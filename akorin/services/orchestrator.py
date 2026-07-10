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
import json
import logging
from time import perf_counter
from typing import Any
from uuid import uuid4

import httpx

from ..components.zigbee import ORIGINAL_TEXT_CONTEXT_KEY
from ..core.constants import Service
from ..core.exceptions import ComponentRequestError
from ..core.exceptions import ComponentUnavailable
from ..core.models import ProcessRequest
from ..core.models import ProcessResponse
from ..core.settings import Settings
from ..llm.agents.chat import ChatAgent
from ..llm.agents.chat_tools import ChatToolsAgent
from ..llm.agents.command import CommandAgent
from ..llm.agents.response import ResponseAgent
from ..llm.agents.spellcheck import SpellCheckAgent
from ..utils.language import detect_language
from .device_commands import select_device_commands
from .device_commands import select_direct_device_command
from .router import rule_route
from .tools import ToolRegistry


logger = logging.getLogger(__name__)

KEYWORDS: dict[Service, tuple[str, ...]] = {
  Service.ISINMI: ("alarm", "alarme", "agenda", "remind", "rappel", "schedule", "timer"),
  Service.WEATHER: ("air quality", "alert", "forecast", "météo", "pollen", "temperature", "warning", "weather"),
  Service.REDIYO: ("radio", "station", "rediyo"),
  Service.KANSA: ("kansa", "podcast", "episode", "épisode"),
  Service.ZIGBEE: ("zigbee", "light", "lamp", "lampe", "switch", "thermostat", "turn on", "turn off", "allume", "éteins"),
}

TEMPORAL_CONTEXT_KEYS = frozenset(("timezone", "datetime", "date_format", "time_format", "first_day_of_week"))
UNIT_CONTEXT_KEYS = frozenset(("temperature_unit", "measurement_system", "distance_unit", "preferred_currency"))
WEATHER_UNIT_CONTEXT_KEYS = frozenset(("temperature_unit", "measurement_system", "distance_unit"))
LOCATION_CONTEXT_KEYS = frozenset(("location", "address", "latitude", "longitude", "lat", "lon"))
SERVICE_CONTEXT_KEYS: dict[Service, frozenset[str]] = {
  Service.CHAT: TEMPORAL_CONTEXT_KEYS | UNIT_CONTEXT_KEYS,
  Service.TOOL: TEMPORAL_CONTEXT_KEYS | UNIT_CONTEXT_KEYS,
  Service.ISINMI: TEMPORAL_CONTEXT_KEYS,
  Service.WEATHER: TEMPORAL_CONTEXT_KEYS | WEATHER_UNIT_CONTEXT_KEYS | LOCATION_CONTEXT_KEYS | frozenset(("alert_service", "service")),
  Service.REDIYO: frozenset(),
  Service.KANSA: frozenset(),
  Service.ZIGBEE: frozenset(("device", "state", "room", "area", "zone")),
}


def context_for_service(service: Service, context: dict[str, Any]) -> dict[str, Any]:
  """Select the context keys a downstream service can use."""
  allowed_keys = SERVICE_CONTEXT_KEYS.get(service, frozenset())

  if not allowed_keys or not context:
    return {}

  selected: dict[str, Any] = {}
  preferences = context.get("preferences")

  if isinstance(preferences, dict):
    selected.update({key: value for key, value in preferences.items() if key in allowed_keys})

  selected.update({key: value for key, value in context.items() if key in allowed_keys})

  if service == Service.WEATHER:
    selected = _normalize_weather_context(selected)

  return selected


def _normalize_weather_context(context: dict[str, Any]) -> dict[str, Any]:
  selected = dict(context)

  if selected.get("lat") is None and selected.get("latitude") is not None:
    selected["lat"] = selected["latitude"]

  if selected.get("lon") is None and selected.get("longitude") is not None:
    selected["lon"] = selected["longitude"]

  return selected


def heuristic_route(text: str) -> tuple[Service, float]:
  match = rule_route(text)

  if match is not None:
    return match.service, match.confidence

  lowered = text.casefold()

  for service, words in KEYWORDS.items():
    if any(word in lowered for word in words):
      return service, 0.72

  return Service.CHAT, 0.55


class Orchestrator:
  def __init__(
    self,
    settings: Settings,
    client: httpx.AsyncClient,
    handlers: dict[Service, Any],
    tools: ToolRegistry | None = None,
  ):
    self.handlers = handlers
    self.tools = tools or ToolRegistry()
    self.chat_agent = ChatAgent(settings, client)
    self.chat_tools_agent = ChatToolsAgent(settings, client)
    self.command_agent = CommandAgent(settings, client)
    self.response_agent = ResponseAgent(settings, client)
    self.spellcheck_agent = SpellCheckAgent(settings, client)

  async def _route(self, message: str, language: str) -> tuple[Service, float]:
    decision = await self.command_agent.classify(message)

    return decision.service, decision.confidence

  async def _chat_with_tools(self, message: str, language: str, context: dict[str, Any]) -> Any:
    return await self.chat_tools_agent.chat(message, language, context, self.tools)

  async def process(self, request: ProcessRequest) -> ProcessResponse:
    request_id = uuid4().hex[:8]
    processing_started = perf_counter()
    language = request.language or detect_language(request.message)
    direct_device_control = select_direct_device_command(request.message, language)

    if direct_device_control is not None:
      _, command = direct_device_control
      message = await self.response_agent.generate(
        "device_command_applied",
        language.value,
        {"command": command.model_dump(mode="json", exclude_none=True), "request": request.message},
      )
      return ProcessResponse(
        input=request.message,
        language=language,
        service=Service.DEVICE,
        message=message,
        confidence=1,
        commands=[command],
      )

    processing_message = request.message
    processing_language = language
    ok = True
    original_routing_match = rule_route(request.message, request.context)

    logger.debug(
      f"[{request_id}] Processing started: input_chars={len(request.message)} "
      f"requested_language={request.language.value if request.language else 'auto'} "
      f"detected_language={language.value} context_keys={sorted(request.context)} tag_count={len(request.tags)} "
      f"input_text={request.message!r}"
    )

    normalization_started = perf_counter()

    try:
      processing_message = await self.spellcheck_agent.check(request.message, language.value)

      logger.debug(
        f"[{request_id}] Spellcheck completed: language={language.value} input_chars={len(request.message)} "
        f"output_chars={len(processing_message)} duration_ms={(perf_counter() - normalization_started) * 1000:.1f} "
        f"source_text={request.message!r} result_text={processing_message!r}"
      )
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exception:
      logger.warning(f"[{request_id}] Input normalization failed; processing original request: {exception}")

      processing_message = request.message
      processing_language = language

    routing_started = perf_counter()
    routing_match = original_routing_match or rule_route(processing_message, request.context)

    if routing_match is not None:
      service = routing_match.service
      confidence = routing_match.confidence
      routing_source = "rules"
      routing_reason = routing_match.reason
    else:
      routing_source = "agent"
      routing_reason = "LLM classification"

      try:
        service, confidence = await self._route(processing_message, language.value)
      except (httpx.HTTPError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exception:
        logger.warning(f"[{request_id}] Agent routing failed, using keyword router: {exception}")
        service, confidence = heuristic_route(processing_message)
        routing_source = "heuristic"
        routing_reason = "LLM unavailable"

    logger.debug(
      f"[{request_id}] Routing completed: source={routing_source} service={service.value} "
      f"confidence={confidence:.2f} reason={routing_reason!r} "
      f"duration_ms={(perf_counter() - routing_started) * 1000:.1f}"
    )

    try:
      if service == Service.CHAT:
        logger.debug(f"[{request_id}] Dispatching to agent chat with {len(self.tools.definitions)} tools")
        dispatch_started = perf_counter()

        chat_context = context_for_service(Service.CHAT, request.context)
        chat_result = await self._chat_with_tools(processing_message, processing_language.value, chat_context)
        message = chat_result.message
        service = Service.TOOL if chat_result.tools else Service.CHAT
        confidence = 1.0 if chat_result.tools else confidence
        data: Any = {"tools": [result.data | {"name": result.name} for result in chat_result.tools]}

        logger.debug(
          f"[{request_id}] Agent chat completed: service={service.value} "
          f"tools={[result.name for result in chat_result.tools]} "
          f"duration_ms={(perf_counter() - dispatch_started) * 1000:.1f}"
        )

        if not chat_result.tools:
          data = {}
      else:
        handler = self.handlers.get(service)

        if handler is None:
          raise ComponentUnavailable(service, "component is not configured")

        logger.debug(f"[{request_id}] Dispatching request: service={service.value} handler={type(handler).__name__}")
        dispatch_started = perf_counter()
        handler_context = context_for_service(service, request.context)

        if service == Service.ZIGBEE:
          handler_context = {**handler_context, ORIGINAL_TEXT_CONTEXT_KEY: request.message}

        message, data = await handler.process(
          processing_message,
          processing_language.value,
          handler_context,
          request.tags,
        )

        logger.debug(
          f"[{request_id}] Service completed: service={service.value} "
          f"duration_ms={(perf_counter() - dispatch_started) * 1000:.1f} "
          f"data_keys={sorted(data) if isinstance(data, dict) else []}"
        )

        if isinstance(data, dict) and data.get("ok") is False:
          ok = False
    except ComponentRequestError as exception:
      logger.info(f"[{request_id}] {service} needs more information: {exception.reason}")

      ok = False
      message = await self.response_agent.generate(
        "component_needs_more_information",
        processing_language.value,
        {"service": service.value, "request": request.message},
      )
      data = {"error": {"type": "more_information_required"}}
    except ComponentUnavailable as exception:
      logger.warning(f"[{request_id}] {service} failed to process the request: {exception.reason}")

      ok = False
      message = await self.response_agent.generate(
        "component_temporarily_unavailable",
        processing_language.value,
        {"service": exception.component.value if isinstance(exception.component, Service) else str(exception.component)},
      )
      data = {"error": {"type": "service_temporarily_unavailable"}}
    except (httpx.HTTPError, KeyError) as exception:
      logger.warning(f"[{request_id}] {service} failed, falling back to chat: {exception}")

      service = Service.CHAT
      confidence = min(confidence, 0.5)
      fallback_tools = []

      try:
        chat_context = context_for_service(Service.CHAT, request.context)
        chat_result = await self._chat_with_tools(processing_message, processing_language.value, chat_context)
        message = chat_result.message
        fallback_tools = chat_result.tools

        if chat_result.tools:
          service = Service.TOOL
          confidence = 1.0
      except httpx.HTTPError:
        message = await self.response_agent.generate(
          "component_temporarily_unavailable",
          processing_language.value,
          {"service": service.value},
        )

      data = {"fallback_reason": str(exception)}

      if fallback_tools:
        data["tools"] = [result.data | {"name": result.name} for result in fallback_tools]

    response = ProcessResponse(
      ok=ok,
      input=request.message,
      language=language,
      service=service,
      message=message,
      data=data,
      confidence=confidence,
    )
    response.commands = select_device_commands(response)

    logger.debug(
      f"[{request_id}] Processing completed: ok={response.ok} service={response.service.value} "
      f"language={response.language.value} confidence={response.confidence:.2f} "
      f"response_chars={len(response.message)} "
      f"data_keys={sorted(response.data) if isinstance(response.data, dict) else []} "
      f"duration_ms={(perf_counter() - processing_started) * 1000:.1f} response={response.message!r}"
    )

    return response
