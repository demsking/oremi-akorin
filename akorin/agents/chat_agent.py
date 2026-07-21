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

from akorin.core.agent import AgentClient
from akorin.core.request import ProcessRequestContext
from akorin.utils.request_context import request_context

CHAT_PROMPT = (
  "Give only the answer intended for the user. Never include notes, reasoning, commentary about the prompt, "
  "or commentary about whether the context is relevant. Do not use parenthetical asides. "
  "Use the supplied context silently when it is relevant and ignore it silently otherwise. "
  "Reply only in {language}.\n"
  "Context: {context}\n"
  "User: {message}\n"
  "Oremi:"
)


class ChatAgent(AgentClient[str]):
  RESULT_TYPE = str

  async def chat(self, message: str, language: str, context: ProcessRequestContext) -> str:
    prompt = CHAT_PROMPT.format(message=message, language=language, context=request_context(context) or "{}")
    return await self._run(prompt)
