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
import inspect
from time import perf_counter

import httpx2
import pytest
from pydantic_ai.models.test import TestModel

from akorin.agents.command_agent import CommandAgent
from akorin.core.agent import AgentClient
from akorin.core.app import create_app
from akorin.core.classifier import ClassificationResult
from akorin.core.orchestrator import Orchestrator
from akorin.core.request import ProcessRequest
from akorin.core.router import RouteContext
from akorin.core.router import RouteSemanticDecision
from akorin.core.service import Service
from akorin.core.settings import Settings
from akorin.core.tools import ToolRegistry
from akorin.routers.openjev import OpenJevError
from akorin.routers.openjev import OpenJevRouter
from akorin.routers.openjev import OpenJevSglangClassifier
from akorin.utils.cache import SmartCache


ROUTING_LABELS = ("isinmi", "ojo", "rediyo", "kansa", "isakoso", "chat")


def make_context(message: str = "What is the weather in Lagos?") -> RouteContext:
  return RouteContext(
    request=ProcessRequest(message=message),
    request_id="req-0001",
    language="en",
    started_at=perf_counter(),
  )


class FakeClassifier:
  def __init__(self, result=None, error=None, delay=0.0):
    self.result = result
    self.error = error
    self.delay = delay
    self.calls = []

  async def classify(self, text, labels):
    self.calls.append((text, tuple(labels)))

    if self.delay:
      await asyncio.sleep(self.delay)

    if self.error is not None:
      raise self.error

    return self.result


def make_router(classifier, threshold=0.5, timeout=1.0) -> OpenJevRouter:
  return OpenJevRouter(
    classifier=classifier,
    confidence_threshold=threshold,
    timeout_calculator=lambda started: timeout,
  )


def choice_response(choice="ojo", confidence=0.95, probabilities=None) -> httpx2.Response:
  if probabilities is None:
    probabilities = {choice: 1.0}

  return httpx2.Response(
    200,
    json={
      "model": "jev-latest",
      "answers": {
        "routing": {
          "type": "choice",
          "choice": choice,
          "probabilities": probabilities,
          "confidence": confidence,
        },
      },
      "usage": {"input_tokens": 10, "output_tokens": 2},
    },
  )


def make_classifier(handler, **overrides) -> OpenJevSglangClassifier:
  kwargs = {
    "base_url": "http://openjev.test",
    "client": httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
    "model": "jev-latest",
    "timeout": 5.0,
    "max_concurrency": 4,
  }
  kwargs.update(overrides)
  return OpenJevSglangClassifier(**kwargs)


# --- Router unit tests (fake classifier) ---


@pytest.mark.asyncio
async def test_router_accepts_confident_classification():
  result = ClassificationResult(label="ojo", confidence=0.9, probabilities={"ojo": 0.9, "chat": 0.1})
  router = make_router(FakeClassifier(result=result), threshold=0.5)

  decision = await router.route(make_context())

  assert isinstance(decision, RouteSemanticDecision)
  assert decision.service == Service.OREMI_OJO
  assert decision.confidence == pytest.approx(0.9)


@pytest.mark.asyncio
async def test_router_passes_all_routable_labels():
  fake = FakeClassifier(result=ClassificationResult(label="chat", confidence=0.9))
  router = make_router(fake)

  await router.route(make_context())

  assert fake.calls[0][1] == ROUTING_LABELS


@pytest.mark.asyncio
async def test_router_returns_none_below_threshold():
  result = ClassificationResult(label="ojo", confidence=0.4)
  router = make_router(FakeClassifier(result=result), threshold=0.5)

  assert await router.route(make_context()) is None


@pytest.mark.asyncio
async def test_router_returns_none_on_classifier_error():
  router = make_router(FakeClassifier(error=OpenJevError("backend unavailable")))

  assert await router.route(make_context()) is None


@pytest.mark.asyncio
async def test_router_returns_none_on_timeout():
  fake = FakeClassifier(result=ClassificationResult(label="chat", confidence=0.9), delay=0.05)
  router = make_router(fake, timeout=0.005)

  assert await router.route(make_context()) is None


@pytest.mark.asyncio
async def test_router_returns_none_on_unknown_label():
  result = ClassificationResult(label="bogus", confidence=0.99)
  router = make_router(FakeClassifier(result=result))

  assert await router.route(make_context()) is None


# --- Classifier client tests (httpx2.MockTransport) ---


@pytest.mark.asyncio
async def test_classifier_returns_parsed_result():
  classifier = make_classifier(lambda request: choice_response("ojo", 0.95, {"ojo": 0.95, "chat": 0.05}))

  result = await classifier.classify("What is the weather in Lagos?", ROUTING_LABELS)

  assert result.label == "ojo"
  assert result.confidence == pytest.approx(0.95)
  assert result.probabilities == {"ojo": 0.95, "chat": 0.05}
  assert result.model == "jev-latest"


@pytest.mark.asyncio
async def test_classifier_sends_choice_question_payload():
  captured = {}

  def handler(request: httpx2.Request) -> httpx2.Response:
    captured["url"] = str(request.url)
    captured["body"] = request.read().decode("utf-8")
    return choice_response("chat", 0.99)

  classifier = make_classifier(handler)

  await classifier.classify("Turn on the lights", ROUTING_LABELS)

  import json

  body = json.loads(captured["body"])

  assert captured["url"] == "http://openjev.test/v1/systemone"
  assert body["model"] == "jev-latest"
  assert body["state"] == "Turn on the lights"
  assert body["questions"]["routing"]["type"] == "choice"
  assert list(body["questions"]["routing"]["criteria"]) == list(ROUTING_LABELS)


@pytest.mark.asyncio
async def test_classifier_raises_on_http_error():
  classifier = make_classifier(lambda request: httpx2.Response(503, json={"detail": "unavailable"}))

  with pytest.raises(OpenJevError):
    await classifier.classify("hello", ROUTING_LABELS)


@pytest.mark.asyncio
async def test_classifier_raises_on_malformed_json():
  classifier = make_classifier(lambda request: httpx2.Response(200, content=b"not-json"))

  with pytest.raises(OpenJevError):
    await classifier.classify("hello", ROUTING_LABELS)


@pytest.mark.asyncio
async def test_classifier_raises_on_missing_answer_keys():
  classifier = make_classifier(lambda request: httpx2.Response(200, json={"model": "jev-latest"}))

  with pytest.raises(OpenJevError):
    await classifier.classify("hello", ROUTING_LABELS)


@pytest.mark.asyncio
async def test_classifier_raises_on_unknown_label():
  classifier = make_classifier(lambda request: choice_response("bogus", 0.99))

  with pytest.raises(OpenJevError):
    await classifier.classify("hello", ROUTING_LABELS)


@pytest.mark.asyncio
async def test_classifier_raises_on_connect_error():
  def handler(request: httpx2.Request) -> httpx2.Response:
    raise httpx2.ConnectError("connection refused")

  classifier = make_classifier(handler)

  with pytest.raises(OpenJevError):
    await classifier.classify("hello", ROUTING_LABELS)


@pytest.mark.asyncio
async def test_classifier_raises_on_read_timeout():
  def handler(request: httpx2.Request) -> httpx2.Response:
    raise httpx2.ReadTimeout("timed out")

  classifier = make_classifier(handler)

  with pytest.raises(OpenJevError):
    await classifier.classify("hello", ROUTING_LABELS)


@pytest.mark.asyncio
async def test_classifier_raises_on_empty_labels():
  classifier = make_classifier(lambda request: choice_response("chat", 0.99))

  with pytest.raises(OpenJevError):
    await classifier.classify("hello", [])


# --- Cache behavior ---


@pytest.mark.asyncio
async def test_classifier_caches_identical_requests():
  calls = []

  def handler(request: httpx2.Request) -> httpx2.Response:
    calls.append(1)
    return choice_response("chat", 0.99)

  cache = SmartCache(enabled=True, max_entries=16)
  classifier = make_classifier(handler, cache=cache, cache_ttl_seconds=60.0)

  first = await classifier.classify("Turn on the lights", ROUTING_LABELS)
  second = await classifier.classify("Turn on the lights", ROUTING_LABELS)

  assert first.label == second.label == "chat"
  assert len(calls) == 1


@pytest.mark.asyncio
async def test_classifier_does_not_cache_failures():
  attempts = []

  def handler(request: httpx2.Request) -> httpx2.Response:
    attempts.append(1)
    raise httpx2.ConnectError("connection refused")

  cache = SmartCache(enabled=True, max_entries=16)
  classifier = make_classifier(handler, cache=cache, cache_ttl_seconds=60.0)

  for _ in range(2):
    with pytest.raises(OpenJevError):
      await classifier.classify("hello", ROUTING_LABELS)

  assert len(attempts) == 2

# --- Orchestrator wiring (router precedence + disable) ---


def openjev_settings(**overrides) -> Settings:
  values = {
    "llm_model": "ollama:qwen3.5:2b",
    "ollama_base_url": "http://localhost:11434",
    "isinmi_url": None,
    "ojo_url": None,
    "rediyo_url": None,
    "kansa_url": None,
    "isakoso_url": None,
    "openjev_url": None,
  }
  values.update(overrides)
  return Settings(**values)


def make_orchestrator(settings) -> Orchestrator:
  client = httpx2.AsyncClient()
  return Orchestrator(settings, client, {}, ToolRegistry([]), SmartCache(enabled=False, max_entries=0))


@pytest.mark.asyncio
async def test_orchestrator_includes_openjev_router_before_semantic():
  orchestrator = make_orchestrator(openjev_settings(openjev_url="http://openjev.test"))
  names = [type(router).__name__ for router in orchestrator.routers]

  assert names == ["SpacyRouter", "McpPromptRouter", "OpenJevRouter", "SemanticRouter"]


@pytest.mark.asyncio
async def test_orchestrator_omits_openjev_router_when_disabled():
  orchestrator = make_orchestrator(openjev_settings())
  names = [type(router).__name__ for router in orchestrator.routers]

  assert names == ["SpacyRouter", "McpPromptRouter", "SemanticRouter"]


# --- End-to-end fallback and precedence through the public API ---


def app_settings(**overrides) -> Settings:
  values = {
    "llm_model": "test",
    "ollama_base_url": None,
    "isinmi_url": None,
    "ojo_url": None,
    "rediyo_url": None,
    "kansa_url": None,
    "isakoso_url": None,
    "openjev_url": None,
  }
  values.update(overrides)
  return Settings(**values)


def build_model_for(command_service: str, chat_text: str):
  def mock_build_model(settings, model_settings, client):
    frame = inspect.currentframe()

    while frame:
      caller_self = frame.f_locals.get("self")

      if isinstance(caller_self, CommandAgent):
        return TestModel(custom_output_args={"service": command_service, "confidence": 0.9})

      frame = frame.f_back

    return TestModel(call_tools=[], custom_output_text=chat_text)

  return mock_build_model


async def post_agent_message(app, message: str) -> dict:
  transport = httpx2.ASGITransport(app=app)

  async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
    response = await client.post("/api/agent/", json={"text": message})

  assert response.status_code == 200
  return response.json()


@pytest.mark.asyncio
async def test_openjev_low_confidence_falls_back_to_semantic_router(monkeypatch):
  def openjev_handler(request: httpx2.Request) -> httpx2.Response:
    if request.url.path == "/v1/systemone":
      return choice_response("ojo", confidence=0.1, probabilities={"ojo": 0.1, "chat": 0.9})
    return httpx2.Response(200, json={"message": "ok"})

  monkeypatch.setattr(AgentClient, "build_model", staticmethod(build_model_for("chat", "Sure.")))

  service_client = httpx2.AsyncClient(transport=httpx2.MockTransport(openjev_handler))
  app = create_app(app_settings(openjev_url="http://openjev.test"), service_client)

  async with app.router.lifespan_context(app):
    body = await post_agent_message(app, "Explain quantum entanglement simply.")

  assert body["service"] == "chat"
  assert body["ok"] is True


@pytest.mark.asyncio
async def test_openjev_confident_decision_beats_semantic_router(monkeypatch):
  def openjev_handler(request: httpx2.Request) -> httpx2.Response:
    if request.url.path == "/v1/systemone":
      return choice_response("chat", confidence=0.99, probabilities={"chat": 0.99, "ojo": 0.01})
    return httpx2.Response(200, json={"message": "ok"})

  # Semantic router would route to "ojo"; OpenJev must win with "chat".
  monkeypatch.setattr(AgentClient, "build_model", staticmethod(build_model_for("ojo", "Sure.")))

  service_client = httpx2.AsyncClient(transport=httpx2.MockTransport(openjev_handler))
  app = create_app(app_settings(openjev_url="http://openjev.test"), service_client)

  async with app.router.lifespan_context(app):
    body = await post_agent_message(app, "Explain quantum entanglement simply.")

  assert body["service"] == "chat"
  assert body["ok"] is True


# --- Fail-safe behavior and concurrency limit ---


@pytest.mark.asyncio
async def test_router_falls_back_on_unexpected_exception():
  router = make_router(FakeClassifier(error=RuntimeError("classifier bug")), threshold=0.5)

  decision = await router.route(make_context())

  assert decision is None


@pytest.mark.asyncio
async def test_classifier_respects_max_concurrency():
  in_flight = 0
  peak = 0

  async def handler(request: httpx2.Request) -> httpx2.Response:
    nonlocal in_flight, peak
    in_flight += 1
    peak = max(peak, in_flight)
    await asyncio.sleep(0.02)
    in_flight -= 1

    return choice_response("chat", 0.99)

  classifier = make_classifier(handler, max_concurrency=1)

  await asyncio.gather(*(classifier.classify(f"message {index}", ROUTING_LABELS) for index in range(5)))

  assert peak == 1


@pytest.mark.asyncio
async def test_classifier_payload_matches_openjev_choice_schema():
  import json

  captured = {}

  def handler(request: httpx2.Request) -> httpx2.Response:
    captured["body"] = request.read().decode("utf-8")

    return choice_response("ojo", 0.97)

  classifier = make_classifier(handler)

  await classifier.classify("Quel temps fait-il ?", ROUTING_LABELS)

  body = json.loads(captured["body"])
  question = body["questions"]["routing"]

  assert body["model"] == "jev-latest"
  assert isinstance(body["state"], str)
  assert question["type"] == "choice"
  assert isinstance(question["instructions"], str) and question["instructions"]
  assert set(question["criteria"]) == set(ROUTING_LABELS)
  assert all(isinstance(value, str) and value for value in question["criteria"].values())


