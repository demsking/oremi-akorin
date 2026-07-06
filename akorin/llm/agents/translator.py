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

from ..agent import AgentClient


SYSTEM_PROMPT = (
  "You are a professional translator.\n\n"
  "Rules:\n"
  "- Translate accurately and naturally.\n"
  "- Preserve the original meaning, tone, and intent.\n"
  "- Preserve names, numbers, dates, URLs, email addresses, code, and formatting.\n"
  "- Do not add, remove, explain, or summarize anything.\n"
  "- Return only the translated text."
)

TRANSLATION_PROMPT = "Source language: {source_language}\nTarget language: {target_language}\n\n{message}"


class TranslatorAgent(AgentClient[str]):
  def _create_agent(self) -> Agent:
    return Agent(
      model=self.model,
      system_prompt=SYSTEM_PROMPT,
      output_type=str,
      model_settings=self.model_settings,
    )

  def _parse_output(self, output: str) -> str:
    return output.strip()

  async def translate(self, message: str, source_language: str, target_language: str) -> str:
    return await self._run(
      TRANSLATION_PROMPT.format(
        message=message,
        source_language=source_language,
        target_language=target_language,
      )
    )
