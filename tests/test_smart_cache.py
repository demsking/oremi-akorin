import httpx
import pytest

from akorin.components.base import ComponentClient
from akorin.core.constants import Service
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
  settings = Settings(llm_model="test", smart_cache_llm_ttl_seconds=60)
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
async def test_component_get_requests_are_cached_by_stable_request_inputs():
  calls = 0

  async def handler(request):
    nonlocal calls
    calls += 1

    return httpx.Response(200, json={"message": f"response {calls}"})

  cache = SmartCache(enabled=True, max_entries=10)
  client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://service.example")
  component = CachedComponent(Service.WEATHER, "https://service.example", client, cache, cache_ttl_seconds=60)

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
  component = CachedComponent(Service.WEATHER, "https://service.example", client, cache, cache_ttl_seconds=60)

  try:
    first = await component.request_json("GET", params={"context": {"datetime": "2026-07-10T12:00:00+02:00"}})
    second = await component.request_json("GET", params={"context": {"datetime": "2026-07-10T12:00:00+02:00"}})
  finally:
    await client.aclose()

  assert first == {"message": "response 1"}
  assert second == {"message": "response 2"}
  assert calls == 2
