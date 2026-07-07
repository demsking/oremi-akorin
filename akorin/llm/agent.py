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
import ollama
from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai import ModelSettings

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
    self.uses_native_ollama = settings.uses_ollama()
    self.ollama_model_name = settings.resolve_ollama_model_name() if self.uses_native_ollama else ""

    self.ollama_client = (
      ollama.AsyncClient(host=settings.ollama_base_url_string, timeout=settings.llm_request_timeout)
      if self.uses_native_ollama
      else None
    )

    self.model_settings = ModelSettings(
      temperature=settings.llm_temperature,
      max_tokens=settings.max_response_tokens,
      timeout=settings.llm_request_timeout,
      thinking=False,
    )

    self.model = None if self.uses_native_ollama else AgentClient.build_model(settings, self.model_settings, client)
    self.agent = None if self.uses_native_ollama else self._create_agent()

  @staticmethod
  def build_model(settings: Settings, model_settings: ModelSettings, client: httpx.AsyncClient) -> str:
    del model_settings, client
    return settings.llm_model

  @abstractmethod
  def _create_agent(self) -> Agent:
    raise NotImplementedError

  def _parse_output(self, output: OutputModel) -> OutputModel:
    return output

  def _ollama_options(self, model_settings: ModelSettings | None = None) -> dict[str, Any]:
    settings = model_settings or self.model_settings
    options: dict[str, Any] = {}

    if (temperature := settings.get("temperature")) is not None:
      options["temperature"] = temperature
    if (seed := settings.get("seed")) is not None:
      options["seed"] = seed
    if (max_tokens := settings.get("max_tokens")) is not None and max_tokens > 0:
      options["num_predict"] = max_tokens

    return options

  async def _run_ollama(
    self,
    prompt: str,
    *,
    system_prompt: str | None,
    model_settings: ModelSettings | None = None,
    output_type: type[Any] = str,
    response_format: str | None = None,
  ) -> Any:
    if self.ollama_client is None:
      raise RuntimeError("Native Ollama client is not configured")

    messages: list[dict[str, str]] = []

    if system_prompt:
      messages.append({"role": "system", "content": system_prompt})

    messages.append({"role": "user", "content": prompt})

    response = await self.ollama_client.chat(
      model=self.ollama_model_name,
      messages=messages,
      stream=False,
      think=False,
      format=response_format,  # pyright: ignore
      options=self._ollama_options(model_settings),
    )
    content = response.message.content or ""

    if isinstance(output_type, type) and issubclass(output_type, BaseModel):
      return output_type.model_validate_json(content)

    return content

  async def _run(self, prompt: str) -> OutputModel:
    if self.uses_native_ollama:
      output = await self._run_ollama(prompt, system_prompt=None)
      return self._parse_output(output)

    if self.agent is None:
      raise RuntimeError("Pydantic AI agent is not configured")

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
