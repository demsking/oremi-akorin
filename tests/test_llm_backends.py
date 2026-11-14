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
from datetime import datetime
from datetime import timezone
from typing import Any

import httpx
import httpx2
import pytest
from pydantic import ValidationError
from pydantic_ai import ModelSettings
from pydantic_ai.exceptions import ModelAPIError
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelResponse
from pydantic_ai.messages import TextPart
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.models.function import AgentInfo
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from akorin.agents.chat_agent import ChatAgent
from akorin.agents.chat_tools_agent import ChatToolsAgent
from akorin.agents.command_agent import CommandAgent
from akorin.core.agent import AgentClient
from akorin.core.service import Service
from akorin.core.settings import Settings
from akorin.core.tools import ToolRegistry
from akorin.tools.datetime_tool import DateTimeTool


def backend_settings(**overrides: Any) -> Settings:
  values: dict[str, Any] = {
    "llm_model": "qwen2.5:3b",
    "llm_backend": "max",
    "llm_base_url": "http://inference.test/v1",
    "isinmi_url": None,
    "ojo_url": None,
    "rediyo_url": None,
    "kansa_url": None,
    "isakoso_url": None,
  }
  values.update(overrides)

  return Settings(**values)


def completion(content: str) -> dict[str, Any]:
  return {
    "id": "chatcmpl-test",
    "object": "chat.completion",
    "created": 0,
    "model": "qwen2.5:3b",
    "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
  }


def mock_chat_model(handler: Any) -> tuple[OpenAIChatModel, httpx.AsyncClient]:
  """Build an OpenAI-compatible model backed by an offline httpx MockTransport."""
  http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
  provider = OpenAIProvider(base_url="http://inference.test/v1", api_key="test", http_client=http_client)

  return OpenAIChatModel("qwen2.5:3b", provider=provider), http_client


def use_model(monkeypatch: pytest.MonkeyPatch, model: Any) -> None:
  monkeypatch.setattr(AgentClient, "build_model", staticmethod(lambda settings, model_settings, client: model))


def test_auto_backend_preserves_ollama_detection():
  settings = Settings(llm_model="ollama:qwen2.5:3b", ollama_base_url="http://ollama.test:11434")

  assert settings.resolved_llm_backend == "ollama"
  assert settings.should_use_ollama
  assert not settings.should_use_openai_compatible


def test_auto_backend_defaults_to_pydantic_provider():
  settings = Settings(llm_model="openai:gpt-4.1-mini")

  assert settings.resolved_llm_backend == "pydantic"
  assert not settings.should_use_ollama
  assert not settings.should_use_openai_compatible


@pytest.mark.parametrize("backend", ["sglang", "max"])
def test_openai_compatible_backends_resolve_and_normalize_base_url(backend: str):
  settings = backend_settings(llm_backend=backend, llm_base_url="http://inference.test:8000/v1/")

  assert settings.resolved_llm_backend == backend
  assert settings.should_use_openai_compatible
  assert not settings.should_use_ollama
  assert settings.llm_base_url_string == "http://inference.test:8000/v1"


@pytest.mark.parametrize("backend", ["sglang", "max"])
def test_openai_compatible_backend_requires_base_url(backend: str):
  with pytest.raises(ValidationError, match="OREMI_AKORIN_LLM_BASE_URL"):
    Settings(llm_model="qwen2.5:3b", llm_backend=backend)


def test_invalid_backend_is_rejected():
  with pytest.raises(ValidationError):
    Settings(llm_model="qwen2.5:3b", llm_backend="vllm")


def test_explicit_backend_overrides_model_prefix():
  settings = backend_settings(llm_backend="max", llm_model="ollama:qwen2.5:3b")

  assert settings.resolved_llm_backend == "max"
  assert not settings.should_use_ollama
  assert settings.should_use_openai_compatible


def test_explicit_ollama_backend_accepts_plain_model_name():
  settings = Settings(llm_backend="ollama", llm_model="qwen2.5:3b", ollama_base_url="http://ollama.test:11434")

  assert settings.resolved_llm_backend == "ollama"
  assert settings.should_use_ollama
  assert settings.ollama_model_name == "qwen2.5:3b"


def test_build_model_returns_openai_compatible_model():
  settings = backend_settings(llm_backend="sglang")

  model = AgentClient.build_model(settings, ModelSettings(), httpx2.AsyncClient())

  assert isinstance(model, OpenAIChatModel)
  assert model.model_name == "qwen2.5:3b"
  assert str(model.provider.client.base_url).startswith("http://inference.test/v1")
  assert model.profile.get("default_structured_output_mode") == "native"


def test_build_model_keeps_provider_string_for_default_backend():
  settings = Settings(llm_model="openai:gpt-4.1-mini")

  assert AgentClient.build_model(settings, ModelSettings(), httpx2.AsyncClient()) == "openai:gpt-4.1-mini"


def test_openai_backend_does_not_create_ollama_client():
  agent = ChatAgent(backend_settings(), httpx2.AsyncClient())

  assert agent.ollama_client is None
  assert isinstance(agent.model, OpenAIChatModel)


def test_native_ollama_backend_is_unchanged():
  settings = Settings(llm_model="ollama:qwen2.5:3b", ollama_base_url="http://ollama.test:11434")

  agent = ChatAgent(settings, httpx2.AsyncClient())

  assert agent.ollama_client is not None
  assert agent.model is None


@pytest.mark.asyncio
async def test_openai_compatible_chat_uses_http_transport(monkeypatch):
  model, http_client = mock_chat_model(lambda request: httpx.Response(200, json=completion("Bonjour")))

  use_model(monkeypatch, model)

  async with httpx2.AsyncClient() as client:
    agent = ChatAgent(backend_settings(), client)
    result = await agent.chat("Salut", "fr", {})

  assert result == "Bonjour"

  await http_client.aclose()


@pytest.mark.asyncio
async def test_openai_compatible_backend_unavailable_raises(monkeypatch):
  def handler(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused")

  model, http_client = mock_chat_model(handler)

  use_model(monkeypatch, model)

  async with httpx2.AsyncClient() as client:
    agent = ChatAgent(backend_settings(), client)

    with pytest.raises(ModelAPIError):
      await agent.chat("Salut", "fr", {})

  await http_client.aclose()


@pytest.mark.asyncio
async def test_openai_compatible_backend_timeout_raises(monkeypatch):
  def handler(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("timed out")

  model, http_client = mock_chat_model(handler)

  use_model(monkeypatch, model)

  async with httpx2.AsyncClient() as client:
    agent = ChatAgent(backend_settings(), client)

    with pytest.raises(ModelAPIError):
      await agent.chat("Salut", "fr", {})

  await http_client.aclose()


@pytest.mark.asyncio
async def test_openai_compatible_http_error_raises(monkeypatch):
  def handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(503, json={"error": {"message": "service unavailable"}})

  model, http_client = mock_chat_model(handler)

  use_model(monkeypatch, model)

  async with httpx2.AsyncClient() as client:
    agent = ChatAgent(backend_settings(), client)

    with pytest.raises(ModelHTTPError):
      await agent.chat("Salut", "fr", {})

  await http_client.aclose()


@pytest.mark.asyncio
async def test_explicit_backend_supports_structured_output(monkeypatch):
  def handler(messages: Any, info: AgentInfo) -> ModelResponse:
    return ModelResponse(
      parts=[
        ToolCallPart(
          tool_name="final_result",
          args={"service": Service.OREMI_ISAKOSO.value, "confidence": 0.97},
          tool_call_id="final_result_call",
        )
      ]
    )

  use_model(monkeypatch, FunctionModel(handler))

  async with httpx2.AsyncClient() as client:
    agent = CommandAgent(backend_settings(), client)
    decision = await agent.classify("Allume la lumière du salon")

  assert decision.service == Service.OREMI_ISAKOSO
  assert decision.confidence == pytest.approx(0.97)


@pytest.mark.asyncio
async def test_explicit_backend_supports_tool_calling(monkeypatch):
  current = datetime(2026, 6, 20, 14, 32, tzinfo=timezone.utc)
  calls = {"count": 0}

  def handler(messages: Any, info: AgentInfo) -> ModelResponse:
    calls["count"] += 1

    if calls["count"] == 1:
      return ModelResponse(
        parts=[
          ToolCallPart(
            tool_name="get_current_datetime",
            args={"timezone": "Europe/Paris"},
            tool_call_id="datetime_call",
          )
        ]
      )

    return ModelResponse(parts=[TextPart("Il est 16 h 32.")])

  use_model(monkeypatch, FunctionModel(handler))

  tools = ToolRegistry([DateTimeTool(clock=lambda: current)])

  async with httpx2.AsyncClient() as client:
    agent = ChatToolsAgent(backend_settings(), client)
    result = await agent.chat("Quelle heure est-il ?", "fr", {"timezone": "Europe/Paris"}, tools)

  assert result.message == "Il est 16 h 32."
  assert result.tools[0].name == "get_current_datetime"
  assert result.tools[0].data["datetime"] == "2026-06-20T16:32:00+02:00"
