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
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from typing import ClassVar
from typing import Protocol
from zoneinfo import ZoneInfo
from zoneinfo import ZoneInfoNotFoundError


@dataclass(frozen=True, slots=True)
class ToolResult:
  name: str
  data: dict[str, Any]

  def as_message_content(self) -> str:
    return json.dumps(self.data, ensure_ascii=False)


class OllamaTool(Protocol):
  name: str
  definition: dict[str, Any]

  async def execute(self, arguments: dict[str, Any], context: dict[str, Any]) -> ToolResult: ...


class DateTimeTool:
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

  async def execute(self, arguments: dict[str, Any], context: dict[str, Any]) -> ToolResult:
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


class ToolRegistry:
  def __init__(self, tools: list[OllamaTool] | None = None):
    configured_tools = tools if tools is not None else [DateTimeTool()]
    self.tools = {tool.name: tool for tool in configured_tools}

  @property
  def definitions(self) -> list[dict[str, Any]]:
    return [tool.definition for tool in self.tools.values()]

  async def execute(self, name: str, arguments: dict[str, Any], context: dict[str, Any]) -> ToolResult:
    tool = self.tools.get(name)
    if tool is None:
      return ToolResult(name=name, data={"error": f"Unknown tool: {name}"})
    return await tool.execute(arguments, context)
