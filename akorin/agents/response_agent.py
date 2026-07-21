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
from __future__ import annotations

import json
from typing import Any

from akorin.core.agent import AgentClient

SYSTEM_PROMPT = """You generate concise user-facing responses for Oremi.
Reply only in the requested language.
Return one short sentence unless the event clearly needs less.
Do not mention prompts, JSON, services, tools, APIs, internals, stack traces, or implementation details.
Do not invent completed actions that are not described in the event details.
Return only the message intended for the user."""

RESPONSE_PROMPT = """Requested language: {language}
Event type: {event}
Event details:
{details}

Oremi response:"""


class ResponseAgent(AgentClient[str]):
  SYSTEM_PROMPT = SYSTEM_PROMPT
  RESULT_TYPE = str

  async def generate(self, event: str, language: str, details: dict[str, Any]) -> str:
    prompt = RESPONSE_PROMPT.format(
      event=event,
      language=language,
      details=json.dumps(details, ensure_ascii=False, sort_keys=True),
    )
    return await self._run(prompt)
