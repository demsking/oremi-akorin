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
from pydantic_ai.capabilities import Thinking

from ..agent import AgentClient


SYSTEM_PROMPT = (
  "You are a professional proofreader.\n\n"
  "Rules:\n"
  "- Correct spelling, grammar, punctuation, and typographical errors.\n"
  "- Preserve the original meaning, tone, and intent.\n"
  "- Preserve names, numbers, dates, URLs, email addresses, code, and formatting.\n"
  "- Do not rewrite unless required for grammatical correctness.\n"
  "- Do not add, remove, explain, or summarize anything.\n"
  "- Return only the corrected text."
)

SPELLCHECK_PROMPT = "Language: {language}\n\n{message}"


class SpellCheckAgent(AgentClient[str]):
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

  async def check(self, message: str, language: str) -> str:
    prompt = SPELLCHECK_PROMPT.format(message=message, language=language)

    if self.uses_native_ollama:
      output = await self._run_ollama(prompt, system_prompt=SYSTEM_PROMPT)
      return self._parse_output(output)

    return await self._run(prompt)
