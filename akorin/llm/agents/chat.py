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

from pydantic_ai import Agent
from pydantic_ai.capabilities import Thinking

from ...utils.request_context import request_context
from ..agent import AgentClient


CHAT_PROMPT = """You are Oremi, a concise and helpful personal assistant. Reply only in {language}.
Give only the answer intended for the user. Never include notes, reasoning, commentary about the prompt, or commentary about whether the context is relevant. Do not use parenthetical asides.
Use the supplied context silently when it is relevant and ignore it silently otherwise.
Context: {context}
User: {message}
Oremi:"""


class ChatAgent(AgentClient[str]):
  def _create_agent(self) -> Agent:
    return Agent(
      model=self.model,
      system_prompt=self.settings.llm_system_prompt,
      output_type=str,
      model_settings=self.model_settings,
      capabilities=[Thinking(effort=False)],
    )

  def _parse_output(self, output: str) -> str:
    return output.strip()

  async def chat(self, message: str, language: str, context: dict[str, Any]) -> str:
    prompt = CHAT_PROMPT.format(message=message, language=language, context=request_context(context) or "{}")

    if self.uses_native_ollama:
      output = await self._run_ollama(prompt, system_prompt=self.settings.llm_system_prompt)
      return self._parse_output(output)

    return await self._run(prompt)
