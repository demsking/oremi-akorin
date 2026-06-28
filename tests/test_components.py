import json

import httpx
import pytest

from oremi_akorin.components.isinmi import IsinmiClient
from oremi_akorin.components.kansa import KansaClient
from oremi_akorin.components.rediyo import RediyoClient
from oremi_akorin.components.weather import WeatherAlertsClient
from oremi_akorin.components.weather import WeatherClient
from oremi_akorin.components.zigbee import DEVICES_TOPIC
from oremi_akorin.components.zigbee import ORIGINAL_TEXT_CONTEXT_KEY
from oremi_akorin.components.zigbee import ZigbeeComponent
from oremi_akorin.core.constants import Service


class FakeMQTTService:
  def __init__(self):
    self.client = None
    self.handlers = {}

  def subscribe(self, topic, handler):
    self.handlers[topic] = handler

  def unsubscribe(self, topic):
    self.handlers.pop(topic, None)


class FakeZigbeeClient:
  def __init__(self):
    self.published = []

  def is_connected(self):
    return True

  def publish(self, topic, payload):
    self.published.append((topic, payload))
    return type("PublishInfo", (), {"rc": 0})()


@pytest.mark.asyncio
async def test_isinmi_uses_natural_language_request_contract():
  captured = None

  def handler(request: httpx.Request) -> httpx.Response:
    nonlocal captured
    captured = request
    return httpx.Response(201, json={"message": "Rappel créé.", "action": "create"})

  async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
    component = IsinmiClient(Service.ISINMI, "http://isinmi.test", client)
    message, data = await component.process(
      "Rappelle-moi la réunion demain",
      "fr",
      {"timezone": "Europe/Paris"},
      {"user": "user-id", "device": "device-id"},
    )

  assert captured is not None
  assert captured.method == "POST"
  assert captured.url.path == "/api/agent/message"
  assert captured.url.params["language"] == "fr"
  assert json.loads(captured.content) == {
    "text": 'Rappelle-moi la réunion demain\n\nContext: {"timezone":"Europe/Paris"}',
    "timezone": "Europe/Paris",
    "tags": ["user:user-id", "device:device-id"],
  }
  assert message == "Rappel créé."
  assert data["action"] == "create"


@pytest.mark.asyncio
async def test_weather_uses_climate_query_contract():
  captured = None

  def handler(request: httpx.Request) -> httpx.Response:
    nonlocal captured
    captured = request
    return httpx.Response(200, json={"message": "Il fait beau.", "provider": "Open-Météo"})

  async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
    component = WeatherClient(Service.WEATHER, "http://weather.test", client)
    message, _ = await component.process(
      "Quel temps fait-il à Paris ?",
      "fr",
      {"timezone": "Europe/Paris", "temperature_unit": "fahrenheit"},
      {},
    )

  assert captured is not None
  assert captured.method == "GET"
  assert captured.url.path == "/api/agent/climate"
  assert dict(captured.url.params) == {
    "q": 'Quel temps fait-il à Paris ?\n\nContext: {"temperature_unit":"fahrenheit","timezone":"Europe/Paris"}',
    "timezone": "Europe/Paris",
    "temperature-unit": "fahrenheit",
  }
  assert message == "Il fait beau."


@pytest.mark.asyncio
@pytest.mark.parametrize("first_failure", ["connection", "status"])
async def test_component_retries_transient_unavailability(first_failure):
  attempts = 0

  def handler(request: httpx.Request) -> httpx.Response:
    nonlocal attempts
    attempts += 1
    if attempts == 1 and first_failure == "connection":
      raise httpx.ConnectError("connection refused")
    if attempts == 1:
      return httpx.Response(503, json={"detail": "temporarily unavailable"})
    return httpx.Response(200, json={"message": "Sunny"})

  async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
    component = WeatherClient(Service.WEATHER, "http://weather.test", client)
    message, _ = await component.process("Weather in Paris", "en", {}, {})

  assert attempts == 2
  assert message == "Sunny"


@pytest.mark.asyncio
async def test_weather_alerts_uses_alert_query_contract():
  captured = None

  def handler(request: httpx.Request) -> httpx.Response:
    nonlocal captured
    captured = request
    return httpx.Response(200, json={"message": "Air quality alert."})

  async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
    component = WeatherAlertsClient(Service.WEATHER_ALERTS, "http://weather.test", client)
    await component.process(
      "Are there air quality alerts?",
      "en",
      {"alert_service": "air-quality", "lat": 48.85, "lon": 2.35, "timezone": "Europe/Paris"},
      {},
    )

  assert captured is not None
  assert captured.method == "GET"
  assert captured.url.path == "/api/agent/alerts"
  assert dict(captured.url.params) == {
    "service": "air-quality",
    "lat": "48.85",
    "lon": "2.35",
    "timezone": "Europe/Paris",
    "language": "en",
    "temperature-unit": "celsius",
  }


@pytest.mark.asyncio
@pytest.mark.parametrize(
  ("component_type", "name", "url"),
  [
    (RediyoClient, "rediyo", "http://rediyo.test"),
    (KansaClient, "kansa", "http://kansa.test"),
  ],
)
async def test_media_components_use_ask_query_contract(component_type, name, url):
  captured = None

  def handler(request: httpx.Request) -> httpx.Response:
    nonlocal captured
    captured = request
    return httpx.Response(200, json={"message": "Voici une recommandation."})

  async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
    component = component_type(name, url, client)
    await component.process("Trouve quelque chose", "fr", {"device": "kitchen", "profile": {"age": 8}}, {})

  assert captured is not None
  assert captured.method == "GET"
  assert captured.url.path == "/api/ask"
  assert dict(captured.url.params) == {
    "query": 'Trouve quelque chose\n\nContext: {"device":"kitchen","profile":{"age":8}}',
    "language": "fr",
  }


@pytest.mark.asyncio
async def test_zigbee_translates_device_names_but_preserves_bridge_names(caplog):
  mqtt_service = FakeMQTTService()

  async def translate_name(name):
    return {"Lampe du salon": "Living Room Lamp"}.get(name, name)

  component = ZigbeeComponent(mqtt_service, translate_name)  # type: ignore[arg-type]

  component.start()
  with caplog.at_level("INFO", logger="oremi-akorin"):
    await mqtt_service.handlers[DEVICES_TOPIC](
      json.dumps(
        [
          {"type": "Coordinator", "friendly_name": "Coordinator"},
          {"type": "Router", "friendly_name": "Lampe du salon", "ieee_address": "0x123"},
        ]
      ).encode()
    )

  assert list(component.devices) == ["Living Room Lamp"]
  assert component._resolve_device("Living Room Lamp") == ("Lampe du salon", "Living Room Lamp")
  assert component._resolve_device("Lampe du salon") == ("Lampe du salon", "Living Room Lamp")
  assert any(
    "Zigbee device found: bridge_name='Lampe du salon' english_name='Living Room Lamp' ieee_address='0x123'"
    in record.getMessage()
    for record in caplog.records
  )

  await mqtt_service.handlers[DEVICES_TOPIC](
    json.dumps(
      [
        {"type": "EndDevice", "friendly_name": "Thermostat", "ieee_address": "0x456"},
      ]
    ).encode()
  )

  assert list(component.devices) == ["Thermostat"]

  component.stop()
  assert DEVICES_TOPIC not in mqtt_service.handlers


@pytest.mark.asyncio
async def test_zigbee_extracts_device_and_state_from_natural_language():
  mqtt_service = FakeMQTTService()
  mqtt_service.client = FakeZigbeeClient()
  component = ZigbeeComponent(mqtt_service)  # type: ignore[arg-type]
  component.devices = {
    "Lumière de la chambre": {
      "friendly_name": "Lumière de la chambre",
      "ieee_address": "0xa4c1385960a05c86",
    },
    "Bedroom switch": {
      "friendly_name": "Interrupteur de la chambre",
      "ieee_address": "0xa4c13846a1d3578c",
    },
  }

  message, data = await component.process(
    "light up the bedroom light",
    "en",
    {ORIGINAL_TEXT_CONTEXT_KEY: "allume la lumiere de la chambre"},
    {},
  )

  assert message == "Command sent to Lumière de la chambre."
  assert data == {"device": "Lumière de la chambre", "command": {"state": "ON"}}
  assert mqtt_service.client.published == [
    ("zigbee2mqtt/Lumière de la chambre/set", '{"state": "ON"}'),
  ]


@pytest.mark.asyncio
async def test_zigbee_uses_context_when_extracting_natural_language_command():
  mqtt_service = FakeMQTTService()
  mqtt_service.client = FakeZigbeeClient()
  component = ZigbeeComponent(mqtt_service)  # type: ignore[arg-type]
  component.devices = {
    "Bedroom switch": {
      "friendly_name": "Interrupteur de la chambre",
      "ieee_address": "0xa4c13846a1d3578c",
    },
    "Kitchen switch": {
      "friendly_name": "Interrupteur de la cuisine",
      "ieee_address": "0xa4c13846a1d3578d",
    },
  }

  message, data = await component.process(
    "turn on the switch",
    "en",
    {"room": "bedroom"},
    {},
  )

  assert message == "Command sent to Bedroom switch."
  assert data == {"device": "Bedroom switch", "command": {"state": "ON"}}
  assert mqtt_service.client.published == [
    ("zigbee2mqtt/Interrupteur de la chambre/set", '{"state": "ON"}'),
  ]
