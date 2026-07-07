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

from typing import Any

from pydantic import BaseModel
from pydantic import Field
from pydantic_ai import Agent
from pydantic_ai import ModelSettings
from pydantic_ai.capabilities import Thinking

from ...core.constants import Service
from ..agent import AgentClient


SYSTEM_PROMPT = (
  "You are a request router.\n\n"
  "Return only valid JSON matching this schema:\n"
  '{"service":"<service>","confidence":<0-1>}\n\n'
  "Valid services:\n"
  "- isinmi: reminders, alarms, timers, calendar, scheduling.\n"
  "- weather: weather, forecast, temperature, air quality, pollen, alerts.\n"
  "- rediyo: radio stations.\n"
  "- kansa: podcasts.\n"
  "- zigbee: smart home and Zigbee devices.\n"
  "- chat: everything else, including current time, current date, or current day.\n\n"
  "Return nothing except the JSON object."
)


class RouteDecision(BaseModel):
  service: Service
  confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class CommandAgent(AgentClient[RouteDecision]):
  command_model_settings: ModelSettings

  def _command_model_settings(self) -> ModelSettings:
    return ModelSettings(
      temperature=0,
      max_tokens=0,
      timeout=self.settings.llm_request_timeout,
      seed=0,
      thinking=False,
    )

  def _create_agent(self) -> Any:
    self.command_model_settings = self._command_model_settings()

    return Agent(
      model=self.model,
      system_prompt=SYSTEM_PROMPT,
      output_type=RouteDecision,
      model_settings=self.command_model_settings,
      capabilities=[Thinking(effort=False)],
    )

  async def classify(self, message: str) -> RouteDecision:
    if self.uses_native_ollama:
      return await self._run_ollama(
        message,
        system_prompt=SYSTEM_PROMPT,
        model_settings=getattr(self, "command_model_settings", self._command_model_settings()),
        output_type=RouteDecision,
        response_format="json",
      )

    return await self._run(message)
