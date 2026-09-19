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
import mcp_types as t
import pytest

from akorin.core.request import ProcessRequest
from akorin.core.router import RouteContext
from akorin.core.service import Service
from akorin.routers.spacy_router import SpacyRouter


def make_route_context(message: str) -> RouteContext:
  return RouteContext(
    request=ProcessRequest(message=message),
    request_id="test_req_1",
    language="fr",
    started_at=0.0,
  )


@pytest.mark.asyncio
async def test_spacy_router_categorizes_weather_queries():
  router = SpacyRouter()

  # French weather queries
  res1 = await router.route(make_route_context("Quel temps fait-il à Paris ?"))
  assert res1 is not None
  assert res1.service == Service.OREMI_OJO
  assert res1.confidence >= 0.90

  res2 = await router.route(make_route_context("Quelle est la météo aujourd'hui ?"))
  assert res2 is not None
  assert res2.service == Service.OREMI_OJO

  # English weather query
  res3 = await router.route(make_route_context("What's the weather forecast for tomorrow?"))
  assert res3 is not None
  assert res3.service == Service.OREMI_OJO


@pytest.mark.asyncio
async def test_spacy_router_categorizes_smart_home_queries():
  router = SpacyRouter()

  # French smart home queries
  res1 = await router.route(make_route_context("Allume la lumière de la chambre"))
  assert res1 is not None
  assert res1.service == Service.OREMI_ISAKOSO
  assert res1.selected_prompt is not None
  assert res1.selected_prompt.name == "turn_on_device"

  res2 = await router.route(make_route_context("Éteins la lampe du salon s'il te plaît"))
  assert res2 is not None
  assert res2.service == Service.OREMI_ISAKOSO
  assert res2.selected_prompt is not None
  assert res2.selected_prompt.name == "turn_off_device"

  # English smart home queries
  res3 = await router.route(make_route_context("Turn on the living room lights"))
  assert res3 is not None
  assert res3.service == Service.OREMI_ISAKOSO
  assert res3.selected_prompt is not None
  assert res3.selected_prompt.name == "turn_on_device"

  res4 = await router.route(make_route_context("Turn off the kitchen plug"))
  assert res4 is not None
  assert res4.service == Service.OREMI_ISAKOSO
  assert res4.selected_prompt is not None
  assert res4.selected_prompt.name == "turn_off_device"


@pytest.mark.asyncio
async def test_spacy_router_categorizes_scheduling_queries():
  router = SpacyRouter()

  res1 = await router.route(make_route_context("Rappelle-moi de sortir les poubelles à 20h"))
  assert res1 is not None
  assert res1.service == Service.OREMI_ISINMI

  res2 = await router.route(make_route_context("Mets une alarme pour 7h demain"))
  assert res2 is not None
  assert res2.service == Service.OREMI_ISINMI

  res3 = await router.route(make_route_context("Set a timer for 10 minutes"))
  assert res3 is not None
  assert res3.service == Service.OREMI_ISINMI


@pytest.mark.asyncio
async def test_spacy_router_categorizes_radio_and_podcast():
  router = SpacyRouter()

  res1 = await router.route(make_route_context("Écouter la radio France Inter"))
  assert res1 is not None
  assert res1.service == Service.OREMI_REDIYO

  res2 = await router.route(make_route_context("Mets le dernier épisode du podcast"))
  assert res2 is not None
  assert res2.service == Service.OREMI_KANSA


@pytest.mark.asyncio
async def test_spacy_router_selects_rediyo_prompt_when_available():
  router = SpacyRouter()
  context = make_route_context("Play BBC Radio 1 Dance")
  context.all_prompts = [
    t.Prompt(name="play_radio", description="Play a radio station", arguments=[]),
    t.Prompt(name="summarize_directory", description="Summarize radio directory stats", arguments=[]),
    t.Prompt(name="explore_by_genre", description="Explore stations by genre", arguments=[]),
  ]

  res = await router.route(context)

  assert res is not None
  assert res.service == Service.OREMI_REDIYO
  assert res.selected_prompt is not None
  assert res.selected_prompt.name == "play_radio"


@pytest.mark.asyncio
async def test_spacy_router_categorizes_time_queries():
  router = SpacyRouter()

  res1 = await router.route(make_route_context("Quelle heure est-il ?"))
  assert res1 is not None
  assert res1.service == Service.CHAT

  res2 = await router.route(make_route_context("What time is it right now?"))
  assert res2 is not None
  assert res2.service == Service.CHAT


@pytest.mark.asyncio
async def test_spacy_router_fallback_returns_none_for_unmatched_text():
  router = SpacyRouter()

  res = await router.route(make_route_context("Pourquoi le ciel est bleu ? Explique-moi."))
  assert res is None
