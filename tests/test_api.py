import logging

import httpx
import pytest
from pydantic import ValidationError

from akorin.core.settings import Settings
from akorin.core.app import create_app


def isolated_settings(**overrides) -> Settings:
  values = {
    "llm_model": "test",
    "ollama_base_url": None,
    "isinmi_url": None,
    "ojo_url": None,
    "rediyo_url": None,
    "kansa_url": None,
    "mqtt_broker": None,
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
  if request.url.path == "/api/agent/chat":
    return httpx.Response(200, json={"message": "22°C and sunny", "data": {"temperature": 22}})
  return httpx.Response(200, json={"message": "ok"})


def test_component_settings_accept_only_base_urls():
  with pytest.raises(ValidationError, match="component URL must be a base URL"):
    isolated_settings(ojo_url="http://weather.test/api/agent/climate")


@pytest.mark.asyncio
async def test_process_endpoint():
  service_client = httpx.AsyncClient(transport=httpx.MockTransport(ollama_handler))
  app = create_app(isolated_settings(ojo_url="http://weather.test"), service_client)
  async with app.router.lifespan_context(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
      response = await client.post(
        "/api/agent/",
        json={"text": "Weather in Paris", "language": "en", "context": {"route_to": "ojo"}},
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
  def invalid_info_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/server":
      return httpx.Response(200, json={"name": "oremi-weather"})
    return httpx.Response(200, json={"models": []})

  service_client = httpx.AsyncClient(transport=httpx.MockTransport(invalid_info_handler))
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
