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
from time import perf_counter
from typing import Any
from uuid import uuid4

import httpx

from ..components.zigbee import ORIGINAL_TEXT_CONTEXT_KEY
from ..core.constants import Language
from ..core.constants import Service
from ..core.exceptions import ComponentRequestError
from ..core.exceptions import ComponentUnavailable
from ..core.exceptions import NoResultFound
from ..core.logger import logger
from ..core.models import ProcessRequest
from ..core.models import ProcessResponse
from ..llm.ollama import OllamaClient
from ..utils.language import detect_language
from .router import rule_route
from .tools import ToolRegistry

KEYWORDS: dict[Service, tuple[str, ...]] = {
  Service.ISINMI: ("alarm", "alarme", "agenda", "remind", "rappel", "schedule", "timer"),
  Service.WEATHER_ALERTS: ("weather alert", "alerte météo", "warning", "vigilance"),
  Service.WEATHER: ("air quality", "forecast", "météo", "pollen", "temperature", "weather"),
  Service.REDIYO: ("radio", "station", "rediyo"),
  Service.KANSA: ("kansa", "podcast", "episode", "épisode"),
  Service.ZIGBEE: ("zigbee", "light", "lamp", "lampe", "switch", "thermostat", "turn on", "turn off", "allume", "éteins"),
  Service.WIKIPEDIA: ("wikipedia", "wikipédia", "encyclopedia", "encyclopédie"),
  Service.SEARCH: ("search", "look up", "recherche", "cherche sur le web", "latest", "current", "actuel"),
}


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
  def __init__(self, ollama: OllamaClient, handlers: dict[Service, Any], tools: ToolRegistry | None = None):
    self.ollama = ollama
    self.handlers = handlers
    self.tools = tools if tools is not None else ToolRegistry()

  async def process(self, request: ProcessRequest) -> ProcessResponse:
    request_id = uuid4().hex[:8]
    processing_started = perf_counter()
    language = request.language or detect_language(request.text)
    processing_text = request.text
    processing_language = language
    ok = True

    logger.debug(
      f"[{request_id}] Processing started: input_chars={len(request.text)} "
      f"requested_language={request.language.value if request.language else 'auto'} "
      f"detected_language={language.value} context_keys={sorted(request.context)} tag_keys={sorted(request.tags)} "
      f"input_text={request.text!r}"
    )

    normalization_started = perf_counter()

    try:
      processing_text = await self.ollama.spellcheck(request.text, language.value)

      logger.debug(
        f"[{request_id}] Spellcheck completed: language={language.value} input_chars={len(request.text)} "
        f"output_chars={len(processing_text)} duration_ms={(perf_counter() - normalization_started) * 1000:.1f} "
        f"source_text={request.text!r} result_text={processing_text!r}"
      )

      if language != Language.EN:
        translation_started = perf_counter()
        translation_source = processing_text
        processing_text = await self.ollama.translate(translation_source, language.value, Language.EN.value)
        processing_language = Language.EN

        logger.debug(
          f"[{request_id}] Input translation completed: source_language={language.value} target_language=en "
          f"output_chars={len(processing_text)} duration_ms={(perf_counter() - translation_started) * 1000:.1f} "
          f"source_text={translation_source!r} result_text={processing_text!r}"
        )
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exception:
      logger.warning(f"[{request_id}] Input normalization failed; processing original request: {exception}")

      processing_text = request.text
      processing_language = language

    routing_started = perf_counter()
    routing_match = rule_route(processing_text, request.context)

    if routing_match is not None:
      service = routing_match.service
      confidence = routing_match.confidence
      routing_source = "rules"
      routing_reason = routing_match.reason
    else:
      routing_source = "ollama"
      routing_reason = "LLM classification"

      try:
        service, confidence = await self.ollama.route(processing_text, processing_language.value)
      except (httpx.HTTPError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exception:
        logger.warning(f"[{request_id}] Ollama routing failed, using keyword router: {exception}")
        service, confidence = heuristic_route(processing_text)
        routing_source = "heuristic"
        routing_reason = "LLM unavailable"

    logger.debug(
      f"[{request_id}] Routing completed: source={routing_source} service={service.value} "
      f"confidence={confidence:.2f} reason={routing_reason!r} "
      f"duration_ms={(perf_counter() - routing_started) * 1000:.1f}"
    )

    try:
      if service == Service.CHAT:
        logger.debug(f"[{request_id}] Dispatching to Ollama chat with {len(self.tools.definitions)} tools")
        dispatch_started = perf_counter()

        chat_result = await self.ollama.chat_with_tools(processing_text, processing_language.value, request.context, self.tools)
        message = chat_result.message
        service = Service.TOOL if chat_result.tools else Service.CHAT
        confidence = 1.0 if chat_result.tools else confidence
        data: Any = {"tools": [result.data | {"name": result.name} for result in chat_result.tools]}

        logger.debug(
          f"[{request_id}] Ollama chat completed: service={service.value} "
          f"tools={[result.name for result in chat_result.tools]} "
          f"duration_ms={(perf_counter() - dispatch_started) * 1000:.1f}"
        )

        if not chat_result.tools:
          data = {}
      else:
        handler = self.handlers.get(service)

        if handler is None:
          raise ComponentUnavailable(service, "component is not configured")

        logger.debug(
          f"[{request_id}] Dispatching request: service={service.value} handler={type(handler).__name__}"
        )
        dispatch_started = perf_counter()
        handler_context = request.context

        if service == Service.ZIGBEE:
          handler_context = {**request.context, ORIGINAL_TEXT_CONTEXT_KEY: request.text}

        message, data = await handler.process(
          processing_text,
          processing_language.value,
          handler_context,
          request.tags,
        )

        logger.debug(
          f"[{request_id}] Service completed: service={service.value} "
          f"duration_ms={(perf_counter() - dispatch_started) * 1000:.1f} "
          f"data_keys={sorted(data) if isinstance(data, dict) else []}"
        )

        if service == Service.WIKIPEDIA:
          synthesis_started = perf_counter()

          try:
            message = await self.ollama.answer_from_source(processing_text, message, processing_language.value)
          except httpx.HTTPError as exception:
            raise ComponentUnavailable(Service.WIKIPEDIA, str(exception)) from exception

          logger.debug(
            f"[{request_id}] Wikipedia answer synthesis completed: "
            f"duration_ms={(perf_counter() - synthesis_started) * 1000:.1f}"
          )

        if isinstance(data, dict) and data.get("ok") is False:
          ok = False
    except NoResultFound as exception:
      logger.info(f"[{request_id}] {exception.service} returned no result; falling back to web search")
      search = self.handlers.get(Service.SEARCH)

      if search is None:
        ok = False
        message = self._component_failure_message(Service.SEARCH, processing_language)
        data = {"error": {"type": "service_temporarily_unavailable"}}
      else:
        try:
          fallback_started = perf_counter()
          message, data = await search.process(processing_text, processing_language.value, request.context, request.tags)
          service = Service.SEARCH
          confidence = min(confidence, 0.7)

          logger.debug(
            f"[{request_id}] Web search fallback completed: "
            f"duration_ms={(perf_counter() - fallback_started) * 1000:.1f}"
          )
        except ComponentUnavailable as search_error:
          logger.warning(f"[{request_id}] Web search fallback failed: {search_error.reason}")

          ok = False
          service = Service.SEARCH
          message = self._component_failure_message(Service.SEARCH, processing_language)
          data = {"error": {"type": "service_temporarily_unavailable"}}
    except ComponentRequestError as exception:
      logger.info(f"[{request_id}] {service} needs more information: {exception.reason}")

      ok = False
      message = exception.message_fr if processing_language == Language.FR else exception.message_en
      data = {"error": {"type": "more_information_required"}}
    except ComponentUnavailable as exception:
      logger.warning(f"[{request_id}] {service} failed to process the request: {exception.reason}")

      ok = False
      message = self._component_failure_message(exception.component, processing_language)
      data = {"error": {"type": "service_temporarily_unavailable"}}
    except (httpx.HTTPError, KeyError) as exception:
      logger.warning(f"[{request_id}] {service} failed, falling back to chat: {exception}")

      service = Service.CHAT
      confidence = min(confidence, 0.5)
      fallback_tools = []

      try:
        chat_result = await self.ollama.chat_with_tools(processing_text, processing_language.value, request.context, self.tools)
        message = chat_result.message
        fallback_tools = chat_result.tools

        if chat_result.tools:
          service = Service.TOOL
          confidence = 1.0
      except httpx.HTTPError:
        message = (
          "I cannot reach the requested service right now."
          if processing_language == Language.EN
          else "Je ne peux pas joindre le service demandé pour le moment."
        )

      data = {"fallback_reason": str(exception)}

      if fallback_tools:
        data["tools"] = [result.data | {"name": result.name} for result in fallback_tools]

    if language != Language.EN and processing_language == Language.EN:
      translation_started = perf_counter()

      try:
        translation_source = message
        message = await self.ollama.translate(translation_source, Language.EN.value, language.value)
        logger.debug(
          f"[{request_id}] Response translation completed: source_language=en target_language={language.value} "
          f"output_chars={len(message)} duration_ms={(perf_counter() - translation_started) * 1000:.1f} "
          f"source_text={translation_source!r} result_text={message!r}"
        )
      except (httpx.HTTPError, KeyError, TypeError, ValueError) as exception:
        logger.warning(f"[{request_id}] Response translation failed; returning English response: {exception}")

    response = ProcessResponse(
      ok=ok,
      input=request.text,
      language=language,
      service=service,
      message=message,
      data=data,
      confidence=confidence,
    )

    logger.debug(
      f"[{request_id}] Processing completed: ok={response.ok} service={response.service.value} "
      f"language={response.language.value} confidence={response.confidence:.2f} "
      f"response_chars={len(response.message)} "
      f"data_keys={sorted(response.data) if isinstance(response.data, dict) else []} "
      f"duration_ms={(perf_counter() - processing_started) * 1000:.1f} response={response.message!r}"
    )

    return response

  def _component_failure_message(self, component: Service, language: Language) -> str:
    return FAILURE_MESSAGES.get(component, FAILURE_FALLBACK_MESSAGE)[language]


FAILURE_MESSAGES: dict[Service, dict[Language, str]] = {
  Service.ISINMI: {
    Language.EN: "I can't access your reminders and alarms right now. Please try again shortly.",
    Language.FR: "Je n'arrive pas à accéder à vos rappels et alarmes pour l'instant. Réessayez dans un instant, je vous prie.",
  },
  Service.WEATHER: {
    Language.EN: "I can't retrieve the weather right now. Please try again shortly.",
    Language.FR: "Je ne parviens pas à obtenir la météo actuelle. Veuillez réessayer sous peu.",
  },
  Service.WEATHER_ALERTS: {
    Language.EN: "I can't retrieve weather alerts right now. Please try again shortly.",
    Language.FR: "Les alertes météo sont momentanément indisponibles. Merci de réessayer plus tard.",
  },
  Service.REDIYO: {
    Language.EN: "I can't find a radio station right now. Please try again shortly.",
    Language.FR: "Je ne trouve aucune station de radio pour le moment. Réessayez dans quelques instants.",
  },
  Service.KANSA: {
    Language.EN: "I can't find a podcast right now. Please try again shortly.",
    Language.FR: "Aucun podcast n'est disponible actuellement. Veuillez renouveler votre essai dans un moment.",
  },
  Service.ZIGBEE: {
    Language.EN: "I can't control your connected device right now. Please try again shortly.",
    Language.FR: "Je ne peux pas commander votre appareil connecté pour l'instant. Réessayez un peu plus tard.",
  },
  Service.SEARCH: {
    Language.EN: "I can't search online right now. Please try again shortly.",
    Language.FR: "La recherche en ligne est temporairement inaccessible. Merci de réessayer bientôt.",
  },
  Service.WIKIPEDIA: {
    Language.EN: "I can't access Wikipedia right now. Please try again shortly.",
    Language.FR: "Wikipédia est indisponible pour le moment. Veuillez tenter à nouveau dans un instant.",
  },
}

FAILURE_FALLBACK_MESSAGE = {
  Language.EN: "I can't complete your request right now. Please try again shortly.",
  Language.FR: "Je ne peux pas traiter votre demande actuellement. Réessayez dans quelques instants, s'il vous plaît.",
}
