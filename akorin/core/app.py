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
from contextlib import asynccontextmanager
from time import perf_counter

import httpx
import ollama
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.responses import JSONResponse

from ..api import agent
from ..api import docs
from ..api import health
from ..components.base import ComponentClient
from ..components.base import ensure_components_available
from ..components.base import monitor_unavailable_components
from ..components.isinmi import IsinmiClient
from ..components.kansa import KansaClient
from ..components.rediyo import RediyoClient
from ..components.weather import WeatherClient
from ..components.zigbee import ZigbeeComponent
from ..llm.agents.translator import TranslatorAgent
from ..services.orchestrator import Orchestrator
from ..services.search import SearchService
from ..services.wikipedia import WikipediaService
from ..utils.logger import configure_logging
from ..utils.url import safe_url
from .constants import Language
from .constants import Service
from .context import AppContext
from .mqtt import MQTTService
from .package import APP_DESCRIPTION
from .package import APP_NAME
from .package import APP_VERSION
from .settings import Settings


logger = logging.getLogger(__name__)


async def _pull_ollama_model(settings: Settings) -> None:
  """Pull configured Ollama model if enabled."""
  try:
    client = ollama.AsyncClient(host=settings.ollama_base_url_string, timeout=settings.llm_request_timeout)

    await client.pull(settings.resolve_ollama_model_name(), stream=False)
    logger.info(f"Ollama model ready: {settings.resolve_ollama_model_name()}")
  except Exception as exception:
    logger.warning(f"Could not pull Ollama model {settings.resolve_ollama_model_name()}: {exception}")


def create_app(settings: Settings, http_client: httpx.AsyncClient | None = None) -> FastAPI:
  @asynccontextmanager
  async def lifespan(app: FastAPI):
    startup_started = perf_counter()
    ready = False
    service_endpoints = {service.value: safe_url(url) for service, url in settings.service_urls.items()}

    configure_logging(settings.log_level, settings.log_file)

    logger.info(f"{APP_NAME} v{APP_VERSION}")
    logger.info(f"Server: http://{settings.server_host}:{settings.server_port}")
    logger.info(f"API Docs: http://{settings.server_host}:{settings.server_port}/docs")
    logger.info(f"Components: endpoints={service_endpoints}")

    logger.info(
      "App settings [server]: host=%s port=%s api_prefix=%s", settings.server_host, settings.server_port, settings.api_prefix
    )
    logger.info(
      "App settings [ollama]: model=%s base_url=%s",
      settings.llm_model,
      safe_url(settings.ollama_base_url_string if settings.ollama_base_url is not None else None),
    )
    logger.info(
      "App settings [generation]: request_timeout=%s temperature=%s max_response_tokens=%s system_prompt=%s",
      settings.llm_request_timeout,
      settings.llm_temperature,
      settings.max_response_tokens,
      settings.llm_system_prompt.replace("\n", " ").strip(),
    )
    logger.info(
      "App settings [components]: isinmi=%s weather=%s rediyo=%s kansa=%s",
      safe_url(settings.isinmi_url),
      safe_url(settings.weather_url),
      safe_url(settings.rediyo_url),
      safe_url(settings.kansa_url),
    )
    logger.info(
      "App settings [mqtt]: enabled=%s broker=%s port=%s client_id=%s authentication_configured=%s tls=%s ca_certificate=%s keepalive=%ss",
      settings.is_mqtt_enabled,
      safe_url(settings.mqtt_broker),
      settings.mqtt_port,
      settings.mqtt_client_id or "automatic",
      bool(settings.mqtt_username and settings.mqtt_password),
      settings.mqtt_tls_enabled,
      settings.mqtt_tls_ca_cert or "system/default",
      settings.mqtt_keepalive,
    )
    logger.info(
      "App settings [mqtt topics]: device_base=%s transcription=%s",
      settings.oremi_device_mqtt_topic,
      settings.mqtt_transcription_topic,
    )
    logger.info("App settings [search]: enabled=%s timeout=%ss", settings.search_enabled, settings.search_timeout)
    logger.info("App settings [logging]: level=%s destination=%s", settings.log_level, settings.log_file or "stderr")

    client = http_client or httpx.AsyncClient(timeout=settings.request_timeout)

    if settings.uses_ollama():
      if settings.ollama_base_url is None:
        raise RuntimeError("OREMI_AKORIN_OLLAMA_BASE_URL must be explicitly configured when using an ollama: model")

      await _pull_ollama_model(settings)

    translator_agent = TranslatorAgent(settings, client)

    configured_components = (
      (Service.ISINMI, settings.isinmi_url, IsinmiClient),
      (Service.WEATHER, settings.weather_url, WeatherClient),
      (Service.REDIYO, settings.rediyo_url, RediyoClient),
      (Service.KANSA, settings.kansa_url, KansaClient),
    )

    components: dict[Service, ComponentClient] = {
      service: component_type(service, str(url), client)
      for service, url, component_type in configured_components
      if url is not None
    }

    component_names = [service.value for service in components]
    logger.info(
      f"Services configured: external={component_names or ['none']} "
      f"wikipedia=enabled search={'enabled' if settings.search_enabled else 'disabled'} "
      f"zigbee={'enabled' if settings.is_mqtt_enabled else 'disabled'}"
    )

    async def _uninitialized_processor(_payload):
      raise RuntimeError("MQTT processor is not initialized")

    mqtt = MQTTService(settings, _uninitialized_processor)
    zigbee = ZigbeeComponent(
      mqtt,
      name_translator=lambda name: translator_agent.translate(name, "auto-detected language", Language.EN.value),
    )

    handlers = {
      **components,
      Service.WIKIPEDIA: WikipediaService(client),
      Service.ZIGBEE: zigbee,
    }

    if settings.search_enabled:
      handlers[Service.SEARCH] = SearchService(client, timeout=settings.search_timeout)

    orchestrator = Orchestrator(settings, client, handlers)
    mqtt.processor = orchestrator.process
    if components:
      logger.info(f"Checking {len(components)} configured external component(s)")
      component_statuses = await ensure_components_available(components)
    else:
      logger.info("No external Oremi components configured; starting in chat-only mode")
      component_statuses = {}

    retry_stop = asyncio.Event()
    retry_task = None

    if components:
      retry_task = asyncio.create_task(
        monitor_unavailable_components(
          components,
          component_statuses,
          stop_event=retry_stop,
          interval_seconds=30.0,
        )
      )

    app.state.client = client
    app.state.settings = settings
    app.state.context = AppContext(
      settings=settings,
      components=components,  # type: ignore
      component_statuses=component_statuses,
      orchestrator=orchestrator,
      mqtt=mqtt,
    )

    zigbee_started = False

    try:
      mqtt_ready = await mqtt.start()

      if mqtt_ready:
        zigbee.start()
        zigbee_started = True
      else:
        logger.info("Zigbee startup skipped: MQTT is disabled")

      ready = True
      logger.info(
        f"Oremi Akọrin ready: components={len(components)} "
        f"mqtt={'connected' if mqtt_ready else 'disabled'} "
        f"duration_ms={(perf_counter() - startup_started) * 1000:.1f}"
      )

      yield
    finally:
      shutdown_started = perf_counter()

      if ready:
        logger.info("Shutting down Oremi Akọrin")
      else:
        logger.warning("Oremi Akọrin startup aborted; cleaning up resources")

      if zigbee_started:
        zigbee.stop()

      retry_stop.set()
      if retry_task is not None:
        await retry_task

      mqtt.stop()
      await client.aclose()
      logger.info(f"Oremi Akọrin stopped: duration_ms={(perf_counter() - shutdown_started) * 1000:.1f}")

  app = FastAPI(
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
    title="Oremi Akọrin",
    version=APP_VERSION,
    description=APP_DESCRIPTION,
    root_path=settings.api_prefix,
    servers=[
      {"url": settings.api_prefix},
    ],
    license_info={
      "name": "Apache 2.0",
      "url": "http://www.apache.org/licenses/LICENSE-2.0.html",
    },
    openapi_tags=[
      agent.API_TAG_METADATA,
      health.API_TAG_METADATA,
    ],
  )

  @app.exception_handler(Exception)
  async def unhandled_exception_handler(_, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled application error")
    return JSONResponse(status_code=500, content={"detail": "Internal server error", "error": str(exc)})

  @app.get("/", include_in_schema=False)
  async def redirect_to_docs():
    return HTMLResponse(status_code=307, headers={"Location": docs.router.prefix})

  prefix = "" if settings.api_prefix == "/" else settings.api_prefix
  api_prefix = f"{prefix}/api"

  app.include_router(agent.router, prefix=api_prefix)
  app.include_router(health.router, prefix=prefix)
  app.include_router(docs.router, prefix=prefix)

  return app
