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
import logging

from akorin.agents.prompt_selector_agent import PromptSelectorAgent
from akorin.core.router import RequestRouter
from akorin.core.router import RouteContext
from akorin.core.router import RoutePromptDecision

logger = logging.getLogger(__name__)


class McpPromptRouter(RequestRouter):
  def __init__(self, agent: PromptSelectorAgent):
    self.agent = agent

  async def route(self, context: RouteContext) -> RoutePromptDecision | None:
    logger.debug(f"[{context.request_id}] Evaluating McpPromptRouter with {len(context.all_prompts)} available prompts")

    if not context.all_prompts:
      return None

    try:
      selected_prompt = await self.agent.select_prompt(context.request.message, context.all_prompts)

      if selected_prompt and selected_prompt.name:
        service = context.prompt_to_service.get(selected_prompt.name)

        if service:
          logger.info(
            f"[{context.request_id}] McpPromptRouter: Prompt selected: name={selected_prompt.name!r} service={service.value}"
          )

          return RoutePromptDecision(service=service, confidence=1.0, selected_prompt=selected_prompt)

      logger.debug(f"[{context.request_id}] McpPromptRouter: No matching prompt found")
    except Exception as exception:
      logger.warning(f"[{context.request_id}] McpPromptRouter: Prompt selection failed: {exception}")

    return None
