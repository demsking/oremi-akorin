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
import inspect
import json
from collections.abc import Awaitable
from collections.abc import Callable
from concurrent.futures import Future

import paho.mqtt.client as mqtt
from pydantic import ValidationError

from ..core.models import ProcessRequest
from ..core.models import ProcessResponse
from .logger import logger
from .logger import tracebacks_enabled
from .settings import Settings


class MQTTService:
  def __init__(self, settings: Settings, processor: Callable[[ProcessRequest], Awaitable[ProcessResponse]]):
    self.settings = settings
    self.processor = processor
    self.loop: asyncio.AbstractEventLoop | None = None
    self.started = False
    self._connection_event = asyncio.Event()
    self._connection_error: str | None = None
    self.message_handlers: dict[str, Callable[[bytes], Awaitable[None] | None]] = {}
    self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=settings.mqtt_client_id)
    self.client.on_connect = self._on_connect
    self.client.on_connect_fail = self._on_connect_fail
    self.client.on_message = self._on_message

    if settings.mqtt_username:
      self.client.username_pw_set(settings.mqtt_username, settings.mqtt_password)

    if settings.mqtt_tls_enabled:
      self.client.tls_set(ca_certs=settings.mqtt_tls_ca_cert)

  @property
  def connected(self) -> bool:
    return self.client.is_connected()

  async def start(self) -> bool:
    if not self.settings.mqtt_broker:
      logger.info("MQTT startup skipped: no broker configured")
      return False

    logger.info(
      f"Starting MQTT connection: broker={self.settings.mqtt_broker}:{self.settings.mqtt_port} "
      f"tls={self.settings.mqtt_tls_enabled}"
    )

    self.loop = asyncio.get_running_loop()
    self._connection_event.clear()
    self._connection_error = None

    try:
      self.client.connect_async(
        self.settings.mqtt_broker,
        self.settings.mqtt_port,
        keepalive=self.settings.mqtt_keepalive,
      )

      loop_result = self.client.loop_start()

      if loop_result != mqtt.MQTT_ERR_SUCCESS:
        raise RuntimeError(f"MQTT network loop could not start: {mqtt.error_string(loop_result)}")

      self.started = True
      await self._connection_event.wait()
    except (OSError, RuntimeError, ValueError) as exception:
      self.stop()
      raise RuntimeError(f"MQTT could not start: {exception}") from exception

    if self._connection_error:
      self.stop()
      raise RuntimeError(f"MQTT connection failed: {self._connection_error}")

    return True

  def stop(self) -> None:
    if self.connected:
      self.client.disconnect()

    if self.started:
      self.client.loop_stop()
      self.started = False
      logger.info("MQTT client stopped")

  def subscribe(self, topic: str, handler: Callable[[bytes], Awaitable[None] | None]) -> None:
    self.message_handlers[topic] = handler
    broker_subscription = "deferred"

    if self.connected:
      self.client.subscribe(topic)
      broker_subscription = "active"

    logger.info(f"MQTT handler subscribed: topic={topic} broker_subscription={broker_subscription}")

  def unsubscribe(self, topic: str) -> None:
    handler_registered = self.message_handlers.pop(topic, None) is not None
    broker_subscription = "inactive"

    if self.connected:
      self.client.unsubscribe(topic)
      broker_subscription = "removed"

    logger.info(
      f"MQTT handler unsubscribed: topic={topic} handler_registered={handler_registered} "
      f"broker_subscription={broker_subscription}"
    )

  def _on_connect(
    self,
    client: mqtt.Client,
    userdata: object,
    flags: mqtt.ConnectFlags,
    reason_code: mqtt.ReasonCode,
    properties: mqtt.Properties | None,
  ) -> None:
    if reason_code == 0:
      client.subscribe(self.settings.mqtt_transcription_topic, qos=1)

      for topic in self.message_handlers:
        client.subscribe(topic)

      logger.info(
        f"MQTT connected: transcription_topic={self.settings.mqtt_transcription_topic} handlers={len(self.message_handlers)}"
      )
      self._signal_connection_result()
    else:
      logger.error(f"MQTT connection failed: {reason_code}")
      self._connection_error = str(reason_code)
      self._signal_connection_result()

  def _on_connect_fail(self, client: mqtt.Client, userdata: object) -> None:
    logger.warning(
      f"MQTT connection attempt failed; Paho will retry: broker={self.settings.mqtt_broker}:{self.settings.mqtt_port}"
    )

  def _signal_connection_result(self) -> None:
    if self.loop and not self.loop.is_closed():
      self.loop.call_soon_threadsafe(self._connection_event.set)

  def _on_message(self, client: mqtt.Client, userdata: object, message: mqtt.MQTTMessage) -> None:
    for topic, handler in self.message_handlers.items():
      if mqtt.topic_matches_sub(topic, message.topic):
        try:
          result = handler(message.payload)

          if inspect.isawaitable(result):
            if self.loop is None:
              raise RuntimeError("MQTT event loop is unavailable")

            future = asyncio.run_coroutine_threadsafe(result, self.loop)  # type: ignore
            future.add_done_callback(lambda completed: self._log_handler_failure(completed, message.topic))
        except Exception as exception:
          logger.error(
            f"Could not process MQTT message from {message.topic}: {exception}",
            exc_info=tracebacks_enabled(),
          )
        return

    if self.loop:
      future = asyncio.run_coroutine_threadsafe(self._process(message.topic, message.payload), self.loop)
      future.add_done_callback(lambda completed: self._log_handler_failure(completed, message.topic))

  def _log_handler_failure(self, future: Future[None], topic: str) -> None:
    try:
      future.result()
    except Exception as exception:
      logger.error(
        f"Could not process MQTT message from {topic}: {exception}",
        exc_info=tracebacks_enabled(),
      )

  async def _process(self, topic: str, payload: bytes) -> None:
    node_id = self._node_id(topic)

    if not payload.strip():
      logger.debug(f"Ignored empty MQTT transcription: node={node_id}")
      return

    try:
      body = json.loads(payload)
      request = ProcessRequest.model_validate(body)
    except (json.JSONDecodeError, UnicodeDecodeError, ValidationError) as exception:
      logger.warning(f"Ignored invalid MQTT transcription: node={node_id} error={exception}")
      return

    try:
      response = await self.processor(request)
      device_response = {"message": response.message}

      if response.commands:
        device_response["commands"] = [command.model_dump(mode="json", exclude_none=True) for command in response.commands]  # type: ignore

      output = json.dumps(device_response)
    except Exception as exc:  # MQTT must always return a response to its caller.
      logger.error(f"Could not process MQTT request: {exc}", exc_info=tracebacks_enabled())
      output = json.dumps({"message": str(exc)})

    self.client.publish(self.settings.mqtt_processing_result_topic(node_id), output, qos=1)

  def _node_id(self, topic: str) -> str:
    prefix = f"{self.settings.oremi_device_mqtt_topic}/nodes/"
    suffix = "/transcription/result"

    if not topic.startswith(prefix) or not topic.endswith(suffix):
      raise ValueError(f"Unexpected Oremi Device transcription topic: {topic}")

    node_id = topic[len(prefix) : -len(suffix)]
    if not node_id or "/" in node_id:
      raise ValueError(f"Invalid Oremi Device node ID in topic: {topic}")

    return node_id
