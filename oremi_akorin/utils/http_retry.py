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
from collections.abc import Awaitable
from collections.abc import Callable

import httpx

from ..core.logger import logger

RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 0.1
RETRY_STATUS_CODES = {502, 503, 504}
RETRY_EXCEPTIONS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)


async def request_with_retry(
  request: Callable[[], Awaitable[httpx.Response]],
  service: str,
) -> httpx.Response:
  for attempt in range(1, RETRY_ATTEMPTS + 1):
    try:
      response = await request()
    except RETRY_EXCEPTIONS as exception:
      if attempt == RETRY_ATTEMPTS:
        raise

      delay = RETRY_BACKOFF_SECONDS * 2 ** (attempt - 1)
      logger.warning(
        f"Service request failed; retrying: service={service} attempt={attempt}/{RETRY_ATTEMPTS} "
        f"delay_seconds={delay:.1f} reason={exception}"
      )
      await asyncio.sleep(delay)
      continue

    if response.status_code not in RETRY_STATUS_CODES or attempt == RETRY_ATTEMPTS:
      return response

    delay = RETRY_BACKOFF_SECONDS * 2 ** (attempt - 1)
    logger.warning(
      f"Service returned a transient error; retrying: service={service} attempt={attempt}/{RETRY_ATTEMPTS} "
      f"status={response.status_code} delay_seconds={delay:.1f}"
    )
    await response.aclose()
    await asyncio.sleep(delay)

  raise RuntimeError("HTTP retry loop completed without a response")
