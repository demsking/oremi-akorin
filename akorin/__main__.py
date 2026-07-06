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
import sys

import uvicorn

from akorin.core.args import parse_arguments
from akorin.core.package import APP_NAME
from akorin.core.package import APP_VERSION
from akorin.core.settings import get_settings
from akorin.utils.logger import LOGGER_DATE_FORMAT
from akorin.utils.logger import LOGGER_FORMAT

__version__ = APP_VERSION

logger = logging.getLogger(__name__)


async def main() -> None:
  parse_arguments()

  settings = get_settings()
  config = uvicorn.Config(
    "akorin:app",
    host=settings.server_host,
    port=settings.server_port,
    server_header=False,
    use_colors=True,
    proxy_headers=True,
    log_level="info",
    log_config={
      "version": 1,
      "disable_existing_loggers": False,
      "formatters": {
        "default": {
          "()": "uvicorn.logging.DefaultFormatter",
          "fmt": LOGGER_FORMAT,
          "datefmt": LOGGER_DATE_FORMAT,
          "use_colors": True,
        },
        "access": {
          "()": "uvicorn.logging.AccessFormatter",
          "fmt": f'%(asctime)s - {APP_NAME} - HTTP - %(client_addr)s - "%(request_line)s" %(status_code)s',
          "datefmt": LOGGER_DATE_FORMAT,
          "use_colors": True,
        },
      },
      "handlers": {
        "default": {"formatter": "default", "class": "logging.StreamHandler", "stream": "ext://sys.stderr"},
        "access": {"formatter": "access", "class": "logging.StreamHandler", "stream": "ext://sys.stdout"},
      },
      "loggers": {
        "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
        "uvicorn.error": {"level": "INFO"},
        "uvicorn.access": {"handlers": ["access"], "level": "INFO", "propagate": False},
      },
    },
  )

  await uvicorn.Server(config).serve()


def start():
  try:
    asyncio.run(main())
  except KeyboardInterrupt:
    pass
  except Exception as exception:
    logger.error(f"Oremi Akọrin failed to start: {exception}")
    sys.exit(3)


if __name__ == "__main__":
  start()
