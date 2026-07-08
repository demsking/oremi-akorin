from datetime import datetime
from datetime import timezone

import httpx
import pytest
from pydantic_ai.messages import ModelResponse
from pydantic_ai.messages import TextPart
from pydantic_ai.models.function import AgentInfo
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel

from akorin.core.constants import Service
from akorin.core.settings import Settings
from akorin.api.agent import PAYLOAD_EXAMPLES
from akorin.llm.agent import AgentClient
from akorin.llm.agents.chat import ChatAgent
from akorin.llm.agents.chat_tools import ChatToolsAgent
from akorin.llm.agents.command import CommandAgent
from akorin.llm.agents.response import ResponseAgent
from akorin.llm.agents.spellcheck import SpellCheckAgent
from akorin.llm.agents.zigbee_command import ZigbeeCommandAgent
from akorin.services.tools import DateTimeTool
from akorin.services.tools import ToolRegistry


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
    "Weather forecast (EN)": Service.WEATHER,
    "Météo (FR)": Service.WEATHER,
    "Pollen count (EN)": Service.WEATHER,
    "Alerte Pollen (FR)": Service.WEATHER,
    "Control Zigbee device (EN)": Service.ZIGBEE,
    "Contrôler un appareil Zigbee (FR)": Service.ZIGBEE,
    "Allumer la lumière de la chambre (FR)": Service.ZIGBEE,
    "Éteindre la lumière de la chambre (FR)": Service.ZIGBEE,
    "General Chat (EN)": Service.CHAT,
    "Discussion générale (FR)": Service.CHAT,
    "Set a reminder (EN)": Service.ISINMI,
    "Créer un rappel (FR)": Service.ISINMI,
    "Schedule recurring event (EN)": Service.ISINMI,
    "Planifier un événement (FR)": Service.ISINMI,
    "Play Radio (EN)": Service.REDIYO,
    "Lancer la radio (FR)": Service.REDIYO,
    "Play Podcast (EN)": Service.KANSA,
    "Lancer un podcast (FR)": Service.KANSA,
  }
  use_model(monkeypatch, TestModel(custom_output_args={"service": "chat", "confidence": 0.1}))

  async with httpx.AsyncClient() as client:
    agent = CommandAgent(isolated_settings(), client)

    for name, example in PAYLOAD_EXAMPLES.items():
      decision = await agent.classify(example["value"].message)

      assert decision.service == expected_services[name], name


@pytest.mark.asyncio
async def test_spellcheck_prompt_returns_only_generated_text(monkeypatch):
  prompts = []

  def handler(messages, info: AgentInfo) -> ModelResponse:
    prompts.append(str(messages))
    return ModelResponse(parts=[TextPart("Quelle heure est-il ?")])

  use_model(monkeypatch, FunctionModel(handler))

  async with httpx.AsyncClient() as client:
    spellcheck_agent = SpellCheckAgent(isolated_settings(), client)
    corrected = await spellcheck_agent.check("quelle heure est il ?", "fr")

  assert corrected == "Quelle heure est-il ?"
  assert "Correct spelling, grammar, punctuation" in prompts[0]


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


@pytest.mark.asyncio
async def test_native_ollama_zigbee_command_handles_non_json_response():
  class FakeMessage:
    content = "I am ready. I have analyzed your device list and can now assist you."
    tool_calls = None

  class FakeResponse:
    message = FakeMessage()

  class FakeOllamaClient:
    async def chat(self, **kwargs):
      return FakeResponse()

  async with httpx.AsyncClient() as client:
    agent = ZigbeeCommandAgent(ollama_settings(), client)
    agent.ollama_client = FakeOllamaClient()
    decision = await agent.select(
      ["allume la lumière de la chambre"],
      [
        {
          "name": "Lumière de la chambre",
          "mqtt_topic": "Lumière de la chambre",
          "operations": [{"property": "state", "type": "binary", "value_on": "ON", "value_off": "OFF"}],
        }
      ],
    )

  assert decision.device is None
  assert decision.payload == {}
  assert decision.state_properties == []
  assert decision.confidence == 0
