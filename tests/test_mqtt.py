import asyncio
import logging

import paho.mqtt.client as mqtt
import pytest
from pydantic import ValidationError

from oremi_akorin.core.settings import Settings
from oremi_akorin.core.constants import Language
from oremi_akorin.core.constants import Service
from oremi_akorin.core.mqtt import MQTTService
from oremi_akorin.core.models import PlayCommand
from oremi_akorin.core.models import ProcessResponse
from oremi_akorin.core.models import SpeakCommand


async def processor(request):
  raise AssertionError("processor should not be called")


@pytest.mark.asyncio
async def test_start_waits_until_mqtt_is_connected(monkeypatch):
  settings = Settings(
    OLLAMA_PULL_MODEL=False,
    MQTT_BROKER="mqtt.test",
    MQTT_PORT=1883,
  )
  service = MQTTService(settings, processor)
  connection = {}

  def connect_async(host, port, keepalive):
    connection.update(host=host, port=port, keepalive=keepalive)

  monkeypatch.setattr(service.client, "connect_async", connect_async)
  monkeypatch.setattr(service.client, "loop_start", lambda: mqtt.MQTT_ERR_SUCCESS)
  monkeypatch.setattr(service.client, "subscribe", lambda *args, **kwargs: None)
  monkeypatch.setattr(service.client, "publish", lambda *args, **kwargs: None)

  start_task = asyncio.create_task(service.start())
  await asyncio.sleep(0)

  assert start_task.done() is False
  assert connection == {"host": "mqtt.test", "port": 1883, "keepalive": 60}

  service._on_connect_fail(service.client, None)
  await asyncio.sleep(0)

  assert start_task.done() is False

  service._on_connect(service.client, None, None, 0, None)  # type: ignore[arg-type]

  assert await start_task is True


def test_mqtt_broker_scheme_is_removed_for_paho():
  settings = Settings(OLLAMA_PULL_MODEL=False, MQTT_BROKER="mqtt://broker.test")

  assert settings.mqtt_broker == "broker.test"


def test_oremi_device_topics_are_derived_from_normalized_base():
  settings = Settings(OLLAMA_PULL_MODEL=False, OREMI_DEVICE_MQTT_TOPIC=" /house/oremi/ ")

  assert settings.oremi_device_mqtt_topic == "house/oremi"
  assert settings.mqtt_transcription_topic == "house/oremi/nodes/+/transcription/result"
  assert settings.mqtt_processing_result_topic("kitchen") == "house/oremi/nodes/kitchen/processing/result"


def test_oremi_device_base_topic_rejects_wildcards():
  with pytest.raises(ValidationError, match="without wildcards"):
    Settings(OLLAMA_PULL_MODEL=False, OREMI_DEVICE_MQTT_TOPIC="oremi/+/device")


def test_subscribe_and_unsubscribe_are_logged(caplog):
  settings = Settings(OLLAMA_PULL_MODEL=False, MQTT_BROKER=None)
  service = MQTTService(settings, processor)

  with caplog.at_level(logging.INFO, logger="oremi-akorin"):
    service.subscribe("zigbee/devices", lambda payload: None)
    service.unsubscribe("zigbee/devices")

  messages = [record.getMessage() for record in caplog.records]
  assert "MQTT handler subscribed: topic=zigbee/devices broker_subscription=deferred" in messages
  assert "MQTT handler unsubscribed: topic=zigbee/devices handler_registered=True broker_subscription=inactive" in messages


def test_mqtt_handler_traceback_is_only_attached_in_debug(caplog):
  settings = Settings(OLLAMA_PULL_MODEL=False, MQTT_BROKER=None)
  service = MQTTService(settings, processor)

  def fail(payload):
    raise ValueError("invalid payload")

  class Message:
    topic = "zigbee/devices"
    payload = b"invalid"

  service.message_handlers["zigbee/#"] = fail

  with caplog.at_level(logging.INFO, logger="oremi-akorin"):
    service._on_message(service.client, None, Message())  # type: ignore[arg-type]

  record = next(record for record in caplog.records if "Could not process MQTT message" in record.getMessage())
  assert not record.exc_info

  caplog.clear()
  with caplog.at_level(logging.DEBUG, logger="oremi-akorin"):
    service._on_message(service.client, None, Message())  # type: ignore[arg-type]

  record = next(record for record in caplog.records if "Could not process MQTT message" in record.getMessage())
  assert record.exc_info is not None


@pytest.mark.asyncio
async def test_mqtt_schedules_async_message_handlers():
  settings = Settings(OLLAMA_PULL_MODEL=False, MQTT_BROKER=None)
  service = MQTTService(settings, processor)
  service.loop = asyncio.get_running_loop()
  handled = asyncio.Event()

  async def handler(payload):
    assert payload == b"devices"
    handled.set()

  class Message:
    topic = "zigbee/devices"
    payload = b"devices"

  service.subscribe("zigbee/#", handler)
  service._on_message(service.client, None, Message())  # type: ignore[arg-type]

  await asyncio.wait_for(handled.wait(), timeout=1)


@pytest.mark.asyncio
async def test_processes_final_transcription_and_replies_to_same_node(monkeypatch):
  requests = []

  async def process(request):
    requests.append(request)
    return ProcessResponse(
      input=request.text,
      language=Language.EN,
      service=Service.CHAT,
      message="The light is on",
      confidence=1,
    )

  settings = Settings(OLLAMA_PULL_MODEL=False, MQTT_BROKER=None)
  service = MQTTService(settings, process)
  published = []
  monkeypatch.setattr(service.client, "publish", lambda *args, **kwargs: published.append((args, kwargs)))

  await service._process(
    "oremi/device/nodes/living-room/transcription/result",
    b'{"text":"turn on the light"}',
  )

  assert requests[0].text == "turn on the light"
  assert published == [(("oremi/device/nodes/living-room/processing/result", '{"message": "The light is on"}'), {"qos": 1})]


@pytest.mark.asyncio
@pytest.mark.parametrize(
  "payload",
  [
    b"",
    b"not-json",
    b'{"partial":"hello"}',
    b'{"text":""}',
  ],
)
async def test_invalid_transcription_is_ignored(payload, monkeypatch, caplog):
  settings = Settings(OLLAMA_PULL_MODEL=False, MQTT_BROKER=None)
  service = MQTTService(settings, processor)
  published = []
  monkeypatch.setattr(service.client, "publish", lambda *args, **kwargs: published.append((args, kwargs)))

  with caplog.at_level(logging.DEBUG, logger="oremi-akorin"):
    await service._process("oremi/device/nodes/bedroom/transcription/result", payload)

  assert published == []
  assert any("Ignored" in record.getMessage() and "node=bedroom" in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
async def test_device_commands_are_forwarded_in_order(monkeypatch):
  async def process(request):
    return ProcessResponse(
      input=request.text,
      language=Language.EN,
      service=Service.REDIYO,
      message="Playing the radio",
      confidence=1,
      commands=[
        SpeakCommand(text="Playing your station"),
        PlayCommand(url="https://radio.example/live.mp3"),
      ],
    )

  settings = Settings(OLLAMA_PULL_MODEL=False, MQTT_BROKER=None)
  service = MQTTService(settings, process)
  published = []
  monkeypatch.setattr(service.client, "publish", lambda *args, **kwargs: published.append((args, kwargs)))

  await service._process("oremi/device/nodes/kitchen/transcription/result", b'{"text":"play the radio"}')

  output = __import__("json").loads(published[0][0][1])
  assert output == {
    "message": "Playing the radio",
    "commands": [
      {"type": "speak", "text": "Playing your station"},
      {"type": "play", "url": "https://radio.example/live.mp3"},
    ],
  }
