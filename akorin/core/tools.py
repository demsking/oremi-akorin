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
import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any
from typing import Callable
from typing import ClassVar
from typing import Protocol
from typing import TYPE_CHECKING

from akorin.core.request import ProcessRequestContext
from akorin.core.service import Service

if TYPE_CHECKING:
  from akorin.core.orchestrator import ServiceHandlers


logger = logging.getLogger(__name__)


class MCPTool:
  def __init__(
    self,
    name: str,
    description: str,
    input_schema: dict[str, Any],
    call_fn: Callable[[str, dict[str, Any]], Any],
    service: Service,
  ):
    self.name = name
    self.definition: dict[str, Any] = {
      "type": "function",
      "function": {
        "name": name,
        "description": description or "",
        "parameters": input_schema,
      },
    }
    self.call_fn = call_fn
    self.service = service

  async def execute(self, arguments: dict[str, Any], context: Any = None) -> "ToolResult":
    schema = self.definition["function"]["parameters"]
    properties = schema.get("properties", {})
    clean_args = {k: v for k, v in arguments.items() if k in properties}

    result = await self.call_fn(self.name, clean_args)

    parsed_items = []
    text_contents = []

    for content_item in result.content:
      text = content_item.text
      text_contents.append(text)

      try:
        parsed_items.append(json.loads(text))
      except Exception:
        pass

    if parsed_items and len(parsed_items) == len(text_contents):
      if len(parsed_items) == 1:
        item = parsed_items[0]

        if isinstance(item, dict):
          data = item
        else:
          data = {"result": item}
      else:
        data = {"result": parsed_items}
    else:
      full_text = "\n".join(text_contents)

      try:
        data = json.loads(full_text)
      except Exception:
        data = {"result": full_text}

    return ToolResult(name=self.name, data=data, service=self.service)


@dataclass(frozen=True, slots=True)
class ToolResult:
  name: str
  data: dict[str, Any]
  service: Service | None = None

  def as_message_content(self) -> str:
    return json.dumps(self.data, ensure_ascii=False)


class OllamaTool(Protocol):
  name: str
  definition: ClassVar[dict[str, Any]]

  async def execute(self, arguments: dict[str, Any], context: ProcessRequestContext) -> ToolResult: ...


class ListResourcesTool:
  name = "list_resources"
  definition: ClassVar[dict[str, Any]] = {
    "type": "function",
    "function": {
      "name": name,
      "description": (
        "List all available resources from connected services. "
        "Resources provide read-only data such as device lists, status, or configurations."
      ),
      "parameters": {
        "type": "object",
        "properties": {},
      },
    },
  }

  def __init__(self, handlers: "ServiceHandlers"):
    self.handlers = handlers

  async def execute(self, arguments: dict[str, Any], context: ProcessRequestContext) -> ToolResult:
    results = []

    for service, handler in self.handlers.items():
      try:
        resources = await handler.get_resources()

        for resource in resources:
          results.append(
            {
              "service": service.value,
              "uri": str(resource.uri),
              "name": resource.name,
              "description": getattr(resource, "description", None) or "",
              "mime_type": getattr(resource, "mimeType", None) or "",
            }
          )
      except asyncio.exceptions.CancelledError:
        logger.warning(f"Skipping list resources for {service.value}: component is not ready")
      except Exception as exception:
        logger.warning(f"Failed to list resources from {service}: {exception}")

    return ToolResult(name=self.name, data={"resources": results})


class ReadResourceTool:
  name = "read_resource"
  definition: ClassVar[dict[str, Any]] = {
    "type": "function",
    "function": {
      "name": name,
      "description": "Read the content of a specific resource using its URI.",
      "parameters": {
        "type": "object",
        "properties": {
          "uri": {
            "type": "string",
            "description": "The URI of the resource to read, e.g., device://list.",
          },
        },
        "required": ["uri"],
      },
    },
  }

  def __init__(self, handlers: "ServiceHandlers"):
    self.handlers = handlers

  async def execute(self, arguments: dict[str, Any], context: ProcessRequestContext) -> ToolResult:
    uri = arguments.get("uri")
    if not uri:
      return ToolResult(name=self.name, data={"error": "URI is required"})

    for service, handler in self.handlers.items():
      try:
        resources = await handler.get_resources()

        if any(str(r.uri) == uri for r in resources):
          result = await handler.read_resource(uri)
          contents = []

          for content in result.contents:
            if hasattr(content, "text") and content.text:
              try:
                contents.append(json.loads(content.text))
              except Exception:
                contents.append(content.text)
            elif hasattr(content, "blob") and content.blob:
              contents.append(content.blob)

          return ToolResult(
            name=self.name,
            data={"uri": uri, "contents": contents},
            service=service,
          )
      except Exception as exc:
        logger.warning(f"Failed to read resource {uri} from {service}: {exc}")

    for service, handler in self.handlers.items():
      if hasattr(handler, "read_resource"):
        try:
          result = await handler.read_resource(uri)
          contents = []

          if hasattr(result, "contents"):
            for content in result.contents:
              if hasattr(content, "text") and content.text:
                try:
                  contents.append(json.loads(content.text))
                except Exception:
                  contents.append(content.text)
              elif hasattr(content, "blob") and content.blob:
                contents.append(content.blob)
          return ToolResult(
            name=self.name,
            data={"uri": uri, "contents": contents},
            service=service,
          )
        except Exception:
          pass

    return ToolResult(name=self.name, data={"error": f"Resource not found or failed to read: {uri}"})


class ListPromptsTool:
  name = "list_prompts"
  definition: ClassVar[dict[str, Any]] = {
    "type": "function",
    "function": {
      "name": name,
      "description": "List all available prompt templates from connected services. Prompts are predefined template messages for specific tasks.",
      "parameters": {
        "type": "object",
        "properties": {},
      },
    },
  }

  def __init__(self, handlers: "ServiceHandlers"):
    self.handlers = handlers

  async def execute(self, arguments: dict[str, Any], context: ProcessRequestContext) -> ToolResult:
    results = []

    for service, handler in self.handlers.items():
      try:
        prompts = await handler.get_prompts()

        for pormpt in prompts:
          args_list = []

          if hasattr(pormpt, "arguments") and pormpt.arguments:
            for arg in pormpt.arguments:
              args_list.append(
                {
                  "name": arg.name,
                  "description": getattr(arg, "description", None) or "",
                  "required": getattr(arg, "required", False),
                }
              )

          results.append(
            {
              "service": service.value if hasattr(service, "value") else str(service),
              "name": pormpt.name,
              "title": getattr(pormpt, "title", None) or pormpt.name,
              "description": getattr(pormpt, "description", None) or "",
              "arguments": args_list,
            }
          )
      except Exception as exc:
        logger.warning(f"Failed to list prompts from {service}: {exc}")

    return ToolResult(name=self.name, data={"prompts": results})


class GetPromptTool:
  name = "get_prompt"
  definition: ClassVar[dict[str, Any]] = {
    "type": "function",
    "function": {
      "name": name,
      "description": "Get the rendered messages of a specific prompt template by name, providing any required arguments.",
      "parameters": {
        "type": "object",
        "properties": {
          "name": {
            "type": "string",
            "description": "The name of the prompt template to render.",
          },
          "arguments": {
            "type": "object",
            "description": "Arguments to pass to the prompt template, as key-value pairs of strings.",
            "additionalProperties": {"type": "string"},
          },
        },
        "required": ["name"],
      },
    },
  }

  def __init__(self, handlers: "ServiceHandlers"):
    self.handlers = handlers

  async def execute(self, arguments: dict[str, Any], context: ProcessRequestContext) -> ToolResult:
    name = arguments.get("name")
    args = arguments.get("arguments") or {}

    string_args = {k: str(v) for k, v in args.items()}

    if not name:
      return ToolResult(name=self.name, data={"error": "Prompt name is required"})

    for service, handler in self.handlers.items():
      try:
        prompts = await handler.get_prompts()

        if any(p.name == name for p in prompts):
          result = await handler.get_prompt(name, string_args)
          messages = []

          if hasattr(result, "messages"):
            for msg in result.messages:
              content_text = ""

              if hasattr(msg, "content"):
                content = msg.content
                content_text = content.text if hasattr(content, "text") else str(content)

              messages.append(
                {
                  "role": msg.role,
                  "content": content_text,
                }
              )
          return ToolResult(
            name=name,
            data={
              "description": getattr(result, "description", "") or "",
              "messages": messages,
            },
            service=service,
          )
      except Exception as exc:
        logger.warning(f"Failed to get prompt {name} from {service}: {exc}")

    for service, handler in self.handlers.items():
      try:
        result = await handler.get_prompt(name, string_args)
        messages = []

        for msg in result.messages:
          content_text = ""
          content = msg.content
          content_text = content.text

          messages.append(
            {
              "role": msg.role,
              "content": content_text,
            }
          )
        return ToolResult(
          name=name,
          data={
            "description": getattr(result, "description", "") or "",
            "messages": messages,
          },
          service=service,
        )
      except Exception:
        pass

    return ToolResult(name=name, data={"error": f"Prompt not found or failed to render: {name}"})


class ToolRegistry:
  def __init__(self, tools: list[OllamaTool | MCPTool]):
    self.tools = {tool.name: tool for tool in tools}

  @property
  def definitions(self) -> list[dict[str, Any]]:
    return [tool.definition for tool in self.tools.values()]

  async def execute(self, name: str, arguments: dict[str, Any], context: ProcessRequestContext) -> ToolResult:
    tool = self.tools.get(name)

    if tool is None:
      return ToolResult(name=name, data={"error": f"Unknown tool: {name}"})

    return await tool.execute(self._arguments(name, arguments, context), context)

  def _arguments(self, name: str, arguments: dict[str, Any], context: ProcessRequestContext) -> dict[str, Any]:
    defaults: dict[str, Any] = {}
    tools_context = context.get("tools")
    named_context = context.get(name)

    if isinstance(tools_context, dict) and isinstance(tools_context.get(name), dict):
      defaults.update(tools_context[name])

    if isinstance(named_context, dict):
      defaults.update(named_context)

    return defaults | arguments
