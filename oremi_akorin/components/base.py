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
from time import perf_counter
from typing import Any
from typing import ClassVar

import httpx
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from ..core.constants import Service
from ..core.exceptions import ComponentUnavailable
from ..core.logger import logger
from ..utils.http_retry import request_with_retry
from ..utils.request_context import contextualized_text
from ..utils.request_context import request_context


class ComponentServiceInfo(BaseModel):
  model_config = ConfigDict(str_strip_whitespace=True)

  name: str = Field(min_length=1)
  version: str = Field(min_length=1)


class ComponentClient:
  endpoint_path: ClassVar[str]
  server_path = "/api/server"

  def __init__(self, name: Service, url: str, client: httpx.AsyncClient):
    self.name = name
    self.base_url = str(httpx.URL(url).copy_with(path="/", query=None, fragment=None))
    self.url = self._url(self.endpoint_path)
    self.client = client
    self.server_url = self._url(self.server_path)

  def _url(self, path: str) -> str:
    return str(httpx.URL(self.base_url).copy_with(path=path, query=None, fragment=None))

  async def process(self, text: str, language: str, context: dict[str, Any], tags: dict[str, str]) -> tuple[str, Any]:
    raise NotImplementedError

  def request_context(self, context: dict[str, Any]) -> str | None:
    return request_context(context)

  def contextualized_text(self, text: str, context: dict[str, Any]) -> str:
    return contextualized_text(text, context)

  async def request_json(self, method: str, **kwargs: Any) -> Any:
    started = perf_counter()
    params = kwargs.get("params")
    payload = kwargs.get("json")

    logger.debug(
      f"Component request started: component={self.name} method={method} url={self.url} "
      f"query_keys={sorted(params) if isinstance(params, dict) else []} "
      f"body_keys={sorted(payload) if isinstance(payload, dict) else []}"
    )

    try:
      response = await request_with_retry(
        lambda: self.client.request(method, self.url, **kwargs),
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
      raise ComponentUnavailable(self.name, str(exception)) from exception

    return data

  def parse_response(self, data: Any) -> tuple[str, Any]:
    if isinstance(data, dict):
      message = data.get("message") or data.get("response") or data.get("answer") or data.get("detail")

      if message:
        return str(message), data

    return str(data), data

  async def get_service_info(self) -> ComponentServiceInfo:
    try:
      response = await request_with_retry(
        lambda: self.client.get(self.server_url, timeout=1.0),
        str(self.name),
      )
      response.raise_for_status()

      return ComponentServiceInfo.model_validate(response.json())
    except (httpx.HTTPError, ValueError) as exception:
      raise ComponentUnavailable(self.name, f"invalid response from {self.server_url}: {exception}") from exception

  async def available(self) -> bool:
    try:
      await self.get_service_info()

      return True
    except ComponentUnavailable:
      return False
