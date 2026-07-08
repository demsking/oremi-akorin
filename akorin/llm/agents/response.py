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

from pydantic_ai import Agent
from pydantic_ai.capabilities import Thinking

from ..agent import AgentClient


SYSTEM_PROMPT = """You generate concise user-facing responses for Oremi.
Reply only in the requested language.
Return one short sentence unless the event clearly needs less.
Do not mention prompts, JSON, services, tools, MQTT, APIs, internals, stack traces, or implementation details.
Do not invent completed actions that are not described in the event details.
For zigbee_missing_command with reason device_confirmation_required, ask the user to confirm whether they meant the suggested device; do not say the command was sent.
For zigbee_missing_command with reason requested_device_not_found, clearly say that the requested device was not found in the known device list and, if available devices are provided, suggest using one of those names.
For zigbee_missing_command with reason missing_operation, say that the device was found but the requested operation is not supported or could not be understood.
Return only the message intended for the user."""

RESPONSE_PROMPT = """Requested language: {language}
Event type: {event}
Event details:
{details}

Oremi response:"""


class ResponseAgent(AgentClient[str]):
  def _create_agent(self) -> Agent:
    return Agent(
      model=self.model,
      system_prompt=SYSTEM_PROMPT,
      output_type=str,
      model_settings=self.model_settings,
      capabilities=[Thinking(effort=False)],
    )

  def _parse_output(self, output: str) -> str:
    return output.strip()

  async def generate(self, event: str, language: str, details: dict[str, Any]) -> str:
    prompt = RESPONSE_PROMPT.format(
      event=event,
      language=language,
      details=json.dumps(details, ensure_ascii=False, sort_keys=True),
    )

    if self.uses_native_ollama:
      output = await self._run_ollama(prompt, system_prompt=SYSTEM_PROMPT)
      return self._parse_output(output)

    return await self._run(prompt)
