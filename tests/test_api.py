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
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import httpx
import pytest
from pydantic_ai.models.test import TestModel

from akorin.core.agent import AgentClient
from akorin.core.app import create_app
from akorin.core.settings import Settings


def isolated_settings(**overrides) -> Settings:
  values = {
    "llm_model": "test",
    "ollama_base_url": None,
    "isinmi_url": None,
    "ojo_url": None,
    "rediyo_url": None,
    "kansa_url": None,
    "isakoso_url": None,
  }
  values.update(overrides)
  return Settings(**values)


def ollama_handler(request: httpx.Request) -> httpx.Response:
  if request.url.path == "/api/tags":
    return httpx.Response(200, json={"models": [{"name": "qwen2.5:3b"}]})
  if request.url.path == "/api/generate":
    return httpx.Response(200, json={"response": '{"service":"ojo","confidence":0.95}'})
  if request.url.path == "/health/":
    return httpx.Response(
      200,
      json={
        "status": "healthy",
        "app": "oremi-weather",
        "version": "1.2.3",
        "llm_model": "test",
      },
    )
  if request.url.path == "/api/chat":
    import json

    body = json.loads(request.read())
    messages = body.get("messages", [])
    if messages and messages[-1].get("role") == "user":
      return httpx.Response(
        200,
        json={
          "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": "get_weather", "arguments": {"q": "Paris"}}}],
          }
        },
      )
    else:
      return httpx.Response(200, json={"message": {"role": "assistant", "content": "22°C and sunny"}})
  return httpx.Response(200, json={"message": "ok"})


@pytest.mark.asyncio
async def test_process_endpoint(monkeypatch):
  class FakeTool:
    def __init__(self, name, description, inputSchema):
      self.name = name
      self.description = description
      self.inputSchema = inputSchema

  class FakeToolsList:
    def __init__(self, tools):
      self.tools = tools

  class FakeServerInfo:
    def __init__(self, name, version):
      self.name = name
      self.version = version

  class FakeCapabilities:
    def __init__(self, tools=False, resources=False, prompts=False):
      self.tools = tools
      self.resources = resources
      self.prompts = prompts

  def mock_build_model(settings, model_settings, client):
    import inspect
    from akorin.agents.command_agent import CommandAgent

    frame = inspect.currentframe()
    while frame:
      caller_self = frame.f_locals.get("self")
      if isinstance(caller_self, CommandAgent):
        return TestModel(custom_output_args={"service": "ojo", "confidence": 0.95})
      frame = frame.f_back

    return TestModel(call_tools=["get_weather"], custom_output_text="22°C and sunny")

  monkeypatch.setattr(AgentClient, "build_model", staticmethod(mock_build_model))

  mock_read = MagicMock()
  mock_write = MagicMock()

  mock_session = AsyncMock()
  mock_init_result = type(
    "FakeInitResult", (), {"serverInfo": FakeServerInfo("oremi-weather", "1.2.3"), "capabilities": FakeCapabilities(tools=True)}
  )()
  mock_session.initialize = AsyncMock(return_value=mock_init_result)
  mock_session.list_tools = AsyncMock(
    return_value=FakeToolsList(
      [FakeTool("get_weather", "Get weather", {"type": "object", "properties": {"q": {"type": "string"}}})]
    )
  )
  mock_call_result = type(
    "FakeResult", (), {"content": [type("FakeContent", (), {"type": "text", "text": '{"temperature": 22}'})()]}
  )()
  mock_session.call_tool = AsyncMock(return_value=mock_call_result)

  class AsyncContextManagerMock:
    def __init__(self, return_value):
      self.return_value = return_value

    async def __aenter__(self):
      return self.return_value

    async def __aexit__(self, exc_type, exc_val, exc_tb):
      pass

  with (
    patch("akorin.core.components.streamable_http_client", return_value=AsyncContextManagerMock((mock_read, mock_write, None))),
    patch("akorin.core.components.ClientSession", return_value=AsyncContextManagerMock(mock_session)),
  ):
    service_client = httpx.AsyncClient(transport=httpx.MockTransport(ollama_handler))
    app = create_app(isolated_settings(ojo_url="http://weather.test"), service_client)
    async with app.router.lifespan_context(app):
      transport = httpx.ASGITransport(app=app)
      async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
          "/api/agent/",
          json={"text": "Weather in Paris", "context": {"route_to": "ojo"}},
        )

  assert response.status_code == 200
  assert response.json()["service"] == "ojo"
  assert response.json()["message"] == "22°C and sunny"


@pytest.mark.asyncio
async def test_validation_rejects_blank_input():
  service_client = httpx.AsyncClient(transport=httpx.MockTransport(ollama_handler))
  app = create_app(isolated_settings(), service_client)
  async with app.router.lifespan_context(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
      response = await client.post("/api/agent/", json={"text": "  "})
  assert response.status_code == 422


@pytest.mark.asyncio
async def test_startup_and_shutdown_emit_operational_logs(caplog):
  service_client = httpx.AsyncClient(transport=httpx.MockTransport(ollama_handler))
  app = create_app(isolated_settings(), service_client)

  with caplog.at_level(logging.INFO, logger="oremi-akorin"):
    async with app.router.lifespan_context(app):
      pass


@pytest.mark.asyncio
async def test_startup_marks_unreachable_component_as_unavailable():
  def unreachable_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/tags":
      return httpx.Response(200, json={"models": [{"name": "qwen2.5:3b"}]})
    raise httpx.ConnectError("connection refused")

  service_client = httpx.AsyncClient(transport=httpx.MockTransport(unreachable_handler))
  app = create_app(
    isolated_settings(ojo_url="http://weather.test"),
    service_client,
  )

  async with app.router.lifespan_context(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
      response = await client.get("/health/")

  assert response.status_code == 200
  payload = response.json()
  assert payload["status"] == "degraded"
  assert payload["components"]["ojo"] == "unavailable"


@pytest.mark.asyncio
async def test_startup_marks_invalid_component_service_info_as_unavailable():
  from unittest.mock import patch

  def invalid_info_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/server":
      return httpx.Response(200, json={"name": "oremi-weather"})
    return httpx.Response(200, json={"models": []})

  service_client = httpx.AsyncClient(transport=httpx.MockTransport(invalid_info_handler))

  from contextlib import asynccontextmanager

  @asynccontextmanager
  async def mock_streamable_http_client(*args, **kwargs):
    raise RuntimeError("Invalid component service info")
    yield

  with patch("akorin.core.components.streamable_http_client", side_effect=mock_streamable_http_client):
    app = create_app(
      isolated_settings(ojo_url="http://weather.test"),
      service_client,
    )

    async with app.router.lifespan_context(app):
      transport = httpx.ASGITransport(app=app)
      async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/")

  assert response.status_code == 200
  payload = response.json()
  assert payload["status"] == "degraded"
  assert payload["components"]["ojo"] == "unavailable"


@pytest.mark.asyncio
async def test_process_endpoint_when_payload_ok_is_false():
  from akorin.core.orchestrator import Orchestrator
  from akorin.core.request import ProcessRequest
  from akorin.core.tools import ToolRegistry
  from akorin.utils.cache import SmartCache

  mock_response_agent = AsyncMock()
  mock_response_agent.generate.return_value = "Service error message"

  settings = isolated_settings()
  client = MagicMock()
  cache = SmartCache(enabled=True, max_entries=100)
  tools = ToolRegistry([])

  orchestrator = Orchestrator(
    settings=settings,
    client=client,
    handlers={},
    tools=tools,
    cache=cache,
  )
  orchestrator.response_agent = mock_response_agent
  request = ProcessRequest(message="test message")

  with patch.object(orchestrator, "_execute_chat_service", side_effect=Exception("Failed execution")):
    response = await orchestrator.process(request)

  assert response.ok is False
  assert response.message == "Service error message"
  assert len(response.commands) == 1
  assert response.commands[0].type == "speak"
  assert response.commands[0].text == "Service error message"


@pytest.mark.asyncio
async def test_process_endpoint_when_ok_is_false_and_message_empty():
  from akorin.core.orchestrator import Orchestrator
  from akorin.core.request import ProcessRequest
  from akorin.core.tools import ToolRegistry
  from akorin.utils.cache import SmartCache

  mock_response_agent = AsyncMock()
  mock_response_agent.generate.return_value = "Generated fallback error message"

  settings = isolated_settings()
  client = MagicMock()
  cache = SmartCache(enabled=True, max_entries=100)
  tools = ToolRegistry([])

  orchestrator = Orchestrator(
    settings=settings,
    client=client,
    handlers={},
    tools=tools,
    cache=cache,
  )
  orchestrator.response_agent = mock_response_agent

  request = ProcessRequest(message="test message")

  with patch.object(orchestrator, "_execute_chat_service", return_value={"ok": False, "message": ""}):
    response = await orchestrator.process(request)

  assert response.ok is False
  assert response.message == "Generated fallback error message"
  assert len(response.commands) == 1
  assert response.commands[0].type == "speak"
  assert response.commands[0].text == "Generated fallback error message"
  mock_response_agent.generate.assert_called_once()
