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
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from time import perf_counter

import httpx2
from fastapi import FastAPI
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.responses import JSONResponse

from akorin.api import agent
from akorin.api import docs
from akorin.api import health
from akorin.components.isakoso import IsakosoClient
from akorin.components.isinmi import IsinmiClient
from akorin.components.kansa import KansaClient
from akorin.components.ojo import OjoClient
from akorin.components.rediyo import RediyoClient
from akorin.core.components import ComponentClient
from akorin.core.components import ensure_components_available
from akorin.core.components import monitor_unavailable_components
from akorin.core.context import set_app_context_components_registry
from akorin.core.context import set_app_context_components_statuses
from akorin.core.context import set_app_context_orchestrator
from akorin.core.context import set_app_context_settings
from akorin.core.orchestrator import Orchestrator
from akorin.core.package import APP_DESCRIPTION
from akorin.core.package import APP_NAME
from akorin.core.package import APP_VERSION
from akorin.core.service import Service
from akorin.core.settings import log_group
from akorin.core.settings import Settings
from akorin.core.tools import ToolRegistry
from akorin.tools.calculator_tool import CalculatorTool
from akorin.tools.datetime_tool import DateTimeTool
from akorin.tools.unit_conversion_tool import UnitConversionTool
from akorin.utils.cache import SmartCache
from akorin.utils.logger import configure_logging
from akorin.utils.ollama_model import load_ollama_model
from akorin.utils.url import safe_url


logger = logging.getLogger(__name__)


def create_app(settings: Settings, http_client: httpx2.AsyncClient | None = None) -> FastAPI:
  @asynccontextmanager
  async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    startup_started = perf_counter()
    ready = False
    service_endpoints = {service.value: safe_url(url) for service, url in settings.service_urls.items()}

    configure_logging(settings.log_level, settings.log_file)

    logger.info(f"{APP_NAME} v{APP_VERSION}")
    logger.info(f"Server: http://{settings.server_host}:{settings.server_port}")
    logger.info(f"API Docs: http://{settings.server_host}:{settings.server_port}/docs/")
    logger.info(f"Components: endpoints={service_endpoints}")

    log_group(settings, "Server", "server_host", "server_port", "api_prefix")
    log_group(
      settings,
      "LLM",
      "llm_model",
      "llm_request_timeout",
      "llm_temperature",
      "llm_max_response_tokens",
      "llm_system_prompt",
      "ollama_base_url",
    )

    log_group(
      settings,
      "Components",
      "isinmi_url",
      "ojo_url",
      "rediyo_url",
      "kansa_url",
      "isakoso_url",
    )

    log_group(settings, "Logging", "log_level", "log_file")
    log_group(
      settings,
      "Smart Cache",
      "llm_cache_enabled",
      "llm_cache_max_entries",
      "llm_cache_ttl_seconds",
      "component_cache_ttl_seconds",
    )

    log_group(
      settings,
      "Performance",
      "request_budget_seconds",
      "spellcheck_timeout_seconds",
      "route_timeout_seconds",
      "skip_spellcheck_max_chars",
      "http_request_timeout",
      "component_cache_stale_seconds",
      "component_circuit_breaker_enabled",
      "component_circuit_breaker_failures",
      "component_circuit_breaker_cooldown_seconds",
    )

    if settings.should_use_ollama:
      if settings.ollama_base_url is None:
        logger.warning("OREMI_AKORIN_OLLAMA_BASE_URL is not configured; LLM-backed endpoints will be unavailable")
      else:
        await load_ollama_model(settings)

    client = http_client or httpx2.AsyncClient(timeout=settings.http_request_timeout, follow_redirects=True)
    smart_cache = SmartCache(enabled=settings.llm_cache_enabled, max_entries=settings.llm_cache_max_entries)

    configured_components = (
      (Service.OREMI_ISINMI, settings.isinmi_url, IsinmiClient),
      (Service.OREMI_OJO, settings.ojo_url, OjoClient),
      (Service.OREMI_REDIYO, settings.rediyo_url, RediyoClient),
      (Service.OREMI_KANSA, settings.kansa_url, KansaClient),
      (Service.OREMI_ISAKOSO, settings.isakoso_url, IsakosoClient),
    )

    components: dict[Service, ComponentClient] = {
      service: component_type(
        name=service,
        url=str(url),
        client=client,
        cache=smart_cache,
        cache_stale_seconds=settings.component_cache_stale_seconds,
        cache_ttl_seconds=settings.component_cache_ttl_seconds,
        circuit_breaker_enabled=settings.component_circuit_breaker_enabled,
        circuit_breaker_failures=settings.component_circuit_breaker_failures,
        circuit_breaker_cooldown_seconds=settings.component_circuit_breaker_cooldown_seconds,
      )
      for service, url, component_type in configured_components
      if url
    }

    component_names = [service.value for service in components]
    logger.info(f"Services configured: external={component_names or ['none']}")

    tools_registry = ToolRegistry([DateTimeTool(), CalculatorTool(), UnitConversionTool()])
    orchestrator = Orchestrator(settings, client, components, cache=smart_cache, tools=tools_registry)

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

    set_app_context_settings(app, settings)
    set_app_context_orchestrator(app, orchestrator)
    set_app_context_components_registry(app, components)
    set_app_context_components_statuses(app, component_statuses)

    try:
      ready = True
      logger.info(
        f"Oremi Akọrin ready: components={len(components)} duration_ms={(perf_counter() - startup_started) * 1000:.1f}"
      )

      yield
    finally:
      shutdown_started = perf_counter()

      if ready:
        logger.info("Shutting down Oremi Akọrin")
      else:
        logger.warning("Oremi Akọrin startup aborted; cleaning up resources")

      retry_stop.set()

      if retry_task is not None:
        await retry_task

      for component in components.values():
        try:
          await component.disconnect()
        except Exception as exception:
          logger.warning(f"Error disconnecting component {component.name}: {exception}")

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
  async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled application error")
    return JSONResponse(status_code=500, content={"detail": "Internal server error", "error": str(exc)})

  @app.get("/", include_in_schema=False)
  async def redirect_to_docs() -> HTMLResponse:
    return HTMLResponse(status_code=307, headers={"Location": prefix + docs.router.prefix + "/"})

  prefix = "" if settings.api_prefix == "/" else settings.api_prefix
  api_prefix = f"{prefix}/api"

  app.include_router(agent.router, prefix=api_prefix)
  app.include_router(health.router, prefix=prefix)
  app.include_router(docs.router, prefix=prefix)

  return app
