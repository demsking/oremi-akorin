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
import logging
from typing import Any

from pydantic import BaseModel
from pydantic import Field
from pydantic import ValidationError
from pydantic_ai import Agent
from pydantic_ai import ModelSettings
from pydantic_ai.capabilities import Thinking

from ..agent import AgentClient


logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
  "You map multilingual smart-home requests to Zigbee2MQTT commands.\n\n"
  "You receive the user's command texts and a catalog of discovered Zigbee devices with their writable operations "
  "and readable states.\n"
  "Choose exactly one device from the catalog.\n"
  "For control requests, return a MQTT payload using only operations listed for that device.\n"
  "For status questions, return readable state properties using only states listed for that device.\n"
  "The user may use any language, and device names in the catalog may be in another language.\n"
  "Use semantic matching between the user's request, device names, operation descriptions, and state descriptions.\n\n"
  "Return only valid JSON matching this schema:\n"
  '{"intent":"write or read","device":"catalog device name or null","payload":{"property":value},'
  '"state_properties":["property"],"confidence":0.0}\n\n'
  "Rules:\n"
  "- Do not invent devices, properties, or values.\n"
  "- For write requests, set intent to write and keep state_properties empty.\n"
  "- For read/status questions, set intent to read, keep payload empty, and include the requested readable properties.\n"
  "- If a request is unclear or unsupported by every matching device, return device null, empty payload, and empty state_properties.\n"
  "- If the catalog contains exactly one device, treat it as the already matched target device.\n"
  "- For enum and binary operations, use one of the listed values exactly.\n"
  "- For numeric operations, use a number inside the listed range.\n"
  "- Do not include explanations or extra keys.\n\n"
  "Return nothing except the JSON object."
)

COMMAND_PROMPT = (
  "Select a command for the latest user request.\n"
  "If there is no concrete user request, return "
  "{{\"intent\":null,\"device\":null,\"payload\":{{}},\"state_properties\":[],\"confidence\":0.0}}.\n\n"
  "Command texts:\n{texts}\n\n"
  "Device catalog:\n{catalog}\n\n"
  "Respond with one JSON object only."
)


class ZigbeeCommandDecision(BaseModel):
  intent: str | None = Field(default=None)
  device: str | None = Field(default=None)
  payload: dict[str, Any] = Field(default_factory=dict)
  state_properties: list[str] = Field(default_factory=list)
  confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ZigbeeCommandAgent(AgentClient[ZigbeeCommandDecision]):
  command_model_settings: ModelSettings

  def _command_model_settings(self) -> ModelSettings:
    return ModelSettings(
      temperature=0,
      max_tokens=300,
      timeout=self.settings.llm_request_timeout,
      seed=0,
      thinking=False,
    )

  def _create_agent(self) -> Any:
    self.command_model_settings = self._command_model_settings()

    return Agent(
      model=self.model,
      system_prompt=SYSTEM_PROMPT,
      output_type=ZigbeeCommandDecision,
      model_settings=self.command_model_settings,
      capabilities=[Thinking(effort=False)],
    )

  async def select(self, texts: list[str], catalog: list[dict[str, Any]]) -> ZigbeeCommandDecision:
    prompt = COMMAND_PROMPT.format(
      texts=json.dumps([text for text in texts if text], ensure_ascii=False),
      catalog=json.dumps(catalog, ensure_ascii=False, sort_keys=True),
    )

    if self.uses_native_ollama:
      try:
        return await self._run_ollama(
          prompt,
          system_prompt=SYSTEM_PROMPT,
          model_settings=getattr(self, "command_model_settings", self._command_model_settings()),
          output_type=ZigbeeCommandDecision,
          response_format=ZigbeeCommandDecision.model_json_schema(),
        )
      except (json.JSONDecodeError, ValidationError, ValueError) as exception:
        logger.warning(f"Could not parse Zigbee command JSON response: {exception}")

        return ZigbeeCommandDecision()

    try:
      return await self._run(prompt)
    except (json.JSONDecodeError, ValidationError, ValueError) as exception:
      logger.warning(f"Could not parse Zigbee command JSON response: {exception}")

      return ZigbeeCommandDecision()
