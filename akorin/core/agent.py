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
import logging
from abc import ABC
from collections.abc import Awaitable
from collections.abc import Callable
from dataclasses import dataclass
from inspect import Parameter
from inspect import Signature
from typing import Annotated
from typing import Any
from typing import cast
from typing import ClassVar
from typing import Generic
from typing import TYPE_CHECKING
from typing import TypeVar

import httpx2
import ollama
from pydantic import BaseModel
from pydantic import Field
from pydantic_ai import Agent
from pydantic_ai import ModelSettings
from pydantic_ai.capabilities import Thinking

from akorin.core.request import ProcessRequestContext
from akorin.core.settings import Settings
from akorin.utils.cache import SmartCache

if TYPE_CHECKING:
  from akorin.core.tools import ToolRegistry, ToolResult

OutputModel = TypeVar("OutputModel", bound=Any)
T = TypeVar("T")

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ChatResult:
  message: str
  tools: list["ToolResult"]


class AgentClient(Generic[OutputModel], ABC):
  """
  Advanced, strongly-typed LLM Agent base class.
  Automatically handles execution routing, caching, tool orchestration, and response parsing.
  """

  SYSTEM_PROMPT: ClassVar[str | None] = None
  RESULT_TYPE: ClassVar[type[Any]] = str
  RESPONSE_FORMAT: ClassVar[Any] = None

  SCHEMA_ANNOTATION_MAPPING: ClassVar[dict[str, type[Any]]] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list[Any],
    "object": dict[str, Any],
  }

  def __init__(
    self,
    settings: Settings,
    client: httpx2.AsyncClient,
    cache: SmartCache | None = None,
  ) -> None:
    self.settings = settings
    self.cache = cache
    self.model_settings = self._get_model_settings()

    self.ollama_client: ollama.AsyncClient | None = None
    self.model: str | None = None
    self.agent: Agent[Any, OutputModel] | None = None

    self._initialize_clients(client)

  def _initialize_clients(self, client: httpx2.AsyncClient) -> None:
    """Securely initialize appropriate backing clients based on configuration."""
    if self.settings.should_use_ollama:
      self.ollama_client = ollama.AsyncClient(
        host=self.settings.ollama_base_url_string,
        timeout=self.settings.llm_request_timeout,
      )
    else:
      self.model = self.build_model(self.settings, self.model_settings, client)
      self.agent = self._create_agent()

  @staticmethod
  def build_model(settings: Settings, model_settings: ModelSettings, client: httpx2.AsyncClient) -> str:
    del model_settings, client
    return settings.llm_model

  def _get_model_settings(self) -> ModelSettings:
    return ModelSettings(
      temperature=self.settings.llm_temperature,
      max_tokens=self.settings.llm_max_response_tokens,
      timeout=self.settings.llm_request_timeout,
      thinking=False,
    )

  def _create_agent(self, system_prompt: str | None = None) -> Agent[Any, OutputModel]:
    """Creates a properly typed Pydantic AI Agent."""
    return Agent(
      model=cast(str, self.model),
      system_prompt=system_prompt or self._get_system_prompt(),
      output_type=self.RESULT_TYPE,
      model_settings=self.model_settings,
      capabilities=[Thinking(effort=False)],
    )

  def _parse_output(self, output: OutputModel) -> OutputModel:
    """Centralized parsing logic to trim strings globally."""
    if isinstance(output, str):
      return cast(OutputModel, output.strip())

    return output

  def _get_system_prompt(self) -> str:
    return self.SYSTEM_PROMPT or self.settings.llm_system_prompt

  def _cache_key(
    self,
    prompt: str,
    *,
    system_prompt: str,
    output_type: type[Any] | None = None,
  ) -> str | None:
    if not self.cache:
      return None

    type_name = getattr(output_type, "__name__", str(output_type)) if output_type else None

    return self.cache.make_key(
      "llm",
      {
        "agent": type(self).__name__,
        "model": self.settings.llm_model,
        "temperature": self.model_settings.get("temperature"),
        "max_tokens": self.model_settings.get("max_tokens"),
        "seed": self.model_settings.get("seed"),
        "system_prompt": system_prompt,
        "output_type": type_name,
        "prompt": prompt,
      },
    )

  async def _execute_with_cache(
    self, cache_key: str | None, executor: Callable[[], Awaitable[T]], ttl_seconds: float | None = None
  ) -> T:
    if self.cache and cache_key:
      ttl = ttl_seconds if ttl_seconds is not None else self.settings.llm_cache_ttl_seconds
      return await self.cache.get_or_set(cache_key, ttl, executor)
    return await executor()

  def _ollama_options(self) -> dict[str, Any]:
    options: dict[str, Any] = {}
    if (temp := self.model_settings.get("temperature")) is not None:
      options["temperature"] = temp
    if (seed := self.model_settings.get("seed")) is not None:
      options["seed"] = seed
    if (tokens := self.model_settings.get("max_tokens")) and tokens > 0:
      options["num_predict"] = tokens
    return options

  async def _run_ollama(self, prompt: str, system_prompt: str, ttl_seconds: float | None = None) -> Any:
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}]
    options = self._ollama_options()
    cache_key = self._cache_key(prompt, system_prompt=system_prompt, output_type=self.RESULT_TYPE)

    async def executor() -> Any:
      if not self.ollama_client:
        raise RuntimeError("Native Ollama client is not configured")

      response = await self.ollama_client.chat(  # pyright: ignore
        model=self.settings.ollama_model_name,
        messages=messages,
        stream=False,
        think=False,
        format=self.RESPONSE_FORMAT,  # pyright: ignore
        options=options,
      )

      content = getattr(response.message, "content", "") or ""

      if isinstance(self.RESULT_TYPE, type) and issubclass(self.RESULT_TYPE, BaseModel):
        return self.RESULT_TYPE.model_validate_json(content)

      return content

    return await self._execute_with_cache(cache_key, executor, ttl_seconds=ttl_seconds)

  async def _run_agent(self, prompt: str, system_prompt: str, ttl_seconds: float | None = None) -> OutputModel:
    agent = self._create_agent(system_prompt=system_prompt)
    cache_key = self._cache_key(prompt, system_prompt=system_prompt, output_type=self.RESULT_TYPE)

    async def executor() -> OutputModel:
      result = await agent.run(prompt)
      return self._parse_output(result.output)

    return await self._execute_with_cache(cache_key, executor, ttl_seconds=ttl_seconds)

  async def _run(self, prompt: str, *, system_prompt: str | None = None, ttl_seconds: float | None = None) -> OutputModel:
    """Unified, secure entrypoint for all non-tool LLM executions."""
    sys_prompt = system_prompt or self._get_system_prompt()

    if self.settings.should_use_ollama:
      output = await self._run_ollama(prompt, system_prompt=sys_prompt, ttl_seconds=ttl_seconds)

      return self._parse_output(cast(OutputModel, output))

    return await self._run_agent(prompt, system_prompt=sys_prompt, ttl_seconds=ttl_seconds)

  async def _run_with_tools(
    self,
    prompt: str,
    tools: ToolRegistry,
    context: ProcessRequestContext,
    system_prompt: str | None = None,
  ) -> ChatResult:
    """Handles intelligent execution of Agents requiring functional tool integrations."""
    sys_prompt = system_prompt or self._get_system_prompt()
    executed_tools: list[ToolResult] = []

    if self.settings.should_use_ollama:
      if not self.ollama_client:
        raise RuntimeError("Native Ollama client is not configured")

      messages: list[dict[str, Any]] = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": prompt},
      ]

      for _ in range(5):
        response = await self.ollama_client.chat(
          model=self.settings.ollama_model_name,
          messages=messages,
          tools=tools.definitions,
          stream=False,
          think=False,
          options=self._ollama_options(),
        )
        tool_calls = response.message.tool_calls or []

        if not tool_calls:
          return ChatResult(message=(response.message.content or "").strip(), tools=executed_tools)

        messages.append(response.message.model_dump(exclude_none=True))

        for tool_call in tool_calls:
          result = await tools.execute(tool_call.function.name, dict(tool_call.function.arguments), context)

          executed_tools.append(result)
          messages.append({"role": "tool", "tool_name": result.name, "content": result.as_message_content()})

      return ChatResult(message=(response.message.content or "").strip(), tools=executed_tools)  # pyright: ignore

    # Pydantic AI Execution
    agent_tools = [self._build_tool_function(name, tools, context, executed_tools) for name in tools.tools]
    agent = Agent(
      model=cast(str, self.model),
      system_prompt=sys_prompt,
      output_type=str,
      model_settings=self.model_settings,
      tools=agent_tools,
      capabilities=[Thinking(effort=False)],
    )

    run_result = await agent.run(prompt)  # pyright: ignore
    return ChatResult(message=str(run_result.output).strip(), tools=executed_tools)

  @classmethod
  def _build_tool_function(
    cls,
    name: str,
    registry: ToolRegistry,
    context: ProcessRequestContext,
    executed_tools: list[ToolResult],
  ) -> Callable[..., Awaitable[str]]:
    async def run_tool(**arguments: Any) -> str:
      result = await registry.execute(name, arguments, context)
      executed_tools.append(result)
      return json.dumps(result.data, ensure_ascii=False)

    func_def = cast(dict[str, Any], registry.tools[name].definition.get("function", {}))
    params = cast(dict[str, Any], func_def.get("parameters", {}))
    props = cast(dict[str, Any], params.get("properties", {}))
    req = set(cast(list[str], params.get("required", [])))

    run_tool.__name__ = name
    run_tool.__qualname__ = name
    run_tool.__doc__ = func_def.get("description") or f"Execute {name}."

    annotations: dict[str, Any] = {"return": str}
    sig_params = []

    for p_name, schema in props.items():
      ann = cls._schema_annotation(schema)

      if desc := schema.get("description"):
        ann = Annotated[ann, Field(description=desc)]

      annotations[p_name] = ann
      sig_params.append(
        Parameter(
          p_name,
          Parameter.KEYWORD_ONLY,
          default=Parameter.empty if p_name in req else None,
          annotation=ann,
        )
      )

    run_tool.__annotations__ = annotations
    setattr(run_tool, "__signature__", Signature(parameters=sig_params, return_annotation=str))

    return run_tool

  @staticmethod
  def _schema_annotation(schema: dict[str, Any]) -> Any:
    return AgentClient.SCHEMA_ANNOTATION_MAPPING.get(str(schema.get("type")), Any)
