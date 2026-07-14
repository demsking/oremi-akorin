import json
import asyncio
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from akorin.components.isinmi import IsinmiClient
from akorin.components.kansa import KansaClient
from akorin.components.rediyo import RediyoClient
from akorin.components.ojo import OjoClient
from akorin.components.base import monitor_unavailable_components
from akorin.components.zigbee import DEVICES_TOPIC
from akorin.components.zigbee import ORIGINAL_TEXT_CONTEXT_KEY
from akorin.components.zigbee import ZigbeeComponent
from akorin.core.constants import Service
from akorin.core.oremi import OremiServerHealth


class FakeMQTTService:
  def __init__(self):
    self.client: Any = None
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


def light_device(friendly_name: str) -> dict[str, Any]:
  return {
    "friendly_name": friendly_name,
    "ieee_address": "0xa4c1385960a05c86",
    "definition": {
      "manufacturer": "Test",
      "model": "TS0505B",
      "exposes": light_exposes(),
    },
  }


def light_exposes() -> list[dict[str, Any]]:
  return [
    {
      "type": "light",
      "features": [
        {
          "type": "binary",
          "property": "state",
          "access": 7,
          "value_on": "ON",
          "value_off": "OFF",
          "description": "Turn the light on or off.",
        },
        {
          "type": "numeric",
          "property": "brightness",
          "access": 7,
          "value_min": 0,
          "value_max": 254,
          "description": "Brightness level.",
        },
      ],
    },
  ]


def thermometer_device(friendly_name: str) -> dict[str, Any]:
  return {
    "friendly_name": friendly_name,
    "ieee_address": "0xa4c138edee4b9c12",
    "definition": {
      "manufacturer": "Test",
      "model": "TS0601",
      "exposes": [
        {
          "type": "numeric",
          "property": "temperature",
          "access": 1,
          "unit": "°C",
          "description": "Measured temperature.",
        },
        {
          "type": "numeric",
          "property": "humidity",
          "access": 1,
          "unit": "%",
          "description": "Measured humidity.",
        },
      ],
    },
  }


def configure_zigbee_devices(component: ZigbeeComponent, devices: dict[str, dict[str, Any]]) -> None:
  component.devices = devices
  component.operations = {name: component._extract_operations(device) for name, device in devices.items()}
  component.states = {name: component._extract_states(device) for name, device in devices.items()}
  component.device_states = {name: {} for name in devices}


def generated_zigbee_response(event: str, language: str, details: dict[str, Any]) -> str:
  return f"{event}:{language}:{json.dumps(details, ensure_ascii=False, sort_keys=True)}"


async def zigbee_response(event: str, language: str, details: dict[str, Any]) -> str:
  return generated_zigbee_response(event, language, details)


@pytest.mark.asyncio
async def test_isinmi_uses_natural_language_request_contract():
  captured = None

  def handler(request: httpx.Request) -> httpx.Response:
    nonlocal captured
    captured = request
    return httpx.Response(201, json={"response_message": "Rappel créé.", "data": {"action": "create"}})

  async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
    component = IsinmiClient(Service.OREMI_ISINMI, "http://isinmi.test", client)
    message, data = await component.process(
      "Rappelle-moi la réunion demain",
      "fr",
      {"timezone": "Europe/Paris"},
      ["user-id", "device-id"],
    )

  assert captured is not None
  assert captured.method == "POST"
  assert captured.url.path == "/api/agent/chat"
  assert json.loads(captured.content) == {
    "message": "Rappelle-moi la réunion demain",
    "context": {"timezone": "Europe/Paris"},
    "tags": ["user-id", "device-id"],
  }
  assert message == "Rappel créé."
  assert data == {"action": "create"}


@pytest.mark.asyncio
async def test_isinmi_service_info_uses_richer_health_model():
  captured = None

  def handler(request: httpx.Request) -> httpx.Response:
    nonlocal captured
    captured = request
    return httpx.Response(
      200,
      json={
        "status": "healthy",
        "app": "isinmi",
        "version": "1.4.0",
        "llm_model": "ollama:qwen3.5:2b",
      },
    )

  async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
    component = IsinmiClient(Service.OREMI_ISINMI, "http://isinmi.test", client)
    info = await component.get_service_info()

  assert captured is not None
  assert captured.url.path == "/health/"
  assert isinstance(info, OremiServerHealth)
  assert info.status == "healthy"
  assert info.app == "isinmi"
  assert info.version == "1.4.0"
  assert info.llm_model == "ollama:qwen3.5:2b"


@pytest.mark.asyncio
async def test_weather_uses_climate_query_contract():
  captured = None

  def handler(request: httpx.Request) -> httpx.Response:
    nonlocal captured
    captured = request
    return httpx.Response(200, json={"message": "Il fait beau.", "provider": "Open-Météo"})

  async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
    component = OjoClient(Service.OREMI_OJO, "http://weather.test", client)
    message, _ = await component.process(
      "Quel temps fait-il à Paris ?",
      "fr",
      {"timezone": "Africa/Douala", "temperature_unit": "fahrenheit"},
      [],
    )

  assert captured is not None
  assert captured.method == "POST"
  assert captured.url.path == "/api/agent/chat"
  assert json.loads(captured.content) == {
    "message": "Quel temps fait-il à Paris ?",
    "context": {"timezone": "Africa/Douala", "temperature_unit": "fahrenheit"},
    "tags": [],
  }
  assert message == "Il fait beau."


@pytest.mark.asyncio
async def test_weather_context_location_overrides_local_request_after_rewrite():
  captured = None

  def handler(request: httpx.Request) -> httpx.Response:
    nonlocal captured
    captured = request
    return httpx.Response(200, json={"message": "Il fait beau à Douala.", "provider": "Open-Météo"})

  async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
    component = OjoClient(Service.OREMI_OJO, "http://weather.test", client)
    message, _ = await component.process(
      "Quelle est la température à Paris aujourd'hui ?",
      "fr",
      {
        "_oremi_original_text": "Quel temps fait-il ici ?",
        "location": "Deido, Douala, Cameroun",
        "timezone": "Africa/Douala",
        "temperature_unit": "celsius",
        "lat": 4.0637626,
        "lon": 9.7151827,
        "datetime": "2026-07-10T07:36:49.673555+02:00",
      },
      [],
    )

  assert captured is not None
  assert captured.url.path == "/api/agent/chat"
  assert json.loads(captured.content) == {
    "message": "Quelle est la température à Paris aujourd'hui ?",
    "context": {
      "_oremi_original_text": "Quel temps fait-il ici ?",
      "location": "Deido, Douala, Cameroun",
      "timezone": "Africa/Douala",
      "temperature_unit": "celsius",
      "lat": 4.0637626,
      "lon": 9.7151827,
      "datetime": "2026-07-10T07:36:49.673555+02:00",
    },
    "tags": [],
  }
  assert message == "Il fait beau à Douala."


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
    component = OjoClient(Service.OREMI_OJO, "http://weather.test", client)
    message, _ = await component.process("Weather in Paris", "en", {}, [])

  assert attempts == 2
  assert message == "Sunny"


@pytest.mark.asyncio
async def test_background_monitor_recovers_component_availability():
  class FlakyAvailabilityComponent:
    def __init__(self):
      self.calls = 0

    async def get_service_info(self):
      self.calls += 1
      if self.calls == 1:
        raise RuntimeError("offline")

      class Info(BaseModel):
        name: str
        version: str

      return Info(name="weather", version="1.0")

  component = FlakyAvailabilityComponent()
  statuses = {Service.OREMI_OJO: False}
  stop_event = asyncio.Event()

  task = asyncio.create_task(
    monitor_unavailable_components(
      {Service.OREMI_OJO: component},  # type: ignore[arg-type]
      statuses,
      stop_event=stop_event,
      interval_seconds=0.01,
    )
  )

  await asyncio.sleep(0.05)
  stop_event.set()
  await task

  assert statuses[Service.OREMI_OJO] is True


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
async def test_zigbee_discovers_devices_with_native_names_and_operations(caplog):
  mqtt_service = FakeMQTTService()
  component = ZigbeeComponent(mqtt_service)

  component.start()
  with caplog.at_level("INFO", logger="akorin.components.zigbee"):
    await mqtt_service.handlers[DEVICES_TOPIC](
      json.dumps(
        [
          {"type": "Coordinator", "friendly_name": "Coordinator"},
          light_device("Lampe du salon") | {"type": "Router", "ieee_address": "0x123"},
        ]
      ).encode()
    )

  assert list(component.devices) == ["Lampe du salon"]
  assert component._resolve_device("Lampe du salon") == ("Lampe du salon", "Lampe du salon")
  assert set(component.operations["Lampe du salon"]) == {"state", "brightness"}
  assert set(component.states["Lampe du salon"]) == {"state", "brightness"}
  assert "zigbee2mqtt/Lampe du salon" in mqtt_service.handlers
  assert any(
    "Zigbee device found: name='Lampe du salon' ieee_address='0x123' "
    "operations=['brightness', 'state'] states=['brightness', 'state']" == record.getMessage()
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
  assert "zigbee2mqtt/Lampe du salon" not in mqtt_service.handlers

  component.stop()
  assert DEVICES_TOPIC not in mqtt_service.handlers


def test_zigbee_extracts_operations_from_definition_exposes_and_inherited_access():
  component = ZigbeeComponent(FakeMQTTService())
  device = {
    "friendly_name": "Radiateur de la chambre",
    "definition": {
      "exposes": [
        {
          "type": "climate",
          "features": [
            {
              "type": "numeric",
              "property": "local_temperature",
              "access": 1,
              "description": "Current measured temperature.",
            },
            {
              "type": "numeric",
              "property": "current_heating_setpoint",
              "access": 7,
              "value_min": 5,
              "value_max": 30,
              "unit": "°C",
              "description": "Target temperature.",
            },
            {
              "type": "enum",
              "property": "system_mode",
              "access": 7,
              "values": ["off", "heat"],
            },
          ],
        },
        {
          "type": "light",
          "access": 7,
          "features": [
            {"type": "binary", "property": "state", "value_on": "ON", "value_off": "OFF"},
          ],
        },
      ],
    },
  }

  operations = component._extract_operations(device)

  assert set(operations) == {"current_heating_setpoint", "system_mode", "state"}
  assert operations["current_heating_setpoint"].value_min == 5
  assert operations["current_heating_setpoint"].value_max == 30
  assert operations["current_heating_setpoint"].unit == "°C"
  assert operations["system_mode"].values == ("off", "heat")
  assert operations["state"].value_on == "ON"


def test_zigbee_extracts_readable_states_from_definition_exposes_and_inherited_access():
  component = ZigbeeComponent(FakeMQTTService())
  device = {
    "friendly_name": "Radiateur de la chambre",
    "definition": {
      "exposes": [
        {
          "type": "climate",
          "features": [
            {
              "type": "numeric",
              "property": "local_temperature",
              "access": 1,
              "unit": "°C",
              "description": "Current measured temperature.",
            },
            {
              "type": "numeric",
              "property": "current_heating_setpoint",
              "access": 7,
              "unit": "°C",
              "description": "Target temperature.",
            },
          ],
        },
        {
          "type": "composite",
          "access": 1,
          "features": [
            {"type": "numeric", "property": "power", "unit": "W"},
          ],
        },
      ],
    },
  }

  states = component._extract_states(device)

  assert set(states) == {"local_temperature", "current_heating_setpoint", "power"}
  assert states["local_temperature"].unit == "°C"
  assert states["local_temperature"].description == "Current measured temperature."
  assert states["current_heating_setpoint"].unit == "°C"
  assert states["power"].unit == "W"


@pytest.mark.asyncio
async def test_zigbee_extracts_device_and_state_from_natural_language():
  mqtt_service = FakeMQTTService()
  mqtt_service.client = FakeZigbeeClient()
  calls = []

  async def select_command(texts, catalog):
    calls.append((texts, catalog))
    return {"device": "Lumière de la chambre", "payload": {"state": "ON"}, "confidence": 0.91}

  component = ZigbeeComponent(mqtt_service, command_selector=select_command, response_generator=zigbee_response)
  configure_zigbee_devices(
    component,
    {
      "Lumière de la chambre": light_device("Lumière de la chambre"),
      "Bedroom switch": {
        "friendly_name": "Interrupteur de la chambre",
        "ieee_address": "0xa4c13846a1d3578c",
        "exposes": [{"type": "binary", "property": "state", "access": 7, "value_on": "ON", "value_off": "OFF"}],
      },
    },
  )

  message, data = await component.process(
    "light up the bedroom light",
    "en",
    {ORIGINAL_TEXT_CONTEXT_KEY: "allume la lumiere de la chambre"},
    [],
  )

  assert message == generated_zigbee_response(
    "zigbee_command_sent",
    "en",
    {"device": "Lumière de la chambre", "command": {"state": "ON"}},
  )
  assert data == {"device": "Lumière de la chambre", "command": {"state": "ON"}}
  assert component.device_states["Lumière de la chambre"] == {"state": "ON"}
  assert mqtt_service.client.published == [
    ("zigbee2mqtt/Lumière de la chambre/set", '{"state": "ON"}'),
  ]
  assert calls[0][1][0]["operations"] == [
    {
      "property": "state",
      "type": "binary",
      "description": "Turn the light on or off.",
      "value_on": "ON",
      "value_off": "OFF",
    },
    {
      "property": "brightness",
      "type": "numeric",
      "description": "Brightness level.",
      "min": 0.0,
      "max": 254.0,
    },
  ]
  assert len(calls[0][1]) == 1


@pytest.mark.asyncio
async def test_zigbee_reuses_cached_command_decision_for_same_catalog():
  mqtt_service = FakeMQTTService()
  mqtt_service.client = FakeZigbeeClient()
  calls = 0

  async def select_command(texts, catalog):
    nonlocal calls
    calls += 1

    return {"device": "Lumière de la chambre", "payload": {"state": "ON"}, "confidence": 0.91}

  component = ZigbeeComponent(mqtt_service, command_selector=select_command, response_generator=zigbee_response)
  configure_zigbee_devices(component, {"Lumière de la chambre": light_device("Lumière de la chambre")})

  await component.process("allume la lumière de la chambre", "fr", {}, [])
  await component.process("allume la lumière de la chambre", "fr", {}, [])

  assert calls == 1
  assert mqtt_service.client.published == [
    ("zigbee2mqtt/Lumière de la chambre/set", '{"state": "ON"}'),
    ("zigbee2mqtt/Lumière de la chambre/set", '{"state": "ON"}'),
  ]


@pytest.mark.asyncio
async def test_zigbee_extracts_french_unaccented_off_command():
  mqtt_service = FakeMQTTService()
  mqtt_service.client = FakeZigbeeClient()

  async def select_command(texts, catalog):
    return {"device": "Lumière de la chambre", "payload": {"state": "OFF"}}

  component = ZigbeeComponent(mqtt_service, command_selector=select_command, response_generator=zigbee_response)
  configure_zigbee_devices(component, {"Lumière de la chambre": light_device("Lumière de la chambre")})

  message, data = await component.process("eteinds la lumière de la chambre", "fr", {}, [])

  assert message == generated_zigbee_response(
    "zigbee_command_sent",
    "fr",
    {"device": "Lumière de la chambre", "command": {"state": "OFF"}},
  )
  assert data == {"device": "Lumière de la chambre", "command": {"state": "OFF"}}
  assert mqtt_service.client.published == [
    ("zigbee2mqtt/Lumière de la chambre/set", '{"state": "OFF"}'),
  ]


@pytest.mark.asyncio
async def test_zigbee_narrows_catalog_before_llm_when_device_is_named():
  calls = []
  mqtt_service = FakeMQTTService()
  mqtt_service.client = FakeZigbeeClient()

  async def select_command(texts, catalog):
    calls.append(catalog)
    if len(catalog) == 1:
      return {"device": "Lumière de la chambre", "payload": {"state": "OFF"}}
    return {"device": None, "payload": {}, "confidence": 0}

  component = ZigbeeComponent(mqtt_service, command_selector=select_command, response_generator=zigbee_response)
  configure_zigbee_devices(
    component,
    {
      "Lumière de la chambre": light_device("Lumière de la chambre"),
      "Lumière du salon": light_device("Lumière du salon"),
      "Radiateur": {
        "friendly_name": "Radiateur",
        "definition": {
          "exposes": [{"type": "numeric", "property": "current_heating_setpoint", "access": 7, "value_min": 5, "value_max": 30}]
        },
      },
    },
  )

  message, data = await component.process("éteins la lumière de la chambre", "fr", {}, [])

  assert [device["name"] for device in calls[0]] == ["Lumière de la chambre"]
  assert message == generated_zigbee_response(
    "zigbee_command_sent",
    "fr",
    {"device": "Lumière de la chambre", "command": {"state": "OFF"}},
  )
  assert data == {"device": "Lumière de la chambre", "command": {"state": "OFF"}}
  assert mqtt_service.client.published == [
    ("zigbee2mqtt/Lumière de la chambre/set", '{"state": "OFF"}'),
  ]


@pytest.mark.asyncio
async def test_zigbee_uses_llm_command_selector_for_multilingual_operation_and_device_matching():
  calls = []
  mqtt_service = FakeMQTTService()
  mqtt_service.client = FakeZigbeeClient()

  async def select_command(texts, catalog):
    calls.append((texts, catalog))
    return {"device": "Bedroom light", "payload": {"brightness": 64, "state": "ON"}, "confidence": 0.88}

  component = ZigbeeComponent(mqtt_service, command_selector=select_command, response_generator=zigbee_response)
  configure_zigbee_devices(component, {"Bedroom light": light_device("Lumière de la chambre")})

  message, data = await component.process("allume doucement la lumière de la chambre", "fr", {}, [])

  assert calls[0][0] == ["allume doucement la lumière de la chambre"]
  assert calls[0][1][0]["name"] == "Bedroom light"
  assert calls[0][1][0]["mqtt_topic"] == "Lumière de la chambre"
  assert message == generated_zigbee_response(
    "zigbee_command_sent",
    "fr",
    {"device": "Bedroom light", "command": {"brightness": 64, "state": "ON"}},
  )
  assert data == {"device": "Bedroom light", "command": {"brightness": 64, "state": "ON"}}
  assert mqtt_service.client.published == [
    ("zigbee2mqtt/Lumière de la chambre/set", '{"brightness": 64, "state": "ON"}'),
  ]


def test_zigbee_fuzzy_matches_french_light_request_to_device_room_name():
  component = ZigbeeComponent(FakeMQTTService())
  configure_zigbee_devices(component, {"Bedroom lamp": light_device("Lampe chambre")})

  assert component._extract_device(["Allume la lumière de la chambre"]) == (
    "Lampe chambre",
    "Bedroom lamp",
    "fuzzy",
    1.0,
  )
  assert component._device_catalog_for("Bedroom lamp") == [
    {
      "name": "Bedroom lamp",
      "mqtt_topic": "Lampe chambre",
      "model": None,
      "manufacturer": None,
      "operations": [
        {
          "property": "state",
          "type": "binary",
          "description": "Turn the light on or off.",
          "value_on": "ON",
          "value_off": "OFF",
        },
        {
          "property": "brightness",
          "type": "numeric",
          "description": "Brightness level.",
          "min": 0.0,
          "max": 254.0,
        },
      ],
      "states": [
        {
          "property": "state",
          "type": "binary",
          "description": "Turn the light on or off.",
        },
        {
          "property": "brightness",
          "type": "numeric",
          "description": "Brightness level.",
        },
      ],
    }
  ]


@pytest.mark.asyncio
async def test_zigbee_uses_context_when_extracting_natural_language_command():
  mqtt_service = FakeMQTTService()
  mqtt_service.client = FakeZigbeeClient()

  async def select_command(texts, catalog):
    return {"device": "Bedroom switch", "payload": {"state": "ON"}}

  component = ZigbeeComponent(mqtt_service, command_selector=select_command, response_generator=zigbee_response)
  configure_zigbee_devices(
    component,
    {
      "Bedroom switch": {
        "friendly_name": "Interrupteur de la chambre",
        "ieee_address": "0xa4c13846a1d3578c",
        "exposes": [{"type": "binary", "property": "state", "access": 7, "value_on": "ON", "value_off": "OFF"}],
      },
      "Kitchen switch": {
        "friendly_name": "Interrupteur de la cuisine",
        "ieee_address": "0xa4c13846a1d3578d",
        "exposes": [{"type": "binary", "property": "state", "access": 7, "value_on": "ON", "value_off": "OFF"}],
      },
    },
  )

  message, data = await component.process(
    "turn on the switch",
    "en",
    {"room": "bedroom"},
    [],
  )

  assert message == generated_zigbee_response(
    "zigbee_command_sent",
    "en",
    {"device": "Bedroom switch", "command": {"state": "ON"}},
  )
  assert data == {"device": "Bedroom switch", "command": {"state": "ON"}}
  assert mqtt_service.client.published == [
    ("zigbee2mqtt/Interrupteur de la chambre/set", '{"state": "ON"}'),
  ]


@pytest.mark.asyncio
async def test_zigbee_rejects_llm_payload_not_exposed_by_device():
  mqtt_service = FakeMQTTService()
  mqtt_service.client = FakeZigbeeClient()

  async def select_command(texts, catalog):
    return {"device": "Bedroom switch", "payload": {"brightness": 80}}

  component = ZigbeeComponent(mqtt_service, command_selector=select_command, response_generator=zigbee_response)
  configure_zigbee_devices(
    component,
    {
      "Bedroom switch": {
        "friendly_name": "Interrupteur de la chambre",
        "ieee_address": "0xa4c13846a1d3578c",
        "exposes": [{"type": "binary", "property": "state", "access": 7, "value_on": "ON", "value_off": "OFF"}],
      },
    },
  )

  message, data = await component.process("mets la lumière à 80 pour cent", "fr", {}, [])

  assert message == generated_zigbee_response(
    "zigbee_missing_command",
    "fr",
    {"available_devices": ["Bedroom switch"], "reason": "missing_operation", "required": ["operation"]},
  )
  assert data == {"available_devices": ["Bedroom switch"], "reason": "missing_operation", "required": ["operation"]}
  assert mqtt_service.client.published == []


@pytest.mark.asyncio
async def test_zigbee_reports_requested_device_not_found_with_available_devices():
  mqtt_service = FakeMQTTService()
  mqtt_service.client = FakeZigbeeClient()

  async def select_command(texts, catalog):
    return {"device": None, "payload": {}, "confidence": 0}

  component = ZigbeeComponent(mqtt_service, command_selector=select_command, response_generator=zigbee_response)
  configure_zigbee_devices(component, {"Bedroom light": light_device("Lumière de la chambre")})

  message, data = await component.process("Turn on the living room lights and set brightness to 80%", "en", {}, [])

  expected = {
    "available_devices": ["Bedroom light"],
    "reason": "requested_device_not_found",
    "requested_device": "Turn on the living room lights and set brightness to 80%",
    "required": ["device", "operation"],
  }
  assert message == generated_zigbee_response("zigbee_missing_command", "en", expected)
  assert data == expected
  assert mqtt_service.client.published == []


@pytest.mark.asyncio
async def test_zigbee_reports_loaded_devices_without_operations_as_missing_operation():
  mqtt_service = FakeMQTTService()
  mqtt_service.client = FakeZigbeeClient()

  async def select_command(texts, catalog):
    raise AssertionError("command selector should not run without a commandable device catalog")

  component = ZigbeeComponent(mqtt_service, command_selector=select_command, response_generator=zigbee_response)
  configure_zigbee_devices(
    component,
    {
      "Bedroom light": {
        "friendly_name": "Lumière de la chambre",
        "ieee_address": "0xa4c1385960a05c86",
        "definition": {"exposes": []},
      },
    },
  )

  message, data = await component.process("Allume la lumière de la chambre", "fr", {}, [])

  expected = {
    "available_devices": ["Bedroom light"],
    "reason": "missing_operation",
    "required": ["operation"],
  }
  assert message == generated_zigbee_response("zigbee_missing_command", "fr", expected)
  assert data == expected
  assert mqtt_service.client.published == []


@pytest.mark.asyncio
async def test_zigbee_suggests_similar_device_instead_of_reporting_not_found():
  mqtt_service = FakeMQTTService()
  mqtt_service.client = FakeZigbeeClient()

  async def select_command(texts, catalog):
    return {"device": None, "payload": {}, "confidence": 0}

  component = ZigbeeComponent(mqtt_service, command_selector=select_command, response_generator=zigbee_response)
  configure_zigbee_devices(component, {"Living room lamp": light_device("Living room lamp")})

  message, data = await component.process("Turn on the living room lights and set brightness to 80%", "en", {}, [])

  expected = {
    "available_devices": ["Living room lamp"],
    "reason": "device_confirmation_required",
    "requested_device": "Turn on the living room lights and set brightness to 80%",
    "required": ["device"],
    "suggested_device": "Living room lamp",
    "suggested_devices": ["Living room lamp"],
  }
  assert message == generated_zigbee_response("zigbee_missing_command", "en", expected)
  assert data == expected
  assert mqtt_service.client.published == []


@pytest.mark.asyncio
async def test_zigbee_normalizes_llm_binary_and_enum_values():
  mqtt_service = FakeMQTTService()
  mqtt_service.client = FakeZigbeeClient()

  async def select_command(texts, catalog):
    return {"device": "Radiateur", "payload": {"state": "on", "system_mode": "HEAT"}}

  component = ZigbeeComponent(mqtt_service, command_selector=select_command, response_generator=zigbee_response)
  configure_zigbee_devices(
    component,
    {
      "Radiateur": {
        "friendly_name": "Radiateur",
        "ieee_address": "0xa4c13846a1d3578c",
        "definition": {
          "exposes": [
            {"type": "binary", "property": "state", "access": 7, "value_on": "ON", "value_off": "OFF"},
            {"type": "enum", "property": "system_mode", "access": 7, "values": ["off", "heat"]},
          ]
        },
      },
    },
  )

  message, data = await component.process("mets le radiateur en chauffe", "fr", {}, [])

  assert message == generated_zigbee_response(
    "zigbee_command_sent",
    "fr",
    {"device": "Radiateur", "command": {"state": "ON", "system_mode": "heat"}},
  )
  assert data == {"device": "Radiateur", "command": {"state": "ON", "system_mode": "heat"}}
  assert mqtt_service.client.published == [
    ("zigbee2mqtt/Radiateur/set", '{"state": "ON", "system_mode": "heat"}'),
  ]


@pytest.mark.asyncio
async def test_zigbee_updates_cached_state_from_device_topic_and_answers_status_question():
  mqtt_service = FakeMQTTService()
  mqtt_service.client = FakeZigbeeClient()

  async def select_command(texts, catalog):
    assert catalog == [
      {
        "name": "Thermomètre de la chambre",
        "mqtt_topic": "Thermomètre de la chambre",
        "model": None,
        "manufacturer": None,
        "operations": [],
        "states": [
          {
            "property": "temperature",
            "type": "numeric",
            "description": "Measured temperature.",
            "unit": "°C",
          },
          {
            "property": "humidity",
            "type": "numeric",
            "description": "Measured humidity.",
            "unit": "%",
          },
        ],
      }
    ]
    return {
      "intent": "read",
      "device": "Thermomètre de la chambre",
      "payload": {},
      "state_properties": ["temperature"],
      "confidence": 0.92,
    }

  component = ZigbeeComponent(mqtt_service, command_selector=select_command, response_generator=zigbee_response)
  component.start()
  await mqtt_service.handlers[DEVICES_TOPIC](json.dumps([thermometer_device("Thermomètre de la chambre")]).encode())
  mqtt_service.handlers["zigbee2mqtt/Thermomètre de la chambre"](
    json.dumps({"temperature": 21.6, "humidity": 48, "battery": 91}).encode()
  )

  message, data = await component.process("quelle est la température dans la chambre", "fr", {}, [])

  assert message == generated_zigbee_response(
    "zigbee_state",
    "fr",
    {
      "device": "Thermomètre de la chambre",
      "state": {"temperature": 21.6},
      "state_catalog": {
        "temperature": {
          "property": "temperature",
          "type": "numeric",
          "description": "Measured temperature.",
          "unit": "°C",
        }
      },
    },
  )
  assert data == {"device": "Thermomètre de la chambre", "state": {"temperature": 21.6}}
  assert component.device_states["Thermomètre de la chambre"] == {"temperature": 21.6, "humidity": 48}


@pytest.mark.asyncio
async def test_zigbee_formats_binary_state_as_human_readable_sentence():
  mqtt_service = FakeMQTTService()
  mqtt_service.client = FakeZigbeeClient()

  async def select_command(texts, catalog):
    return {
      "intent": "read",
      "device": "Lumière de la chambre",
      "payload": {},
      "state_properties": ["state"],
      "confidence": 1,
    }

  component = ZigbeeComponent(mqtt_service, command_selector=select_command, response_generator=zigbee_response)
  configure_zigbee_devices(component, {"Lumière de la chambre": light_device("Lumière de la chambre")})
  component.device_states["Lumière de la chambre"] = {"state": "OFF"}

  message, data = await component.process("est-ce que la lumière de la chambre est allumée", "fr", {}, [])

  assert message == generated_zigbee_response(
    "zigbee_state",
    "fr",
    {
      "device": "Lumière de la chambre",
      "state": {"state": "OFF"},
      "state_catalog": {
        "state": {
          "property": "state",
          "type": "binary",
          "description": "Turn the light on or off.",
        }
      },
    },
  )
  assert data == {"device": "Lumière de la chambre", "state": {"state": "OFF"}}
