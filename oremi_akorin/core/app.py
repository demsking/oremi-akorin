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
from contextlib import asynccontextmanager
from time import perf_counter

import httpx
from fastapi import FastAPI

from ..components.base import ComponentClient
from ..components.base import ComponentServiceInfo
from ..components.isinmi import IsinmiClient
from ..components.kansa import KansaClient
from ..components.rediyo import RediyoClient
from ..components.weather import WeatherAlertsClient
from ..components.weather import WeatherClient
from ..components.zigbee import ZigbeeComponent
from ..endpoints.agent import create_agent_endpoints
from ..endpoints.docs import create_docs_endpoints
from ..endpoints.server import create_server_endpoints
from ..llm.ollama import OllamaClient
from ..services.orchestrator import Orchestrator
from ..services.search import SearchService
from ..services.wikipedia import WikipediaService
from ..utils.http_logging import enable_http_request_logging
from .constants import Language
from .constants import Service
from .context import AppContext
from .logger import logger
from .mqtt import MQTTService
from .package import APP_DESCRIPTION
from .package import APP_VERSION
from .settings import Settings


def _safe_endpoint(value: object | None) -> str:
  if value is None:
    return "disabled"

  url = httpx.URL(str(value))
  updates: dict[str, object] = {"query": None, "fragment": None}

  if url.username or url.password:
    updates.update(username="***", password="***")

  return str(url.copy_with(**updates))


def log_startup_settings(config: Settings) -> None:
  service_endpoints = {service.value: _safe_endpoint(url) for service, url in config.service_urls.items()}

  logger.info(
    f"App settings [server]: host={config.server_host} port={config.server_port} "
    f"root_path={config.api_root_path} request_timeout={config.request_timeout:.1f}s"
  )

  logger.info(
    f"App settings [ollama]: host={_safe_endpoint(config.ollama_baseurl)} model={config.ollama_model} "
    f"pull_model={config.ollama_pull_model} request_timeout={config.ollama_request_timeout:.1f}s"
  )

  logger.info(f"App settings [generation]: max_response_tokens={config.max_response_tokens} temperature={config.temperature}")
  logger.info(f"App settings [components]: endpoints={service_endpoints}")

  logger.info(
    f"App settings [mqtt]: enabled={config.is_mqtt_enabled} broker={_safe_endpoint(config.mqtt_broker)} "
    f"port={config.mqtt_port} client_id={config.mqtt_client_id or 'automatic'} "
    f"authentication_configured={bool(config.mqtt_username and config.mqtt_password)} "
    f"tls={config.mqtt_tls_enabled} ca_certificate={config.mqtt_tls_ca_cert or 'system/default'} "
    f"keepalive={config.mqtt_keepalive}s retry=paho-native"
  )

  logger.info(
    f"App settings [mqtt topics]: device_base={config.oremi_device_mqtt_topic} transcription={config.mqtt_transcription_topic}"
  )

  logger.info(f"App settings [search]: enabled={config.search_enabled} timeout={config.search_timeout:.1f}s")
  logger.info(f"App settings [logging]: level={config.log_level} destination={config.log_file or 'stderr'}")


async def ensure_components_available(components: dict[Service, ComponentClient]) -> None:
  """Fail startup when a configured Oremi component cannot be reached."""
  if not components:
    logger.info("No external Oremi components configured; starting in chat-only mode")
    return

  component_items = list(components.items())
  results = await asyncio.gather(
    *(component.get_service_info() for _, component in component_items),
    return_exceptions=True,
  )
  unavailable: list[Service] = []

  for (service, component), result in zip(component_items, results, strict=True):
    if isinstance(result, ComponentServiceInfo):
      logger.info(f"Component {service.value} is reachable: {result.name}/{result.version} at {component.server_url}")
    else:
      logger.error(f"Component {service.value} is unreachable at {component.server_url}: {result}")
      unavailable.append(service)

  if unavailable:
    names = ", ".join(unavailable)

    raise RuntimeError(f"Configured components are unreachable: {names}")


def create_app(settings: Settings, http_client: httpx.AsyncClient | None = None) -> FastAPI:
  @asynccontextmanager
  async def lifespan(app: FastAPI):
    startup_started = perf_counter()
    ready = False
    logger.info(f"Starting Oremi Akọrin {APP_VERSION}")
    log_startup_settings(settings)

    client = http_client or httpx.AsyncClient(timeout=settings.request_timeout)
    enable_http_request_logging(client)
    ollama = OllamaClient(str(settings.ollama_baseurl), settings.ollama_model, client)

    configured_components = (
      (Service.ISINMI, settings.isinmi_url, IsinmiClient),
      (Service.WEATHER, settings.weather_url, WeatherClient),
      (Service.WEATHER_ALERTS, settings.weather_url, WeatherAlertsClient),
      (Service.REDIYO, settings.rediyo_url, RediyoClient),
      (Service.KANSA, settings.kansa_url, KansaClient),
    )

    components = {
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

    mqtt = MQTTService(settings, lambda payload: orchestrator.process(payload))  # pylint: disable=unnecessary-lambda
    zigbee = ZigbeeComponent(
      mqtt,
      name_translator=lambda name: ollama.translate(name, "auto-detected language", Language.EN.value),
    )

    handlers = {
      **components,
      Service.WIKIPEDIA: WikipediaService(client),
      Service.ZIGBEE: zigbee,
    }

    if settings.search_enabled:
      handlers[Service.SEARCH] = SearchService(client, timeout=settings.search_timeout)

    orchestrator = Orchestrator(ollama, handlers)

    app.state.client = client
    app.state.context = AppContext(
      config=settings,
      ollama=ollama,
      components=components,  # type: ignore
      orchestrator=orchestrator,
      mqtt=mqtt,
    )

    zigbee_started = False

    try:
      if settings.ollama_pull_model:
        logger.info(f"Preparing Ollama model: {settings.ollama_model}")

        try:
          await ollama.ensure_model()
          logger.info(f"Ollama model ready: {settings.ollama_model}")
        except httpx.HTTPError as exeption:
          logger.warning(f"Ollama startup preparation failed: {exeption}")
      else:
        logger.info("Ollama model preparation disabled")

      logger.info(f"Checking {len(components)} configured external component(s)")
      await ensure_components_available(components)  # type: ignore
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
    root_path=settings.api_root_path.rstrip("/"),
    servers=[
      {"url": settings.api_root_path},
    ],
    license_info={
      "name": "Apache 2.0",
      "url": "http://www.apache.org/licenses/LICENSE-2.0.html",
    },
    openapi_tags=[],
  )

  create_agent_endpoints(app)
  create_server_endpoints(app)
  create_docs_endpoints(app, settings)

  return app
