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
from typing import Any
from typing import TYPE_CHECKING

import httpx

from ..core.constants import Service
from .prompts import CHAT_PROMPT
from .prompts import CHAT_SYSTEM_PROMPT
from .prompts import GROUNDED_ANSWER_PROMPT
from .prompts import ROUTER_PROMPT
from .prompts import SPELLCHECK_PROMPT
from .prompts import TRANSLATION_PROMPT

if TYPE_CHECKING:
  from ..services.tools import ToolRegistry
  from ..services.tools import ToolResult


@dataclass(frozen=True, slots=True)
class ChatResult:
  message: str
  tools: list[ToolResult]


class OllamaClient:
  def __init__(self, host: str, model: str, client: httpx.AsyncClient):
    self.host = host
    self.model = model
    self.client = client

  async def ensure_model(self) -> None:
    response = await self.client.get(f"{self.host}api/tags")
    response.raise_for_status()
    names = {model.get("name") for model in response.json().get("models", [])}

    if self.model not in names and f"{self.model}:latest" not in names:
      response = await self.client.post(f"{self.host}api/pull", json={"name": self.model, "stream": False}, timeout=None)
      response.raise_for_status()

  async def available(self) -> bool:
    try:
      response = await self.client.get(f"{self.host}api/tags", timeout=1.0)

      return response.is_success
    except httpx.HTTPError:
      return False

  async def _generate(
    self,
    prompt: str,
    *,
    json_format: bool = False,
    options: dict[str, Any] | None = None,
  ) -> str:
    body: dict[str, Any] = {"model": self.model, "prompt": prompt, "stream": False}

    if json_format:
      body["format"] = "json"

    if options:
      body["options"] = options

    response = await self.client.post(f"{self.host}api/generate", json=body)
    response.raise_for_status()

    return str(response.json()["response"]).strip()

  async def route(self, text: str, language: str) -> tuple[Service, float]:
    request = ROUTER_PROMPT.format(text=text, language=language)
    raw = await self._generate(request, json_format=True, options={"temperature": 0, "seed": 0})
    result = json.loads(raw)

    return Service(result["service"]), max(0.0, min(1.0, float(result.get("confidence", 0.8))))

  async def spellcheck(self, text: str, language: str) -> str:
    return await self._generate(SPELLCHECK_PROMPT.format(text=text, language=language))

  async def translate(self, text: str, source_language: str, target_language: str) -> str:
    return await self._generate(
      TRANSLATION_PROMPT.format(
        text=text,
        source_language=source_language,
        target_language=target_language,
      )
    )

  async def chat(self, text: str, language: str, context: dict[str, Any]) -> str:
    return await self._generate(CHAT_PROMPT.format(text=text, language=language, context=json.dumps(context)))

  async def answer_from_source(self, question: str, source: str, language: str) -> str:
    prompt = GROUNDED_ANSWER_PROMPT.format(
      question=question,
      source=source[:6000],
      language=language,
    )

    response = await self.client.post(
      f"{self.host}api/generate",
      json={
        "model": self.model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0, "num_predict": 100},
      },
    )

    response.raise_for_status()

    return str(response.json()["response"]).strip()

  async def chat_with_tools(
    self,
    text: str,
    language: str,
    context: dict[str, Any],
    tools: ToolRegistry,
    *,
    max_iterations: int = 4,
  ) -> ChatResult:
    messages: list[dict[str, Any]] = [
      {"role": "system", "content": CHAT_SYSTEM_PROMPT.format(language=language)},
      {"role": "user", "content": text},
    ]
    executed_tools: list[ToolResult] = []

    for _ in range(max_iterations):
      response = await self.client.post(
        f"{self.host}api/chat",
        json={
          "model": self.model,
          "messages": messages,
          "tools": tools.definitions,
          "stream": False,
        },
      )

      response.raise_for_status()

      assistant_message = response.json()["message"]
      messages.append(assistant_message)
      tool_calls = assistant_message.get("tool_calls") or []

      if not tool_calls:
        return ChatResult(message=str(assistant_message.get("content", "")).strip(), tools=executed_tools)

      for tool_call in tool_calls:
        function = tool_call.get("function", {})
        name = str(function.get("name", ""))
        arguments = function.get("arguments") or {}

        if not isinstance(arguments, dict):
          arguments = {}

        result = await tools.execute(name, arguments, context)
        executed_tools.append(result)
        messages.append({"role": "tool", "tool_name": name, "content": result.as_message_content()})

    raise RuntimeError("Ollama tool loop exceeded its maximum number of iterations")
