import logging

import httpx
import pytest
from pydantic import ValidationError

from oremi_akorin.core.settings import Settings
from oremi_akorin.core.app import create_app
from oremi_akorin.core.app import log_startup_settings


def isolated_settings(**overrides) -> Settings:
  values = {
    "OLLAMA_PULL_MODEL": False,
    "ISINMI_URL": None,
    "WEATHER_URL": None,
    "REDIYO_URL": None,
    "KANSA_URL": None,
    "MQTT_BROKER": None,
  }
  values.update(overrides)
  return Settings(**values)


def ollama_handler(request: httpx.Request) -> httpx.Response:
  if request.url.path == "/api/tags":
    return httpx.Response(200, json={"models": [{"name": "qwen2.5:3b"}]})
  if request.url.path == "/api/generate":
    return httpx.Response(200, json={"response": '{"service":"weather","confidence":0.95}'})
  if request.url.path == "/api/server":
    return httpx.Response(200, json={"name": "oremi-weather", "version": "1.2.3"})
  if request.url.path.endswith("/climate"):
    return httpx.Response(200, json={"message": "22°C and sunny", "temperature": 22})
  return httpx.Response(200, json={"message": "ok"})


def test_component_settings_accept_only_base_urls():
  with pytest.raises(ValidationError, match="component URL must be a base URL"):
    isolated_settings(WEATHER_URL="http://weather.test/api/agent/climate")


@pytest.mark.asyncio
async def test_process_endpoint():
  service_client = httpx.AsyncClient(transport=httpx.MockTransport(ollama_handler))
  app = create_app(isolated_settings(WEATHER_URL="http://weather.test"), service_client)
  async with app.router.lifespan_context(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
      response = await client.post("/api/process", json={"text": "Weather in Paris", "language": "en"})
  assert response.status_code == 200
  assert response.json()["service"] == "weather"
  assert response.json()["message"] == "22°C and sunny"


@pytest.mark.asyncio
async def test_validation_rejects_blank_input():
  service_client = httpx.AsyncClient(transport=httpx.MockTransport(ollama_handler))
  app = create_app(isolated_settings(), service_client)
  async with app.router.lifespan_context(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
      response = await client.post("/api/process", json={"text": "  "})
  assert response.status_code == 422


def test_process_openapi_documentation_describes_contract():
  app = create_app(isolated_settings())
  operation = app.openapi()["paths"]["/api/process"]["post"]

  assert operation["summary"] == "Process a natural-language request"
  assert "HTTP 200" in operation["description"]
  request_examples = operation["requestBody"]["content"]["application/json"]["examples"]

  assert {
    "weather",
    "reminder",
    "weather_alert",
    "zigbee",
  } <= set(request_examples)
  assert all({"summary", "description", "value"} <= set(example) for example in request_examples.values())
  assert set(operation["responses"]) == {"200", "422", "500"}
  assert set(operation["responses"]["200"]["content"]["application/json"]["examples"]) == {
    "weather",
    "tool",
    "more_information_required",
  }


@pytest.mark.asyncio
async def test_startup_and_shutdown_emit_operational_logs(caplog):
  service_client = httpx.AsyncClient(transport=httpx.MockTransport(ollama_handler))
  app = create_app(isolated_settings(), service_client)

  with caplog.at_level(logging.INFO, logger="oremi-akorin"):
    async with app.router.lifespan_context(app):
      pass

  messages = [record.getMessage() for record in caplog.records]
  assert any(message.startswith("Starting Oremi Akọrin ") for message in messages)
  assert any("App settings [server]:" in message for message in messages)
  assert any("App settings [ollama]:" in message for message in messages)
  assert any("App settings [generation]:" in message for message in messages)
  assert any("App settings [components]:" in message for message in messages)
  assert any("App settings [mqtt]:" in message for message in messages)
  assert any("App settings [mqtt topics]:" in message for message in messages)
  assert any("App settings [search]:" in message for message in messages)
  assert any("App settings [logging]:" in message for message in messages)
  assert any("Services configured:" in message for message in messages)
  assert any("Oremi Akọrin ready:" in message for message in messages)
  assert any("Oremi Akọrin stopped:" in message for message in messages)


def test_startup_settings_do_not_log_credentials_or_url_queries(caplog):
  settings = isolated_settings(
    OLLAMA_BASEURL="http://ollama-user:ollama-secret@ollama.test:11434/?token=secret-token",
    MQTT_USERNAME="mqtt-user",
    MQTT_PASSWORD="mqtt-secret",
  )

  with caplog.at_level(logging.INFO, logger="oremi-akorin"):
    log_startup_settings(settings)

  output = "\n".join(record.getMessage() for record in caplog.records)
  assert "ollama-secret" not in output
  assert "secret-token" not in output
  assert "mqtt-user" not in output
  assert "mqtt-secret" not in output
  assert "authentication_configured=True" in output


@pytest.mark.asyncio
async def test_startup_fails_when_a_configured_component_is_unreachable():
  def unreachable_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/tags":
      return httpx.Response(200, json={"models": [{"name": "qwen2.5:3b"}]})
    raise httpx.ConnectError("connection refused")

  service_client = httpx.AsyncClient(transport=httpx.MockTransport(unreachable_handler))
  app = create_app(
    isolated_settings(WEATHER_URL="http://weather.test"),
    service_client,
  )

  with pytest.raises(RuntimeError, match="Configured components are unreachable: weather"):
    async with app.router.lifespan_context(app):
      pass


@pytest.mark.asyncio
async def test_startup_rejects_invalid_component_service_info():
  def invalid_info_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/server":
      return httpx.Response(200, json={"name": "oremi-weather"})
    return httpx.Response(200, json={"models": []})

  service_client = httpx.AsyncClient(transport=httpx.MockTransport(invalid_info_handler))
  app = create_app(
    isolated_settings(WEATHER_URL="http://weather.test"),
    service_client,
  )

  with pytest.raises(RuntimeError, match="Configured components are unreachable: weather"):
    async with app.router.lifespan_context(app):
      pass
