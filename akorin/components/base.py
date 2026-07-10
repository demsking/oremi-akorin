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
from time import monotonic
from time import perf_counter
from typing import Any
from typing import ClassVar

import httpx
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from ..core.constants import Service
from ..core.exceptions import ComponentUnavailable
from ..utils.cache import has_volatile_context
from ..utils.cache import SmartCache
from ..utils.http_retry import request_with_retry
from ..utils.request_context import contextualized_text
from ..utils.request_context import request_context


logger = logging.getLogger(__name__)


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
  endpoint_path: ClassVar[str]
  server_path = "/api/server"
  server_info_model: ClassVar[type[BaseModel]] = ComponentServiceInfo

  def __init__(
    self,
    name: Service,
    url: str,
    client: httpx.AsyncClient,
    cache: SmartCache | None = None,
    *,
    cache_ttl_seconds: float = 0.0,
    cache_stale_seconds: float = 0.0,
    circuit_breaker_enabled: bool = False,
    circuit_breaker_failures: int = 3,
    circuit_breaker_cooldown_seconds: float = 30.0,
  ):
    self.name = name
    self.base_url = str(httpx.URL(url).copy_with(path="/", query=None, fragment=None))
    self.url = self._url(self.endpoint_path)
    self.client = client
    self.cache = cache
    self.cache_ttl_seconds = cache_ttl_seconds
    self.cache_stale_seconds = cache_stale_seconds
    self.circuit_breaker_enabled = circuit_breaker_enabled
    self.circuit_breaker_failures = circuit_breaker_failures
    self.circuit_breaker_cooldown_seconds = circuit_breaker_cooldown_seconds
    self._failure_count = 0
    self._circuit_open_until = 0.0
    self.server_url = self._url(self.server_path)

  def _url(self, path: str) -> str:
    return str(httpx.URL(self.base_url).copy_with(path=path, query=None, fragment=None))

  async def process(self, message: str, language: str, context: dict[str, Any], tags: list[str]) -> tuple[str, Any]:
    raise NotImplementedError

  def request_context(self, context: dict[str, Any]) -> str | None:
    return request_context(context)

  def contextualized_text(self, text: str, context: dict[str, Any]) -> str:
    return contextualized_text(text, context)

  async def request_json(self, method: str, *, path: str | None = None, **kwargs: Any) -> Any:
    started = perf_counter()
    params = kwargs.get("params")
    payload = kwargs.get("json")
    url = self._url(path or self.endpoint_path)

    logger.debug(
      f"Component request started: component={self.name} method={method} url={url} "
      f"query_keys={sorted(params) if isinstance(params, dict) else []} "
      f"body_keys={sorted(payload) if isinstance(payload, dict) else []}"
    )

    async def run_request() -> Any:
      self._raise_if_circuit_open()

      try:
        response = await request_with_retry(
          lambda: self.client.request(method, url, **kwargs),
          str(self.name),
        )

        logger.debug(
          f"Component response received: component={self.name} status={response.status_code} "
          f"duration_ms={(perf_counter() - started) * 1000:.1f}"
        )

        data = response.json()

        if response.is_error:
          if isinstance(data, dict) and data.get("message"):
            return data

          detail = data.get("detail") if isinstance(data, dict) else data

          raise ComponentUnavailable(self.name, f"HTTP {response.status_code}: {detail}")
      except (httpx.HTTPError, ValueError) as exception:
        self._record_failure()
        raise ComponentUnavailable(self.name, str(exception)) from exception
      except ComponentUnavailable:
        self._record_failure()
        raise

      self._record_success()
      return data

    if self.cache is not None and method.upper() == "GET" and self.cache_ttl_seconds > 0 and not has_volatile_context(kwargs):
      cache_key = self.cache.make_key(
        "component",
        {
          "component": self.name.value,
          "method": method.upper(),
          "url": url,
          "params": kwargs.get("params"),
          "json": kwargs.get("json"),
        },
      )

      return await self.cache.get_or_set_stale(
        cache_key,
        self.cache_ttl_seconds,
        self.cache_stale_seconds,
        run_request,
      )

    return await run_request()

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

  def parse_response(self, data: Any) -> tuple[str, Any]:
    if isinstance(data, dict):
      message = data.get("message") or data.get("response") or data.get("answer") or data.get("detail")

      if message:
        return str(message), data

    return str(data), data

  async def get_service_info(self) -> BaseModel:
    try:
      response = await request_with_retry(
        lambda: self.client.get(self.server_url, timeout=1.0),
        str(self.name),
      )
      response.raise_for_status()

      return self.server_info_model.model_validate(response.json())
    except (httpx.HTTPError, ValueError) as exception:
      raise ComponentUnavailable(self.name, f"invalid response from {self.server_url}: {exception}") from exception

  async def available(self) -> bool:
    try:
      await self.get_service_info()

      return True
    except ComponentUnavailable:
      return False


async def ensure_components_available(components: dict[Service, ComponentClient]) -> dict[Service, bool]:
  """Probe configured components and log their availability."""
  component_items = list(components.items())
  results = await asyncio.gather(
    *(component.get_service_info() for _, component in component_items),
    return_exceptions=True,
  )
  statuses: dict[Service, bool] = {}

  for (service, component), result in zip(component_items, results, strict=True):
    if isinstance(result, BaseModel):
      statuses[service] = True
      logger.info(f"Component {service.value} is reachable: {describe_service_info(result)} at {component.server_url}")
    else:
      statuses[service] = False
      logger.error(f"Component {service.value} is unreachable at {component.server_url}: {result}")

  return statuses


async def monitor_unavailable_components(
  components: dict[Service, ComponentClient],
  statuses: dict[Service, bool],
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
      available = isinstance(result, BaseModel)
      previous = statuses.get(service)
      statuses[service] = available
      server_url = getattr(component, "server_url", "unknown")

      if available and previous is not True:
        logger.info(f"Component {service.value} recovered: {describe_service_info(result)} at {server_url}")
      elif not available and previous is not False:
        logger.warning(f"Component {service.value} became unavailable at {server_url}: {result}")
