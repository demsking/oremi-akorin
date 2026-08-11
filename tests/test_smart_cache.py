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
from unittest.mock import AsyncMock

import httpx2
import pytest

from akorin.core.agent import AgentClient
from akorin.core.components import ComponentClient
from akorin.core.exceptions import ComponentUnavailable
from akorin.core.service import Service
from akorin.utils.cache import SmartCache


class DummyResult:
  def __init__(self, output):
    self.output = output


class DummyAgent:
  def __init__(self):
    self.calls = 0

  async def run(self, prompt):
    self.calls += 1

    return DummyResult(f"{prompt}:{self.calls}")


class CachedAgent(AgentClient[str]):
  def _create_agent(self):
    return DummyAgent()


class ParsedCachedAgent(CachedAgent):
  def _parse_output(self, output):
    if output == "bad":
      raise ValueError("invalid generated output")

    return output


class CachedComponent(ComponentClient):
  endpoint_path = "/api/ask"


@pytest.mark.asyncio
async def test_smart_cache_singleflights_concurrent_misses():
  calls = 0

  async def factory():
    nonlocal calls
    calls += 1
    await asyncio.sleep(0.01)

    return {"value": calls}

  cache = SmartCache(enabled=True, max_entries=10)
  results = await asyncio.gather(
    cache.get_or_set("same-key", 60, factory),
    cache.get_or_set("same-key", 60, factory),
  )

  assert results == [{"value": 1}, {"value": 1}]
  assert calls == 1
  assert cache.stats.singleflight_waits == 1


@pytest.mark.asyncio
async def test_smart_cache_serves_stale_value_while_refreshing():
  now = 0.0
  calls = 0

  def clock():
    return now

  async def factory():
    nonlocal calls
    calls += 1

    return {"value": calls}

  cache = SmartCache(enabled=True, max_entries=10, clock=clock)

  assert await cache.get_or_set_stale("key", 1, 10, factory) == {"value": 1}
  now = 2.0
  assert await cache.get_or_set_stale("key", 1, 10, factory) == {"value": 1}

  await asyncio.sleep(0.01)

  assert calls == 2
  assert cache.stats.stale_hits == 1
  assert cache.stats.refreshes == 1


class MockCachedComponent(ComponentClient):
  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._mock_session = AsyncMock()
    self._session = None

  async def connect(self):
    self._raise_if_circuit_open()
    if hasattr(self, "_connect_exception"):
      self._record_failure()
      raise self._connect_exception
    self._session = self._mock_session


@pytest.mark.asyncio
async def test_component_get_requests_are_cached_by_stable_request_inputs():
  cache = SmartCache(enabled=True, max_entries=10)
  component = MockCachedComponent(
    Service.OREMI_OJO, "https://service.example", httpx2.AsyncClient(), cache, cache_ttl_seconds=60
  )

  component._mock_session.call_tool.side_effect = [
    {"message": "response 1"},
    {"message": "response 2"},
  ]

  first = await component.call_tool("get_weather", {"q": "weather in Paris"})
  second = await component.call_tool("get_weather", {"q": "weather in Paris"})
  third = await component.call_tool("get_weather", {"q": "weather in London"})

  assert first == {"message": "response 1"}
  assert second == {"message": "response 1"}
  assert third == {"message": "response 2"}
  assert component._mock_session.call_tool.call_count == 2


@pytest.mark.asyncio
async def test_component_cache_bypasses_volatile_context_inputs():
  cache = SmartCache(enabled=True, max_entries=10)
  component = MockCachedComponent(
    Service.OREMI_OJO, "https://service.example", httpx2.AsyncClient(), cache, cache_ttl_seconds=60
  )

  component._mock_session.call_tool.side_effect = [
    {"message": "response 1"},
    {"message": "response 2"},
  ]

  first = await component.call_tool("get_weather", {"context": {"datetime": "2026-07-10T12:00:00+02:00"}})
  second = await component.call_tool("get_weather", {"context": {"datetime": "2026-07-10T12:00:00+02:00"}})

  assert first == {"message": "response 1"}
  assert second == {"message": "response 2"}
  assert component._mock_session.call_tool.call_count == 2


@pytest.mark.asyncio
async def test_component_cache_bypasses_serialized_volatile_context_inputs():
  cache = SmartCache(enabled=True, max_entries=10)
  component = MockCachedComponent(
    Service.OREMI_OJO, "https://service.example", httpx2.AsyncClient(), cache, cache_ttl_seconds=60
  )

  component._mock_session.call_tool.side_effect = [
    {"message": "response 1"},
    {"message": "response 2"},
  ]

  params = {
    "q": 'Quel temps fait-il ici ?\n\nContext: {"datetime":"2026-07-10T12:00:00+02:00"}',
  }
  first = await component.call_tool("get_weather", params)
  second = await component.call_tool("get_weather", params)

  assert first == {"message": "response 1"}
  assert second == {"message": "response 2"}
  assert component._mock_session.call_tool.call_count == 2


@pytest.mark.asyncio
async def test_component_circuit_breaker_fails_fast_after_repeated_errors():
  cache = SmartCache(enabled=False, max_entries=10)
  component = MockCachedComponent(
    Service.OREMI_OJO,
    "https://service.example",
    httpx2.AsyncClient(),
    cache,
    circuit_breaker_enabled=True,
    circuit_breaker_failures=2,
    circuit_breaker_cooldown_seconds=60,
  )

  component._connect_exception = ComponentUnavailable(Service.OREMI_OJO, "offline")

  with pytest.raises(ComponentUnavailable):
    await component.call_tool("get_weather", {"q": "weather"})

  with pytest.raises(ComponentUnavailable):
    await component.call_tool("get_weather", {"q": "weather"})

  with pytest.raises(ComponentUnavailable, match="circuit breaker open"):
    await component.call_tool("get_weather", {"q": "weather"})
