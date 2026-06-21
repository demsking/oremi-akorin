import json
from datetime import datetime
from datetime import timezone

import httpx
import pytest

from oremi_akorin.llm.ollama import OllamaClient
from oremi_akorin.services.tools import DateTimeTool
from oremi_akorin.services.tools import ToolRegistry


@pytest.mark.asyncio
async def test_chat_prompt_forbids_meta_commentary():
  captured_prompt = ""

  def handler(request: httpx.Request) -> httpx.Response:
    nonlocal captured_prompt
    captured_prompt = request.read().decode()
    return httpx.Response(200, json={"response": "Ça va bien."})

  async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
    ollama = OllamaClient("http://ollama.test/", "qwen2.5:3b", client)
    response = await ollama.chat("Comment vas-tu ?", "fr", {})

  assert response == "Ça va bien."
  assert "Never include notes" in captured_prompt


@pytest.mark.asyncio
async def test_router_generation_is_deterministic():
  captured = None

  def handler(request: httpx.Request) -> httpx.Response:
    nonlocal captured
    captured = json.loads(request.content)
    return httpx.Response(200, json={"response": '{"service":"chat","confidence":0.8}'})

  async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
    ollama = OllamaClient("http://ollama.test/", "qwen2.5:3b", client)
    await ollama.route("Tell me something interesting", "en")

  assert captured["format"] == "json"
  assert captured["options"] == {"temperature": 0, "seed": 0}


@pytest.mark.asyncio
async def test_spellcheck_and_translation_prompts_return_only_generated_text():
  prompts = []

  def handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    prompts.append(body["prompt"])
    response = "Quelle heure est-il ?" if len(prompts) == 1 else "What time is it?"
    return httpx.Response(200, json={"response": response})

  async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
    ollama = OllamaClient("http://ollama.test/", "qwen2.5:3b", client)
    corrected = await ollama.spellcheck("quelle heure est il ?", "fr")
    translated = await ollama.translate(corrected, "fr", "en")

  assert corrected == "Quelle heure est-il ?"
  assert translated == "What time is it?"
  assert "Correct spelling, grammar, and punctuation" in prompts[0]
  assert "from fr to en" in prompts[1]


@pytest.mark.asyncio
async def test_native_ollama_tool_call_loop():
  requests = []

  def handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    requests.append(body)
    if len(requests) == 1:
      return httpx.Response(
        200,
        json={
          "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [
              {
                "type": "function",
                "function": {"name": "get_current_datetime", "arguments": {}},
              }
            ],
          }
        },
      )
    return httpx.Response(200, json={"message": {"role": "assistant", "content": "Il est 14 h 32."}})

  current = datetime(2026, 6, 20, 14, 32, tzinfo=timezone.utc)
  tools = ToolRegistry([DateTimeTool(clock=lambda: current)])
  async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
    ollama = OllamaClient("http://ollama.test/", "qwen2.5:3b", client)
    result = await ollama.chat_with_tools("Quelle heure est-il ?", "fr", {}, tools)

  assert result.message == "Il est 14 h 32."
  assert result.tools[0].name == "get_current_datetime"
  assert requests[0]["tools"][0]["function"]["name"] == "get_current_datetime"
  tool_message = requests[1]["messages"][-1]
  assert tool_message["role"] == "tool"
  assert tool_message["tool_name"] == "get_current_datetime"
  assert json.loads(tool_message["content"])["datetime"] == "2026-06-20T14:32:00+00:00"


@pytest.mark.asyncio
async def test_grounded_answer_is_constrained_and_deterministic():
  captured = None

  def handler(request: httpx.Request) -> httpx.Response:
    nonlocal captured
    captured = json.loads(request.content)
    return httpx.Response(200, json={"response": "La capitale de la Chine est Pékin."})

  async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
    ollama = OllamaClient("http://ollama.test/", "qwen2.5:3b", client)
    result = await ollama.answer_from_source(
      "Quelle est la capitale de la Chine ?",
      "Pékin est l'actuelle capitale de la république populaire de Chine.",
      "fr",
    )

  assert result == "La capitale de la Chine est Pékin."
  assert captured["options"] == {"temperature": 0, "num_predict": 100}
  assert "using only the supplied source" in captured["prompt"]
  assert "at most two short sentences" in captured["prompt"]
