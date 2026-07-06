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
from akorin.llm.agent import AgentClient
from akorin.services.tools import DateTimeTool
from akorin.services.tools import ToolRegistry


def isolated_settings() -> Settings:
  return Settings(llm_model="test", ollama_base_url=None)


@pytest.mark.asyncio
async def test_chat_prompt_forbids_meta_commentary():
  captured = ""

  def handler(messages, info: AgentInfo) -> ModelResponse:
    nonlocal captured
    captured = str(messages)
    return ModelResponse(parts=[TextPart("Ça va bien.")])

  async with httpx.AsyncClient() as client:
    agent = AgentClient(isolated_settings(), client, model=FunctionModel(handler))
    response = await agent.chat("Comment vas-tu ?", "fr", {"mood": "curious"})

  assert response == "Ça va bien."
  assert "Never include notes" in captured
  assert 'Context: {"mood":"curious"}' in captured


@pytest.mark.asyncio
async def test_router_generation_is_deterministic():
  async with httpx.AsyncClient() as client:
    agent = AgentClient(
      isolated_settings(),
      client,
      model=TestModel(custom_output_args={"service": "chat", "confidence": 0.8}),
    )
    service, confidence = await agent.route("Tell me something interesting", "en")

  assert service == Service.CHAT
  assert confidence == 0.8


@pytest.mark.asyncio
async def test_spellcheck_and_translation_prompts_return_only_generated_text():
  prompts = []

  def handler(messages, info: AgentInfo) -> ModelResponse:
    prompts.append(str(messages))
    response = "Quelle heure est-il ?" if len(prompts) == 1 else "What time is it?"
    return ModelResponse(parts=[TextPart(response)])

  async with httpx.AsyncClient() as client:
    agent = AgentClient(isolated_settings(), client, model=FunctionModel(handler))
    corrected = await agent.spellcheck("quelle heure est il ?", "fr")
    translated = await agent.translate(corrected, "fr", "en")

  assert corrected == "Quelle heure est-il ?"
  assert translated == "What time is it?"
  assert "Correct spelling, grammar, and punctuation" in prompts[0]
  assert "from fr to en" in prompts[1]


@pytest.mark.asyncio
async def test_pydantic_ai_tool_call_records_tool_result():
  current = datetime(2026, 6, 20, 14, 32, tzinfo=timezone.utc)
  tools = ToolRegistry([DateTimeTool(clock=lambda: current)])

  async with httpx.AsyncClient() as client:
    agent = AgentClient(
      isolated_settings(),
      client,
      model=TestModel(call_tools=["get_current_datetime"], custom_output_text="Il est 14 h 32."),
    )
    result = await agent.chat_with_tools("Quelle heure est-il ?", "fr", {"timezone": "Europe/Paris"}, tools)

  assert result.message == "Il est 14 h 32."
  assert result.tools[0].name == "get_current_datetime"
  assert result.tools[0].data["datetime"] == "2026-06-20T16:32:00+02:00"


@pytest.mark.asyncio
async def test_grounded_answer_is_constrained_and_deterministic():
  captured = ""
  captured_settings = None

  def handler(messages, info: AgentInfo) -> ModelResponse:
    nonlocal captured, captured_settings
    captured = str(messages)
    captured_settings = info.model_settings
    return ModelResponse(parts=[TextPart("La capitale de la Chine est Pékin.")])

  async with httpx.AsyncClient() as client:
    agent = AgentClient(isolated_settings(), client, model=FunctionModel(handler))
    result = await agent.answer_from_source(
      "Quelle est la capitale de la Chine ?",
      "Pékin est l'actuelle capitale de la république populaire de Chine.",
      "fr",
    )

  assert result == "La capitale de la Chine est Pékin."
  assert captured_settings["temperature"] == 0
  assert captured_settings["max_tokens"] == 100
  assert "using only the supplied source" in captured
  assert "at most two short sentences" in captured
