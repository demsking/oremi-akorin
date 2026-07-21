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

import httpx
import pytest
from pydantic_ai.messages import ModelResponse
from pydantic_ai.messages import TextPart
from pydantic_ai.models.function import AgentInfo
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel

from akorin.agents.chat_agent import ChatAgent
from akorin.agents.chat_tools_agent import ChatToolsAgent
from akorin.agents.command_agent import CommandAgent
from akorin.agents.response_agent import ResponseAgent
from akorin.api.agent import PAYLOAD_EXAMPLES
from akorin.core.agent import AgentClient
from akorin.core.service import Service
from akorin.core.settings import Settings
from akorin.core.tools import ToolRegistry
from akorin.tools.datetime_tool import DateTimeTool


def isolated_settings() -> Settings:
  return Settings(llm_model="test", ollama_base_url=None)


def ollama_settings() -> Settings:
  return Settings(llm_model="ollama:qwen3.5:2b", ollama_base_url="http://ollama.test:11434")


def use_model(monkeypatch: pytest.MonkeyPatch, model):
  monkeypatch.setattr(AgentClient, "build_model", staticmethod(lambda settings, model_settings, client: model))


@pytest.mark.asyncio
async def test_chat_prompt_forbids_meta_commentary(monkeypatch):
  captured = ""

  def handler(messages, info: AgentInfo) -> ModelResponse:
    nonlocal captured
    captured = str(messages)
    return ModelResponse(parts=[TextPart("Ça va bien.")])

  use_model(monkeypatch, FunctionModel(handler))

  async with httpx.AsyncClient() as client:
    agent = ChatAgent(isolated_settings(), client)
    response = await agent.chat("Comment vas-tu ?", "fr", {"mood": "curious"})

  assert response == "Ça va bien."
  assert "Never include notes" in captured
  assert 'Context: {"mood":"curious"}' in captured


@pytest.mark.asyncio
async def test_router_generation_is_deterministic(monkeypatch):
  use_model(monkeypatch, TestModel(custom_output_args={"service": "chat", "confidence": 0.8}))

  async with httpx.AsyncClient() as client:
    agent = CommandAgent(isolated_settings(), client)
    decision = await agent.classify("Tell me something interesting")

  assert decision.service == Service.CHAT
  assert decision.confidence == 0.8


@pytest.mark.asyncio
async def test_command_agent_classifies_all_payload_examples(monkeypatch):
  expected_services = {
    "weather": Service.OREMI_OJO,
    "Weather forecast (EN)": Service.OREMI_OJO,
    "Météo (FR)": Service.OREMI_OJO,
    "Weather with Oremi Device context": Service.OREMI_OJO,
    "Pollen count (EN)": Service.OREMI_OJO,
    "Alerte Pollen (FR)": Service.OREMI_OJO,
    "zigbee": Service.OREMI_ISAKOSO,
    "Zigbee device command": Service.OREMI_ISAKOSO,
    "Control Zigbee device (EN)": Service.OREMI_ISAKOSO,
    "Contrôler un appareil Zigbee (FR)": Service.OREMI_ISAKOSO,
    "Allumer la lumière de la chambre (FR)": Service.OREMI_ISAKOSO,
    "Éteindre la lumière de la chambre (FR)": Service.OREMI_ISAKOSO,
    "General Chat (EN)": Service.CHAT,
    "Discussion générale (FR)": Service.CHAT,
    "reminder": Service.OREMI_ISINMI,
    "Set a reminder (EN)": Service.OREMI_ISINMI,
    "Créer un rappel (FR)": Service.OREMI_ISINMI,
    "Créer un rappel avec un context élargie (FR)": Service.OREMI_ISINMI,
    "Schedule recurring event (EN)": Service.OREMI_ISINMI,
    "Planifier un événement (FR)": Service.OREMI_ISINMI,
    "Play Radio (EN)": Service.OREMI_REDIYO,
    "Lancer la radio (FR)": Service.OREMI_REDIYO,
    "Play Podcast (EN)": Service.OREMI_KANSA,
    "Lancer un podcast (FR)": Service.OREMI_KANSA,
  }
  message_to_service = {}
  for name, example in PAYLOAD_EXAMPLES.items():
    message_to_service[example["value"].message] = expected_services[name]

  def handler(messages, info) -> ModelResponse:
    from pydantic_ai.messages import ModelResponse, ToolCallPart

    prompt = ""
    for m in messages:
      for part in getattr(m, "parts", []):
        if hasattr(part, "content"):
          prompt = part.content
    svc = message_to_service.get(prompt, Service.CHAT)
    return ModelResponse(
      parts=[
        ToolCallPart(
          tool_name="final_result",
          args={"service": svc.value, "confidence": 0.95},
          tool_call_id="final_result_call",
        )
      ]
    )

  use_model(monkeypatch, FunctionModel(handler))

  async with httpx.AsyncClient() as client:
    agent = CommandAgent(isolated_settings(), client)

    for name, example in PAYLOAD_EXAMPLES.items():
      decision = await agent.classify(example["value"].message)

      assert decision.service == expected_services[name], name


@pytest.mark.asyncio
async def test_response_agent_generates_contextual_user_message():
  class FakeMessage:
    content = "La lumière est allumée."
    tool_calls = None

  class FakeResponse:
    message = FakeMessage()

  class FakeOllamaClient:
    def __init__(self):
      self.request = None

    async def chat(self, **kwargs):
      self.request = kwargs
      return FakeResponse()

  async with httpx.AsyncClient() as client:
    agent = ResponseAgent(ollama_settings(), client)
    fake_client = FakeOllamaClient()
    agent.ollama_client = fake_client
    response = await agent.generate(
      "zigbee_command_sent",
      "fr",
      {"device": "Lumière de la chambre", "command": {"state": "ON"}},
    )

  assert response == "La lumière est allumée."
  messages = fake_client.request["messages"]
  assert messages[0]["role"] == "system"
  assert "Return only the message intended for the user" in messages[0]["content"]
  assert "Event type: zigbee_command_sent" in messages[1]["content"]
  assert '"device": "Lumière de la chambre"' in messages[1]["content"]


@pytest.mark.asyncio
async def test_pydantic_ai_tool_call_records_tool_result(monkeypatch):
  current = datetime(2026, 6, 20, 14, 32, tzinfo=timezone.utc)
  tools = ToolRegistry([DateTimeTool(clock=lambda: current)])
  use_model(monkeypatch, TestModel(call_tools=["get_current_datetime"], custom_output_text="Il est 14 h 32."))

  async with httpx.AsyncClient() as client:
    agent = ChatToolsAgent(isolated_settings(), client)
    result = await agent.chat("Quelle heure est-il ?", "fr", {"timezone": "Europe/Paris"}, tools)

  assert result.message == "Il est 14 h 32."
  assert result.tools[0].name == "get_current_datetime"
  assert result.tools[0].data["datetime"] == "2026-06-20T16:32:00+02:00"
