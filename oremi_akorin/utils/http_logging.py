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
import httpx

from ..core.logger import logger

_SENSITIVE_PARAM_PARTS = ("key", "password", "secret", "token")


async def log_http_request(request: httpx.Request) -> None:
  """Log final HTTP request options without URL credentials or sensitive params."""
  url = request.url.copy_with(username=None, password=None, query=None, fragment=None)
  params = {
    name: "***" if any(part in name.casefold() for part in _SENSITIVE_PARAM_PARTS) else value
    for name, value in request.url.params.multi_items()
  }

  logger.debug(f"HTTP request: method={request.method} url={url} params={params}")


def enable_http_request_logging(client: httpx.AsyncClient) -> None:
  """Attach HTTP request logging to a client once while preserving existing hooks."""
  hooks = client.event_hooks.setdefault("request", [])

  if log_http_request not in hooks:
    hooks.append(log_http_request)
