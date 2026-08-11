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
from contextlib import AsyncExitStack
from time import monotonic
from typing import Any

import httpx2
from mcp import ClientSession
from mcp import Resource
from mcp.client.streamable_http import streamable_http_client
from mcp_types import Implementation
from mcp_types import Prompt
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from akorin.core.exceptions import ComponentUnavailable
from akorin.core.oremi import OremiServerHealth
from akorin.core.service import Service
from akorin.core.tools import MCPTool
from akorin.utils.cache import has_volatile_context
from akorin.utils.cache import SmartCache

logger = logging.getLogger(__name__)
ComponentsRegistry = dict[Service, "ComponentClient"]
ComponentsStatuses = dict[Service, bool]


class ComponentServiceInfo(BaseModel):
  model_config = ConfigDict(str_strip_whitespace=True)

  name: str = Field(min_length=1)
  version: str = Field(min_length=1)


def describe_service_info(info: BaseModel) -> str:
  name = getattr(info, "name", None) or getattr(info, "app", None) or info.__class__.__name__
  version = getattr(info, "version", None) or "unknown"
  details: list[str] = [f"{name}/{version}"]

  status = getattr(info, "status", None)
  if status:
    details.append(f"status={status}")

  llm_model = getattr(info, "llm_model", None)
  if llm_model:
    details.append(f"llm_model={llm_model}")

  return " ".join(details)


class ComponentClient:
  def __init__(
    self,
    name: Service,
    url: str,
    client: httpx2.AsyncClient,
    cache: SmartCache,
    *,
    cache_ttl_seconds: float = 60.0,
    cache_stale_seconds: float = 30.0,
    circuit_breaker_enabled: bool = True,
    circuit_breaker_failures: int = 5,
    circuit_breaker_cooldown_seconds: float = 30.0,
  ):
    self.name = name
    self.server_url = url
    self.client = client
    self.cache = cache
    self.cache_ttl_seconds = cache_ttl_seconds
    self.cache_stale_seconds = cache_stale_seconds
    self.circuit_breaker_enabled = circuit_breaker_enabled
    self.circuit_breaker_failures = circuit_breaker_failures
    self.circuit_breaker_cooldown_seconds = circuit_breaker_cooldown_seconds
    self._failure_count = 0
    self._circuit_open_until = 0.0

    self._session: ClientSession | None = None
    self._exit_stack: AsyncExitStack | None = None
    self._lock = asyncio.Lock()
    self._available = False

    self._tools: list[MCPTool] = []
    self._resources: list[Resource] = []
    self._prompts: list[Prompt] = []

    self._server_info: Implementation | None = None

  async def connect(self) -> None:
    self._raise_if_circuit_open()

    async with self._lock:
      if self._session is not None:
        return

      self._exit_stack = AsyncExitStack()
      self._available = False
      self._resources = []
      self._prompts = []
      self._tools = []

      try:
        streams = await self._exit_stack.enter_async_context(streamable_http_client(self.server_url, http_client=self.client))
        read_stream, write_stream = streams[0], streams[1]

        session = await self._exit_stack.enter_async_context(ClientSession(read_stream, write_stream))
        mcp = await session.initialize()

        self._server_info = mcp.server_info

        if mcp.capabilities.tools:
          mcp_tools = await session.list_tools()

          for tool in mcp_tools.tools:
            self._tools.append(
              MCPTool(
                name=tool.name,
                description=tool.description or "",
                input_schema=tool.input_schema,
                call_fn=self.call_tool,
                service=self.name,
              )
            )

        if mcp.capabilities.resources:
          resources_result = await session.list_resources()
          self._resources = resources_result.resources or []

        if mcp.capabilities.prompts:
          prompts_result = await session.list_prompts()
          self._prompts = prompts_result.prompts or []

        self._session = session
        self._available = True
        self._record_success()

        tool_names = ", ".join([t.name for t in self._tools])
        resource_names = ", ".join([str(r.uri) for r in self._resources])
        prompt_names = ", ".join([p.name for p in self._prompts])

        logger.debug(
          f"Connected to MCP server {self.name} at {self.server_url} "
          f"(tools: {tool_names or 'none'}) (resources: {resource_names or 'none'}) (prompts: {prompt_names or 'none'})"
        )
      except asyncio.CancelledError:
        self._record_failure()
        self._available = False
        raise
      except Exception as exception:
        logger.error(f"Failed to connect to MCP server {self.name} at {self.server_url}: {exception}")
        self._record_failure()

        self._available = False

        raise ComponentUnavailable(self.name, str(exception)) from exception
      finally:
        if not self._available:
          await self.disconnect()

  async def disconnect(self) -> None:
    if self._exit_stack is not None:
      try:
        await self._exit_stack.aclose()
      except (KeyboardInterrupt, SystemExit):
        raise
      except BaseException as exception:
        logger.warning(f"Error during disconnect from {self.name}: {exception}")
      finally:
        self._exit_stack = None

    self._session = None
    self._available = False
    self._server_info = None
    self._tools = []
    self._resources = []
    self._prompts = []

  async def get_tools(self) -> list[MCPTool]:
    if self._session is None:
      await self.connect()

    return self._tools

  async def get_resources(self) -> list[Any]:
    if self._session is None:
      await self.connect()

    return self._resources

  async def read_resource(self, uri: str) -> Any:
    self._raise_if_circuit_open()

    try:
      if self._session is None:
        await self.connect()

      if self._session is None:
        raise ComponentUnavailable(self.name, "Failed to establish MCP session")

      result = await self._session.read_resource(uri)

      self._record_success()

      return result
    except ComponentUnavailable as exception:
      raise exception
    except Exception as exception:
      await self.disconnect()
      self._record_failure()
      raise ComponentUnavailable(self.name, str(exception)) from exception

  async def get_prompts(self) -> list[Any]:
    if self._session is None:
      await self.connect()

    return self._prompts

  async def get_prompt(self, name: str, arguments: dict[str, str] | None = None) -> Any:
    self._raise_if_circuit_open()

    try:
      if self._session is None:
        await self.connect()

      if self._session is None:
        raise ComponentUnavailable(self.name, "Failed to establish MCP session")

      result = await self._session.get_prompt(name, arguments)

      self._record_success()

      return result
    except ComponentUnavailable as exception:
      raise exception
    except Exception as exception:
      await self.disconnect()
      self._record_failure()
      raise ComponentUnavailable(self.name, str(exception)) from exception

  async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
    self._raise_if_circuit_open()

    use_cache = not has_volatile_context(arguments)
    cache_key = None

    if use_cache:
      cache_key = self.cache.make_key(f"{self.name.value}:{name}", arguments)
      cached = self.cache.get(cache_key)

      if cached is not None:
        return cached

    try:
      if self._session is None:
        await self.connect()

      if self._session is None:
        raise ComponentUnavailable(self.name, "Failed to establish MCP session")

      result = await self._session.call_tool(name, arguments)

      self._record_success()

      if use_cache and cache_key:
        self.cache.set(cache_key, result, ttl_seconds=self.cache_ttl_seconds)

      return result
    except ComponentUnavailable as exception:
      raise exception
    except Exception as exception:
      await self.disconnect()
      self._record_failure()
      raise ComponentUnavailable(self.name, str(exception)) from exception

  async def get_service_info(self) -> BaseModel:
    if self._session is not None:
      try:
        await self._session.send_ping()
      except Exception as exception:
        logger.warning(f"Ping failed for component {self.name}: {exception}")
        await self.disconnect()

    if self._session is None:
      await self.connect()

    return OremiServerHealth(
      status="healthy",
      app=self._server_info.name if self._server_info else self.name.value,
      version=self._server_info.version if self._server_info else "unknown",
    )

  async def available(self) -> bool:
    try:
      await self.get_service_info()

      return True
    except Exception:
      return False

  def _raise_if_circuit_open(self) -> None:
    if not self.circuit_breaker_enabled:
      return

    remaining = self._circuit_open_until - monotonic()

    if remaining > 0:
      raise ComponentUnavailable(self.name, f"circuit breaker open for {remaining:.1f}s")

  def _record_success(self) -> None:
    self._failure_count = 0
    self._circuit_open_until = 0.0

  def _record_failure(self) -> None:
    if not self.circuit_breaker_enabled:
      return

    self._failure_count += 1

    if self._failure_count >= self.circuit_breaker_failures:
      self._circuit_open_until = monotonic() + self.circuit_breaker_cooldown_seconds

      logger.warning(
        "Component circuit breaker opened: component=%s failures=%s cooldown_seconds=%s",
        self.name.value,
        self._failure_count,
        self.circuit_breaker_cooldown_seconds,
      )


async def ensure_components_available(components: ComponentsRegistry) -> ComponentsStatuses:
  """Probe configured components and log their availability."""
  component_items = list(components.items())
  results = await asyncio.gather(
    *(component.get_service_info() for _, component in component_items),
    return_exceptions=True,
  )
  statuses: ComponentsStatuses = {}

  for (service, component), result in zip(component_items, results, strict=True):
    if isinstance(result, BaseModel):
      statuses[service] = True
      logger.info(f"Component {service.value} is reachable: {describe_service_info(result)} at {component.server_url}")
    else:
      statuses[service] = False
      logger.error(f"Component {service.value} is unreachable at {component.server_url}: {result}")

  return statuses


async def monitor_unavailable_components(
  components: ComponentsRegistry,
  statuses: ComponentsStatuses,
  *,
  stop_event: asyncio.Event,
  interval_seconds: float = 30.0,
) -> None:
  """Continuously retry configured components and update their availability."""
  while True:
    try:
      await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
      return
    except asyncio.TimeoutError:
      pass

    component_items = list(components.items())
    results = await asyncio.gather(
      *(component.get_service_info() for _, component in component_items),
      return_exceptions=True,
    )

    for (service, component), result in zip(component_items, results, strict=True):
      previous = statuses.get(service)
      server_url = getattr(component, "server_url", "unknown")

      if isinstance(result, BaseModel):
        statuses[service] = True

        if previous is not True:
          logger.info(f"Component {service.value} recovered: {describe_service_info(result)} at {server_url}")
      else:
        statuses[service] = False

        if previous is not False:
          logger.warning(f"Component {service.value} became unavailable at {server_url}: {result}")
