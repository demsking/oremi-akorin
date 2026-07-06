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
from dataclasses import dataclass
from inspect import Parameter
from inspect import Signature
from typing import Any

from pydantic_ai import Agent

from ...services.tools import ToolRegistry
from ...services.tools import ToolResult
from ...utils.request_context import request_context
from ..agent import AgentClient
from .chat import CHAT_PROMPT


@dataclass(frozen=True, slots=True)
class ChatResult:
  message: str
  tools: list[ToolResult]


class ChatToolsAgent(AgentClient[str]):
  def _create_agent(self) -> Agent:
    return Agent(model=self.model)

  async def chat(
    self,
    message: str,
    language: str,
    context: dict[str, Any],
    tools: ToolRegistry,
  ) -> ChatResult:
    executed_tools: list[ToolResult] = []
    agent_tools = [self._build_tool_function(name, context, tools, executed_tools) for name in tools.tools]

    agent = Agent(
      model=self.model,
      system_prompt=self.settings.llm_system_prompt,
      output_type=str,
      model_settings=self.model_settings,
      tools=agent_tools,
    )

    prompt = CHAT_PROMPT.format(message=message, language=language, context=request_context(context) or "{}")
    result = await agent.run(prompt)

    return ChatResult(message=str(result.output).strip(), tools=executed_tools)

  @staticmethod
  def _build_tool_function(
    name: str,
    context: dict[str, Any],
    registry: ToolRegistry,
    executed_tools: list[ToolResult],
  ):
    async def run_tool(**arguments: Any) -> str:
      result = await registry.execute(name, arguments, context)
      executed_tools.append(result)
      return json.dumps(result.data, ensure_ascii=False)

    function_definition = registry.tools[name].definition.get("function", {})
    parameters = function_definition.get("parameters", {})
    properties = parameters.get("properties", {})
    required = set(parameters.get("required", []))
    annotations: dict[str, Any] = {}
    signature_parameters = []

    run_tool.__name__ = name
    run_tool.__qualname__ = name
    run_tool.__doc__ = function_definition.get("description") or f"Execute {name}."

    for parameter_name, schema in properties.items():
      annotation = ChatToolsAgent._schema_annotation(schema)
      annotations[parameter_name] = annotation
      signature_parameters.append(
        Parameter(
          parameter_name,
          Parameter.KEYWORD_ONLY,
          default=Parameter.empty if parameter_name in required else None,
          annotation=annotation,
        )
      )

    annotations["return"] = str
    run_tool.__annotations__ = annotations
    signature = Signature(parameters=signature_parameters, return_annotation=str)

    setattr(run_tool, "__signature__", signature)

    return run_tool

  @staticmethod
  def _schema_annotation(schema: dict[str, Any]) -> Any:
    schema_type = schema.get("type")

    if schema_type == "string":
      return str

    if schema_type == "integer":
      return int

    if schema_type == "number":
      return float

    if schema_type == "boolean":
      return bool

    if schema_type == "array":
      return list[Any]

    if schema_type == "object":
      return dict[str, Any]

    return Any
