# Copyright 2026 Sébastien Demanou. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
import asyncio
import logging
from time import perf_counter
from typing import Any
from typing import Callable
from typing import Sequence

import httpx2

from akorin.core.classifier import ClassificationResult
from akorin.core.classifier import SemanticClassifier
from akorin.core.router import RequestRouter
from akorin.core.router import RouteContext
from akorin.core.router import RouteDecision
from akorin.core.router import RouteSemanticDecision
from akorin.core.service import Service
from akorin.utils.cache import SmartCache

logger = logging.getLogger(__name__)

# Key of the single "choice" question sent to the OpenJev/Jev API.
ROUTING_QUESTION_KEY = "routing"

# Service semantics shared with akorin/agents/command_agent.py so the classifier
# sees the same service definitions as the existing LLM router. Order is stable
# and mirrors CommandAgent's label list.
SERVICE_DESCRIPTIONS: dict[Service, str] = {
  Service.OREMI_ISINMI: "reminders, alarms, timers, calendar, scheduling.",
  Service.OREMI_OJO: "current or future weather, forecast, temperature, air quality, pollen, alerts, or warnings for a place.",
  Service.OREMI_REDIYO: "radio stations.",
  Service.OREMI_KANSA: "podcasts.",
  Service.OREMI_ISAKOSO: "smart home and Zigbee devices, including lights, lamps, switches, plugs, thermostats, blinds, shutters, locks, and commands such as turn on, turn off, allume, éteins, ouvre, ferme, active, désactive.",
  Service.CHAT: "everything else, including current time, current date, or current day.",
}

ROUTING_LABELS: tuple[Service, ...] = tuple(SERVICE_DESCRIPTIONS)

ROUTING_INSTRUCTIONS = "Which Oremi service should handle this request? Classify the user request into exactly one category."


class OpenJevError(Exception):
  """Raised when the OpenJev/SGLang backend cannot produce a classification."""


class OpenJevSglangClassifier(SemanticClassifier):
  """Semantic classifier backed by an OpenJev (Jev-compatible) server on SGLang.

  Implements a minimal subset of the OpenJev HTTP API: a single `choice` question
  against `POST /v1/systemone`. It reuses the application's shared HTTP client and
  the shared SmartCache, bounds concurrency with a semaphore, and is intentionally
  decoupled from AgentClient (used only for semantic routing).
  """

  def __init__(
    self,
    base_url: str,
    client: httpx2.AsyncClient,
    *,
    model: str,
    timeout: float,
    max_concurrency: int,
    cache: SmartCache | None = None,
    cache_ttl_seconds: float = 300.0,
  ):
    self.base_url = base_url.rstrip("/")
    self.client = client
    self.model = model
    self.timeout = timeout
    self.cache = cache
    self.cache_ttl_seconds = cache_ttl_seconds
    self._semaphore = asyncio.Semaphore(max_concurrency)

  async def classify(self, text: str, labels: Sequence[str]) -> ClassificationResult:
    if not labels:
      raise OpenJevError("no classification labels provided")

    cache_key = self._cache_key(text, labels)

    if self.cache is not None and cache_key is not None:
      return await self.cache.get_or_set(cache_key, self.cache_ttl_seconds, lambda: self._classify(text, labels))

    return await self._classify(text, labels)

  def _cache_key(self, text: str, labels: Sequence[str]) -> str | None:
    if self.cache is None:
      return None

    return self.cache.make_key("openjev", {"model": self.model, "labels": list(labels), "text": text})

  async def _classify(self, text: str, labels: Sequence[str]) -> ClassificationResult:
    criteria: dict[str, str | None] = {}

    for label in labels:
      try:
        criteria[label] = SERVICE_DESCRIPTIONS[Service(label)]
      except ValueError:
        criteria[label] = None

    payload = {
      "model": self.model,
      "state": text,
      "questions": {
        ROUTING_QUESTION_KEY: {
          "type": "choice",
          "instructions": ROUTING_INSTRUCTIONS,
          "criteria": criteria,
        },
      },
    }

    async with self._semaphore:
      try:
        response = await self.client.post(
          f"{self.base_url}/v1/systemone",
          json=payload,
          timeout=self.timeout,
        )
      except httpx2.HTTPError as exception:
        raise OpenJevError(f"OpenJev request failed: {exception}") from exception

    if response.status_code >= 400:
      raise OpenJevError(f"OpenJev returned HTTP {response.status_code}")

    try:
      body = response.json()
    except ValueError as exception:
      raise OpenJevError(f"malformed OpenJev response: {exception}") from exception

    return self._parse(body, labels)

  def _parse(self, body: dict[str, Any], labels: Sequence[str]) -> ClassificationResult:
    try:
      answer = body["answers"][ROUTING_QUESTION_KEY]

      if answer.get("type") != "choice":
        raise OpenJevError(f"unexpected answer type: {answer.get('type')!r}")

      label = str(answer["choice"])
      confidence = float(answer["confidence"])
      probabilities = {str(key): float(value) for key, value in (answer.get("probabilities") or {}).items()}
      model = body.get("model")
    except OpenJevError:
      raise
    except (KeyError, TypeError, ValueError) as exception:
      raise OpenJevError(f"malformed OpenJev response: {exception}") from exception

    if label not in labels:
      raise OpenJevError(f"OpenJev returned unknown label {label!r}")

    return ClassificationResult(label=label, confidence=confidence, probabilities=probabilities, model=model)


class OpenJevRouter(RequestRouter):
  """Fast-path semantic router backed by OpenJev/SGLang.

  Returns a RouteSemanticDecision only when the classifier produced a valid,
  confident label. Otherwise returns None so the existing SemanticRouter (LLM)
  takes over. A classifier outage must never make Oremi unavailable.
  """

  def __init__(
    self,
    classifier: SemanticClassifier,
    confidence_threshold: float,
    timeout_calculator: Callable[[float], float],
  ):
    self.classifier = classifier
    self.confidence_threshold = confidence_threshold
    self.timeout_calculator = timeout_calculator

  async def route(self, context: RouteContext) -> RouteDecision | None:
    logger.debug("[%s] Evaluating OpenJevRouter", context.request_id)
    routing_started = perf_counter()
    timeout = self.timeout_calculator(context.started_at)

    try:
      result = await asyncio.wait_for(
        self.classifier.classify(context.request.message, [service.value for service in ROUTING_LABELS]),
        timeout=timeout,
      )
    except asyncio.CancelledError:
      raise
    except Exception as exception:
      # Any classifier failure must degrade to the existing LLM router rather
      # than fail the user request.
      logger.warning("[%s] OpenJevRouter failed: %s", context.request_id, exception)
      return None

    try:
      service = Service(result.label)
    except ValueError:
      logger.warning("[%s] OpenJevRouter returned unknown service %r", context.request_id, result.label)
      return None

    duration_ms = (perf_counter() - routing_started) * 1000.0

    if result.confidence < self.confidence_threshold:
      logger.info(
        "[%s] OpenJevRouter low confidence: service=%s confidence=%.2f threshold=%.2f duration_ms=%.1f",
        context.request_id,
        service.value,
        result.confidence,
        self.confidence_threshold,
        duration_ms,
      )
      return None

    logger.info(
      "[%s] OpenJevRouter decision: service=%s confidence=%.2f duration_ms=%.1f",
      context.request_id,
      service.value,
      result.confidence,
      duration_ms,
    )

    return RouteSemanticDecision(service=service, confidence=result.confidence)
