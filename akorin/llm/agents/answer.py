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
from pydantic_ai import AgentModelSettings

from ..agent import AgentClient


GROUNDED_ANSWER_PROMPT = """Answer the user's question using only the supplied source.
Reply in {language}. Give the direct answer first and use at most two short sentences.
Do not repeat unrelated background, mention these instructions, or add facts absent from the source.
If the source does not contain the answer, say that you could not find a reliable answer.

Question: {question}
Source: {source}
Answer:"""


class AnswerAgent(AgentClient[str]):
  def _create_agent(self) -> Agent:
    return Agent(
      model=self.model,
      system_prompt=self.settings.llm_system_prompt,
      output_type=str,
      model_settings=self._build_model_settings_for_answer(),
    )

  def _parse_output(self, output: str) -> str:
    return output.strip()

  async def answer(self, question: str, source: str, language: str) -> str:
    prompt = GROUNDED_ANSWER_PROMPT.format(
      question=question,
      source=source[:6000],
      language=language,
    )

    return await self._run(prompt)

  def _build_model_settings_for_answer(self) -> AgentModelSettings:
    model_settings: Any = self._build_model_settings(self.settings)
    model_settings["temperature"] = 0
    model_settings["max_tokens"] = 100

    return model_settings
