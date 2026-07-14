import asyncio

import httpx
import pytest

from akorin.components.base import ComponentClient
from akorin.core.constants import Service
from akorin.core.exceptions import ComponentUnavailable
from akorin.core.settings import Settings
from akorin.llm.agent import AgentClient
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


class CachedComponent(ComponentClient):
  endpoint_path = "/api/ask"


@pytest.mark.asyncio
async def test_smart_cache_reuses_internal_llm_calls():
  cache = SmartCache(enabled=True, max_entries=10)
  settings = Settings(llm_model="test", llm_cache_ttl_seconds=60)
  client = httpx.AsyncClient()
  agent = CachedAgent(settings, client, cache)

  try:
    first = await agent._run("same prompt")
    second = await agent._run("same prompt")
    third = await agent._run("different prompt")
  finally:
    await client.aclose()

  assert first == "same prompt:1"
  assert second == "same prompt:1"
  assert third == "different prompt:2"
  assert agent.agent.calls == 2


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


@pytest.mark.asyncio
async def test_component_get_requests_are_cached_by_stable_request_inputs():
  calls = 0

  async def handler(request):
    nonlocal calls
    calls += 1

    return httpx.Response(200, json={"message": f"response {calls}"})

  cache = SmartCache(enabled=True, max_entries=10)
  client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://service.example")
  component = CachedComponent(Service.OREMI_OJO, "https://service.example", client, cache, cache_ttl_seconds=60)

  try:
    first = await component.request_json("GET", params={"q": "weather in Paris"})
    second = await component.request_json("GET", params={"q": "weather in Paris"})
    third = await component.request_json("GET", params={"q": "weather in London"})
  finally:
    await client.aclose()

  assert first == {"message": "response 1"}
  assert second == {"message": "response 1"}
  assert third == {"message": "response 2"}
  assert calls == 2


@pytest.mark.asyncio
async def test_component_cache_bypasses_volatile_context_inputs():
  calls = 0

  async def handler(request):
    nonlocal calls
    calls += 1

    return httpx.Response(200, json={"message": f"response {calls}"})

  cache = SmartCache(enabled=True, max_entries=10)
  client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://service.example")
  component = CachedComponent(Service.OREMI_OJO, "https://service.example", client, cache, cache_ttl_seconds=60)

  try:
    first = await component.request_json("GET", params={"context": {"datetime": "2026-07-10T12:00:00+02:00"}})
    second = await component.request_json("GET", params={"context": {"datetime": "2026-07-10T12:00:00+02:00"}})
  finally:
    await client.aclose()

  assert first == {"message": "response 1"}
  assert second == {"message": "response 2"}
  assert calls == 2


@pytest.mark.asyncio
async def test_component_cache_bypasses_serialized_volatile_context_inputs():
  calls = 0

  async def handler(request):
    nonlocal calls
    calls += 1

    return httpx.Response(200, json={"message": f"response {calls}"})

  cache = SmartCache(enabled=True, max_entries=10)
  client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://service.example")
  component = CachedComponent(Service.OREMI_OJO, "https://service.example", client, cache, cache_ttl_seconds=60)

  try:
    params = {
      "q": 'Quel temps fait-il ici ?\n\nContext: {"datetime":"2026-07-10T12:00:00+02:00"}',
    }
    first = await component.request_json("GET", params=params)
    second = await component.request_json("GET", params=params)
  finally:
    await client.aclose()

  assert first == {"message": "response 1"}
  assert second == {"message": "response 2"}
  assert calls == 2


@pytest.mark.asyncio
async def test_component_circuit_breaker_fails_fast_after_repeated_errors():
  calls = 0

  async def handler(request):
    nonlocal calls
    calls += 1

    return httpx.Response(503, json={"detail": "offline"})

  client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://service.example")
  component = CachedComponent(
    Service.OREMI_OJO,
    "https://service.example",
    client,
    circuit_breaker_enabled=True,
    circuit_breaker_failures=2,
    circuit_breaker_cooldown_seconds=60,
  )

  try:
    with pytest.raises(ComponentUnavailable):
      await component.request_json("GET", params={"q": "weather"})

    with pytest.raises(ComponentUnavailable):
      await component.request_json("GET", params={"q": "weather"})

    with pytest.raises(ComponentUnavailable, match="circuit breaker open"):
      await component.request_json("GET", params={"q": "weather"})
  finally:
    await client.aclose()

  assert calls == 6
