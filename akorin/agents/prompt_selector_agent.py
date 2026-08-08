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

import logging

from mcp_types import Prompt
from pydantic import BaseModel
from pydantic import Field
from pydantic_ai import ModelSettings

from akorin.core.agent import AgentClient


logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
  "You are a prompt selector and argument extractor.\n\n"
  "Your task is to match a user request to one of the available prompt templates from an MCP service, "
  "and extract the values for the template arguments from the user's request.\n\n"
  "Available prompts:\n"
  "{prompts_description}\n\n"
  "Determine if one of the available prompts matches the user request. If a prompt matches:\n"
  "1. Set 'name' to the matching prompt's name.\n"
  "2. Extract the values for the prompt's arguments from the user's request. All argument values must be strings.\n\n"
  "If no available prompts match the user's request, set 'name' to null (or None) and return an empty arguments dictionary.\n"
  "Return only valid JSON matching this schema:\n"
  '{{"name": "<prompt_name_or_null>", "arguments": {{"<param_name>": "<param_value>"}}}}'
)


class SelectedPrompt(BaseModel):
  name: str | None = Field(default=None)
  arguments: dict[str, str] = Field(default_factory=dict)


class PromptSelectorAgent(AgentClient[SelectedPrompt]):
  RESULT_TYPE = SelectedPrompt
  RESPONSE_FORMAT = "json"

  def _get_model_settings(self) -> ModelSettings:
    return ModelSettings(
      temperature=0.0,
      max_tokens=200,
      timeout=self.settings.llm_request_timeout,
      seed=0,
      thinking=False,
    )

  async def select_prompt(self, message: str, prompts: list[Prompt]) -> SelectedPrompt:
    if not prompts:
      return SelectedPrompt(name=None, arguments={})

    prompts_desc = []

    for prompt in prompts:
      args = []

      if prompt.arguments:
        for arg in prompt.arguments:
          req = "required" if arg.required else "optional"
          args.append(f"- {arg.name} ({req}): {arg.description or ''}")

      args_str = "\n  ".join(args) if args else "None"

      prompts_desc.append(
        f"Prompt: {prompt.name}\nDescription: {getattr(prompt, 'description', '') or ''}\nArguments:\n  {args_str}"
      )

    system_prompt = SYSTEM_PROMPT.format(prompts_description="\n\n".join(prompts_desc))

    # Submits the dynamic prompt to the unified execution route
    return await self._run(message, system_prompt=system_prompt)
