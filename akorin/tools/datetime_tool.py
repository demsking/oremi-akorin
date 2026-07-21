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
import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any
from typing import ClassVar
from zoneinfo import ZoneInfo
from zoneinfo import ZoneInfoNotFoundError

from akorin.core.request import ProcessRequestContext
from akorin.core.tools import OllamaTool
from akorin.core.tools import ToolResult


logger = logging.getLogger(__name__)


class DateTimeTool(OllamaTool):
  name = "get_current_datetime"
  definition: ClassVar[dict[str, Any]] = {
    "type": "function",
    "function": {
      "name": name,
      "description": "Get the real current local date and time. Use this for every question about the current time, date, or day.",
      "parameters": {
        "type": "object",
        "properties": {
          "timezone": {
            "type": "string",
            "description": "Optional IANA timezone such as Europe/Paris when explicitly known.",
          },
        },
      },
    },
  }

  def __init__(self, clock: Callable[[], datetime] | None = None):
    self.clock = clock or (lambda: datetime.now().astimezone())

  async def execute(self, arguments: dict[str, Any], context: ProcessRequestContext) -> ToolResult:
    timezone = arguments.get("timezone") or context.get("timezone")
    now = self._now(timezone)

    return ToolResult(
      name=self.name,
      data={
        "datetime": now.isoformat(),
        "date": now.date().isoformat(),
        "time": now.strftime("%H:%M:%S"),
        "timezone": str(now.tzinfo),
      },
    )

  def _now(self, timezone: Any) -> datetime:
    now = self.clock()

    if not timezone:
      return now

    try:
      return now.astimezone(ZoneInfo(str(timezone)))
    except ZoneInfoNotFoundError:
      return now
