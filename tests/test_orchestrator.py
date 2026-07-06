import logging

import httpx
import pytest

from akorin.core.constants import Service
from akorin.core.models import ProcessRequest
from akorin.core.exceptions import ComponentUnavailable
from akorin.core.exceptions import ComponentRequestError
from akorin.core.exceptions import NoResultFound
from akorin.llm.agent import ChatResult
from akorin.services.orchestrator import Orchestrator
from akorin.services.orchestrator import heuristic_route
from akorin.services.router import rule_route
from akorin.services.tools import ToolResult


class FakeOllama:
  def __init__(self, tools=None):
    self.tools = tools or []

  async def spellcheck(self, text, language):
    return text

  async def translate(self, text, source_language, target_language):
    translations = {
      "Météo à Paris": "Weather in Paris",
      "Wikipédia : quelle est la capitale de la Chine ?": "Wikipedia: what is the capital of China?",
      "quelle heure est il ?": "what time is it?",
      "I can't retrieve the weather right now. Please try again shortly.": (
        "Je ne peux pas obtenir la météo pour le moment. Veuillez réessayer bientôt."
      ),
      "The capital of China is Beijing.": "La capitale de la Chine est Pékin.",
      "fallback chat": "discussion de secours",
    }
    return translations.get(text, text)

  async def route(self, text, language):
    raise httpx.ConnectError("offline")

  async def chat_with_tools(self, text, language, context, tools):
    message = "discussion de secours" if language == "fr" else "fallback chat"
    return ChatResult(message=message, tools=self.tools)

  async def answer_from_source(self, question, source, language):
    if language == "fr":
      return "La capitale de la Chine est Pékin."
    return "The capital of China is Beijing."


class FakeComponent:
  def __init__(self, unavailable=False):
    self.unavailable = unavailable

  async def process(self, text, language, context, tags):
    if self.unavailable:
      raise ComponentUnavailable("weather", "offline")
    return "Sunny", {"temperature": 22}


class FakeResultComponent:
  def __init__(self, message, data):
    self.message = message
    self.data = data

  async def process(self, text, language, context, tags):
    return self.message, self.data


class FakeIncompleteRequestComponent:
  async def process(self, text, language, context, tags):
    raise ComponentRequestError(
      "weather",
      "context.lat and context.lon are required",
      message_en="Please share a location so I can check alerts for that area.",
      message_fr="Veuillez indiquer un lieu pour que je puisse vérifier les alertes dans cette zone.",
    )


class FakeWikipediaWithoutResult:
  async def process(self, text, language, context, tags):
    raise NoResultFound("wikipedia")


class FakeWikipediaResult:
  async def process(self, text, language, context, tags):
    source = "Les capitales historiques incluent Pékin. Pékin est l'actuelle capitale de la Chine."
    return source, {"source": "Wikipedia", "url": "https://fr.wikipedia.org/wiki/Chine"}


class FakeSearch:
  async def process(self, text, language, context, tags):
    return "Web result", {"source": "search"}


def test_heuristic_routes_bilingual_intents():
  assert heuristic_route("Météo à Paris")[0] == Service.WEATHER
  assert heuristic_route("Play a podcast")[0] == Service.KANSA
  assert heuristic_route("Hello there")[0] == Service.CHAT
  assert heuristic_route("Recherche Wikipédia sur le Cameroun")[0] == Service.WIKIPEDIA


@pytest.mark.parametrize(
  "text",
  [
    "light up the bedroom light",
    "turn on the light in the room",
    "switch on the bedroom lamp",
  ],
)
def test_rule_router_stably_routes_device_command_variants(text):
  match = rule_route(text)

  assert match is not None
  assert match.service == Service.ZIGBEE
  assert match.confidence == 0.98


def test_rule_router_distinguishes_light_names_and_weather_stations_from_radio():
  radio = rule_route("play KTLF The Light radio station")
  weather = rule_route("show the weather station forecast")

  assert radio is not None and radio.service == Service.REDIYO
  assert weather is not None and weather.service == Service.WEATHER


def test_rule_router_accepts_explicit_service_context():
  match = rule_route("tell me about Lagos", {"route_to": "wikipedia"})

  assert match is not None
  assert match.service == Service.WIKIPEDIA
  assert match.reason == "explicit service context"


def test_rule_router_ignores_non_service_context_values():
  match = rule_route("Are there alerts?", {"service": "air-quality"})

  assert match is None


@pytest.mark.asyncio
async def test_process_uses_router_fallback_and_component():
  orchestrator = Orchestrator(FakeOllama(), {Service.WEATHER: FakeComponent()})
  result = await orchestrator.process(ProcessRequest(text="Weather in London"))
  assert result.service == Service.WEATHER
  assert result.message == "Sunny"
  assert result.data == {"temperature": 22}


@pytest.mark.asyncio
async def test_rediyo_result_selects_speak_then_play_commands():
  component = FakeResultComponent(
    "Here is France Culture.",
    {"station": {"name": "France Culture", "url": "https://radio.example/live.mp3"}},
  )
  orchestrator = Orchestrator(FakeOllama(), {Service.REDIYO: component})

  result = await orchestrator.process(ProcessRequest(text="Play France Culture radio", language="en"))

  assert [command.model_dump(mode="json", exclude_none=True) for command in result.commands] == [
    {"type": "speak", "text": "Here is France Culture."},
    {"type": "play", "url": "https://radio.example/live.mp3"},
  ]


@pytest.mark.asyncio
async def test_isinmi_result_selects_speak_then_reminder_commands():
  component = FakeResultComponent(
    "Reminder created.",
    {
      "ok": True,
      "action": "create",
      "id": "medicine",
      "type": "reminder",
      "data": {
        "type": "reminder",
        "label": "Take your medicine",
        "time": "2026-06-23T18:30:00+02:00",
      },
    },
  )
  orchestrator = Orchestrator(FakeOllama(), {Service.ISINMI: component})

  result = await orchestrator.process(
    ProcessRequest(
      text="Remind me to take my medicine tomorrow",
      language="en",
      context={"timezone": "Europe/Paris"},
    )
  )

  assert [command.model_dump(mode="json", exclude_none=True) for command in result.commands] == [
    {"type": "speak", "text": "Reminder created."},
    {
      "type": "reminder",
      "id": "medicine",
      "at": "2026-06-23T18:30:00+02:00",
      "message": "Take your medicine",
    },
  ]


@pytest.mark.asyncio
async def test_incomplete_media_result_falls_back_to_automatic_message_speech():
  component = FakeResultComponent("No playable station found.", {"station": {"name": "Unknown"}})
  orchestrator = Orchestrator(FakeOllama(), {Service.REDIYO: component})

  result = await orchestrator.process(ProcessRequest(text="Play an unknown station", language="en"))

  assert result.commands == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
  ("text", "language", "command"),
  [
    ("pause the radio", "en", {"type": "pause"}),
    ("reprends la lecture", "fr", {"type": "resume"}),
    ("set volume to 60%", "en", {"type": "set_volume", "volume": 60}),
    ("coupe le son", "fr", {"type": "mute", "muted": True}),
    ("unmute", "en", {"type": "mute", "muted": False}),
    ("use the voice Ada", "en", {"type": "set_voice", "voice": "Ada"}),
  ],
)
async def test_direct_device_controls_bypass_conversational_processing(text, language, command):
  orchestrator = Orchestrator(FakeOllama(), {})

  result = await orchestrator.process(ProcessRequest(message=message, language=language))

  assert result.service == Service.DEVICE
  assert result.commands[0].model_dump(mode="json", exclude_none=True) == command


@pytest.mark.asyncio
async def test_invalid_direct_device_control_is_not_emitted():
  orchestrator = Orchestrator(FakeOllama(), {})

  result = await orchestrator.process(ProcessRequest(text="set volume to 101", language="en"))

  assert result.service == Service.CHAT
  assert result.commands == []


@pytest.mark.asyncio
async def test_processing_emits_correlated_debug_information(caplog):
  orchestrator = Orchestrator(FakeOllama(), {Service.WEATHER: FakeComponent()})

  with caplog.at_level(logging.DEBUG, logger="oremi-akorin"):
    await orchestrator.process(
      ProcessRequest(
        text="Weather in London",
        context={"timezone": "Europe/London"},
        tags=["private-user-id"],
      )
    )

  messages = [record.getMessage() for record in caplog.records]
  assert any(
    "Processing started:" in message and "context_keys=['timezone']" in message and "input_text='Weather in London'" in message
    for message in messages
  )
  assert any(
    "Spellcheck completed: language=en" in message
    and "source_text='Weather in London' result_text='Weather in London'" in message
    for message in messages
  )
  assert any("Routing completed:" in message and "service=weather" in message for message in messages)
  assert any("Dispatching request: service=weather handler=FakeComponent" in message for message in messages)
  assert any(
    "Processing completed: ok=True service=weather" in message and "response='Sunny'" in message for message in messages
  )
  assert not any("private-user-id" in message for message in messages)


@pytest.mark.asyncio
async def test_non_english_request_is_processed_in_original_language(caplog):
  calls = []

  class NormalizingOllama(FakeOllama):
    async def spellcheck(self, text, language):
      calls.append(("spellcheck", text, language))
      return "Quelle heure est-il ?"

    async def translate(self, text, source_language, target_language):
      calls.append(("translate", text, source_language, target_language))
      return text

    async def chat_with_tools(self, text, language, context, tools):
      calls.append(("chat", text, language))
      return ChatResult(message="Il est 14 h 32.", tools=[])

  orchestrator = Orchestrator(NormalizingOllama(), {})

  with caplog.at_level(logging.DEBUG, logger="oremi-akorin"):
    result = await orchestrator.process(ProcessRequest(text="quelle heure est il ?", language="fr"))

  assert calls == [
    ("spellcheck", "quelle heure est il ?", "fr"),
    ("chat", "Quelle heure est-il ?", "fr"),
  ]
  assert result.input == "quelle heure est il ?"
  assert result.language.value == "fr"
  assert result.message == "Il est 14 h 32."
  messages = [record.getMessage() for record in caplog.records]
  assert any(
    "Spellcheck completed: language=fr" in message
    and "source_text='quelle heure est il ?' result_text='Quelle heure est-il ?'" in message
    for message in messages
  )
  assert not any("translation completed" in message.casefold() for message in messages)


@pytest.mark.asyncio
async def test_component_failure_returns_an_explanatory_response():
  orchestrator = Orchestrator(FakeOllama(), {Service.WEATHER: FakeComponent(unavailable=True)})
  result = await orchestrator.process(ProcessRequest(text="Weather in London"))
  assert result.ok is False
  assert result.service == Service.WEATHER
  assert result.message == "I can't retrieve the weather right now. Please try again shortly."
  assert result.data == {"error": {"type": "service_temporarily_unavailable"}}
  assert "offline" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_component_failure_message_uses_request_language():
  orchestrator = Orchestrator(FakeOllama(), {Service.WEATHER: FakeComponent(unavailable=True)})
  result = await orchestrator.process(ProcessRequest(text="Météo à Paris", language="fr"))

  assert result.message == "Je ne parviens pas à obtenir la météo actuelle. Veuillez réessayer sous peu."
  assert "offline" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_missing_component_input_returns_help_without_internal_details():
  orchestrator = Orchestrator(FakeOllama(), {Service.WEATHER: FakeIncompleteRequestComponent()})
  result = await orchestrator.process(ProcessRequest(text="Weather alert", language="en"))

  assert result.ok is False
  assert result.service == Service.WEATHER
  assert result.message == "Please share a location so I can check alerts for that area."
  assert result.data == {"error": {"type": "more_information_required"}}
  assert "context.lat" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_wikipedia_without_results_falls_back_to_web_search():
  orchestrator = Orchestrator(
    FakeOllama(),
    {
      Service.WIKIPEDIA: FakeWikipediaWithoutResult(),
      Service.SEARCH: FakeSearch(),
    },
  )
  result = await orchestrator.process(ProcessRequest(text="Wikipedia unknown subject", language="en"))

  assert result.ok is True
  assert result.service == Service.SEARCH
  assert result.message == "Web result"
  assert result.data == {"source": "search"}


@pytest.mark.asyncio
async def test_wikipedia_result_is_synthesized_into_a_short_grounded_answer():
  orchestrator = Orchestrator(FakeOllama(), {Service.WIKIPEDIA: FakeWikipediaResult()})

  result = await orchestrator.process(ProcessRequest(text="Wikipédia : quelle est la capitale de la Chine ?", language="fr"))

  assert result.service == Service.WIKIPEDIA
  assert result.message == "La capitale de la Chine est Pékin."
  assert result.data["source"] == "Wikipedia"


@pytest.mark.asyncio
async def test_native_ollama_tool_result_is_exposed_in_response():
  tool_result = ToolResult(name="get_current_datetime", data={"time": "14:32:00", "timezone": "UTC"})
  orchestrator = Orchestrator(FakeOllama([tool_result]), {})

  result = await orchestrator.process(ProcessRequest(text="quelle heure est il ?"))

  assert result.service == Service.TOOL
  assert result.message == "discussion de secours"
  assert result.data["tools"] == [
    {"name": "get_current_datetime", "time": "14:32:00", "timezone": "UTC"},
  ]
  assert result.confidence == 1.0
