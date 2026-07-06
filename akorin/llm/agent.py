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
from abc import ABC
from abc import abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from typing import Generic
from typing import TYPE_CHECKING
from typing import TypeVar

import httpx
from pydantic_ai import Agent
from pydantic_ai import AgentModelSettings
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.ollama import OllamaProvider

from ..core.settings import Settings

if TYPE_CHECKING:
  from ..services.tools import ToolRegistry
  from ..services.tools import ToolResult

OutputModel = TypeVar("OutputModel")


@dataclass(frozen=True, slots=True)
class ChatResult:
  message: str
  tools: list[ToolResult]


class AgentClient(Generic[OutputModel], ABC):
  def __init__(self, settings: Settings, client: httpx.AsyncClient):
    self.settings = settings
    self.model = self._build_model(settings, client)
    self.model_settings = self._build_model_settings(settings)

    self.agent = self._create_agent()

  @staticmethod
  def _build_model(settings: Settings, client: httpx.AsyncClient) -> str | OpenAIChatModel:
    if settings.uses_ollama():
      from pydantic_ai.models.ollama import OllamaModel  # pylint: disable=import-outside-toplevel

      return OllamaModel(
        model_name=settings.resolve_ollama_model_name(),
        provider=OllamaProvider(base_url=f"{settings.ollama_base_url_string}/v1", http_client=client),
      )

    return settings.llm_model

  @staticmethod
  def _build_model_settings(settings: Settings) -> AgentModelSettings:
    model_settings: AgentModelSettings = {
      "temperature": settings.llm_temperature,
      "max_tokens": settings.max_response_tokens,
      "timeout": settings.llm_request_timeout,
      "thinking": False,
    }

    if settings.uses_ollama():
      model_settings["extra_body"] = {"think": False}

    return model_settings

  @abstractmethod
  def _create_agent(self) -> Agent:
    raise NotImplementedError

  def _parse_output(self, output: OutputModel) -> OutputModel:
    return output

  async def _run(self, prompt: str) -> OutputModel:
    result: Any = await self.agent.run(prompt)

    return self._parse_output(result.output)

  @staticmethod
  def _build_tool_function(
    name: str,
    context: dict[str, Any],
    registry: ToolRegistry,
    executed_tools: list[ToolResult],
  ) -> Callable[..., Any]:
    async def run_tool(**arguments: Any) -> str:
      result = await registry.execute(name, arguments, context)

      executed_tools.append(result)

      return json.dumps(result.data, ensure_ascii=False)

    tool = registry.tools[name]
    run_tool.__name__ = name
    run_tool.__qualname__ = name
    run_tool.__doc__ = tool.definition.get("function", {}).get("description") or f"Execute {name}."

    return run_tool
