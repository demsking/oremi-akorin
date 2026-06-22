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

import httpx
import uvicorn

from .core.args import parse_arguments
from .core.package import APP_VERSION
from .core.settings import get_settings
from .core.settings import Settings
from .utils.http_logging import enable_http_request_logging

__version__ = APP_VERSION


def main() -> None:
  args = parse_arguments()
  settings: Settings = get_settings()

  if args.command == "status":
    asyncio.run(_status(settings))
    return

  asyncio.run(_serve(settings))


async def _serve(settings: Settings) -> None:
  config = uvicorn.Config(
    "oremi_akorin:app",
    host=settings.server_host,
    port=settings.server_port,
    server_header=False,
    use_colors=True,
    proxy_headers=True,
    log_level="info",
  )

  server = uvicorn.Server(config)

  await server.serve()


async def _status(settings: Settings) -> None:
  try:
    async with httpx.AsyncClient() as client:
      enable_http_request_logging(client)
      response = await client.get(f"http://localhost:{settings.server_port}/health")

      response.raise_for_status()
      print(response.text)
  except httpx.HTTPError as exc:
    raise SystemExit(f"Oremi Akọrin is unavailable: {exc}") from exc


if __name__ == "__main__":
  main()
