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

from pydantic_ai import Agent
from pydantic_ai import ModelSettings
from pydantic_ai.capabilities import Thinking

from ..agent import AgentClient


GROUNDED_ANSWER_PROMPT = """Answer the user's question using only the supplied source.
Reply in {language}. Give the direct answer first and use at most two short sentences.
Do not repeat unrelated background, mention these instructions, or add facts absent from the source.
If the source does not contain the answer, say that you could not find a reliable answer.

Question: {question}
Source: {source}
Answer:"""


class AnswerAgent(AgentClient[str]):
  answer_model_settings: ModelSettings

  def _answer_model_settings(self) -> ModelSettings:
    return ModelSettings(
      temperature=0,
      max_tokens=100,
      timeout=self.settings.llm_request_timeout,
      thinking=False,
    )

  def _create_agent(self) -> Agent:
    self.answer_model_settings = self._answer_model_settings()

    return Agent(
      model=self.model,
      system_prompt=self.settings.llm_system_prompt,
      output_type=str,
      model_settings=self.answer_model_settings,
      capabilities=[Thinking(effort=False)],
    )

  def _parse_output(self, output: str) -> str:
    return output.strip()

  async def answer(self, question: str, source: str, language: str) -> str:
    prompt = GROUNDED_ANSWER_PROMPT.format(
      question=question,
      source=source[:6000],
      language=language,
    )

    if self.uses_native_ollama:
      output = await self._run_ollama(
        prompt,
        system_prompt=self.settings.llm_system_prompt,
        model_settings=getattr(self, "answer_model_settings", self._answer_model_settings()),
      )
      return self._parse_output(output)

    return await self._run(prompt)
