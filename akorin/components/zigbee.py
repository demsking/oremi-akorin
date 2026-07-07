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
import json
import logging
import re
import unicodedata
from collections.abc import Awaitable
from collections.abc import Callable
from difflib import SequenceMatcher
from typing import Any

import paho.mqtt.client as mqtt

from ..core.constants import Service
from ..core.exceptions import ComponentUnavailable
from ..core.mqtt import MQTTService
from ..utils.request_context import contextualized_text

DEVICES_TOPIC = "zigbee2mqtt/bridge/devices"
ORIGINAL_TEXT_CONTEXT_KEY = "_oremi_original_text"
DEVICE_MATCH_THRESHOLD = 0.72
DEVICE_MATCH_MARGIN = 0.1

logger = logging.getLogger(__name__)


class ZigbeeComponent:
  def __init__(
    self,
    mqtt_service: MQTTService,
    name_translator: Callable[[str], Awaitable[str]],
  ) -> None:
    self.mqtt = mqtt_service
    self.client = mqtt_service.client
    self.name_translator = name_translator
    self.devices: dict[str, dict[str, Any]] = {}

  def start(self) -> None:
    self.mqtt.subscribe(DEVICES_TOPIC, self._update_devices)
    logger.info(f"Zigbee device discovery subscribed: topic={DEVICES_TOPIC}")

  def stop(self) -> None:
    self.mqtt.unsubscribe(DEVICES_TOPIC)
    logger.info("Zigbee device discovery stopped")

  async def _update_devices(self, payload: bytes) -> None:
    try:
      device_list = json.loads(payload)

      if not isinstance(device_list, list):
        raise ValueError("device list must be an array")

      bridge_devices = []

      for device in device_list:
        if not isinstance(device, dict) or device.get("type") == "Coordinator":
          continue

        friendly_name = device.get("friendly_name")

        if isinstance(friendly_name, str) and friendly_name.strip():
          bridge_devices.append((friendly_name, device))

      english_names = await asyncio.gather(*(self._translate_name(friendly_name) for friendly_name, _ in bridge_devices))
      devices = {}

      for (friendly_name, device), english_name in zip(bridge_devices, english_names, strict=True):
        if english_name in devices:
          logger.warning(f"Duplicate translated Zigbee device name: {english_name}; using bridge name {friendly_name}")
          english_name = friendly_name

        devices[english_name] = device
        logger.info(
          f"Zigbee device found: bridge_name={friendly_name!r} english_name={english_name!r} "
          f"ieee_address={device.get('ieee_address', 'unknown')!r}"
        )

      self.devices = devices
      logger.info(f"Loaded {len(devices)} Zigbee devices with English names")
    except (json.JSONDecodeError, ValueError, TypeError) as exception:
      logger.warning(f"Ignoring invalid Zigbee device list: {exception}")

  async def _translate_name(self, name: str) -> str:
    try:
      translated_name = await self.name_translator(name)

      return translated_name or name
    except Exception as exception:
      logger.warning(f"Could not translate Zigbee device name {name!r}; using bridge name: {exception}")
      return name

  def _resolve_device(self, name: str) -> tuple[str, str]:
    normalized = self._normalize(name)

    for english_name, device in self.devices.items():
      friendly_name = device.get("friendly_name")
      ieee_address = device.get("ieee_address")

      if (
        self._normalize(english_name) == normalized
        or (isinstance(friendly_name, str) and self._normalize(friendly_name) == normalized)
        or (isinstance(ieee_address, str) and ieee_address.casefold() == normalized)
      ):
        return str(friendly_name), english_name
    return name, name

  def _extract_device(self, texts: list[str]) -> tuple[str, str, str, float] | None:
    normalized_texts = [self._normalize(text) for text in texts if text]
    exact_matches = []

    for english_name, device in self.devices.items():
      friendly_name = str(device.get("friendly_name", ""))

      for alias_type, alias in (("english", english_name), ("bridge", friendly_name)):
        normalized_alias = self._normalize(alias)

        if normalized_alias and any(self._contains_phrase(text, normalized_alias) for text in normalized_texts):
          exact_matches.append((len(normalized_alias), friendly_name, english_name, f"{alias_type} exact", 1.0))

    if exact_matches:
      _, bridge_name, english_name, reason, score = max(exact_matches)
      return bridge_name, english_name, reason, score

    fuzzy_matches = []

    for english_name, device in self.devices.items():
      friendly_name = str(device.get("friendly_name", ""))
      aliases = {self._normalize(english_name), self._normalize(friendly_name)}
      score = max(
        (self._device_similarity(text, alias) for text in normalized_texts for alias in aliases if alias),
        default=0.0,
      )
      fuzzy_matches.append((score, friendly_name, english_name))

    fuzzy_matches.sort(reverse=True)

    if not fuzzy_matches or fuzzy_matches[0][0] < DEVICE_MATCH_THRESHOLD:
      return None

    best_score, bridge_name, english_name = fuzzy_matches[0]
    runner_up_score = fuzzy_matches[1][0] if len(fuzzy_matches) > 1 else 0.0

    logger.debug(f"Zigbee fuzzy device candidates: best={english_name!r}:{best_score:.2f} runner_up={runner_up_score:.2f}")

    if best_score - runner_up_score < DEVICE_MATCH_MARGIN:
      logger.warning(
        f"Ambiguous Zigbee device name: best={english_name!r} score={best_score:.2f} runner_up_score={runner_up_score:.2f}"
      )
      return None

    return bridge_name, english_name, "fuzzy", best_score

  def _extract_state(self, texts: list[str]) -> str | None:
    normalized_texts = [self._normalize(text) for text in texts if text]
    off_phrases = ("turn off", "switch off", "power off", "eteins", "eteindre", "desactive", "desactiver", "ferme")
    on_phrases = ("turn on", "switch on", "power on", "light up", "allume", "allumer", "active", "activer", "ouvre")

    if any(self._contains_phrase(text, phrase) for text in normalized_texts for phrase in off_phrases):
      return "OFF"
    if any(self._contains_phrase(text, phrase) for text in normalized_texts for phrase in on_phrases):
      return "ON"
    return None

  def _device_similarity(self, text: str, alias: str) -> float:
    ignored_words = {
      "a",
      "an",
      "the",
      "to",
      "on",
      "off",
      "turn",
      "switch",
      "light",
      "up",
      "allume",
      "allumer",
      "de",
      "du",
      "la",
      "le",
      "les",
    }
    text_tokens = {word for word in text.split() if word not in ignored_words}
    alias_tokens = {word for word in alias.split() if word not in ignored_words}
    token_score = len(text_tokens & alias_tokens) / len(alias_tokens) if alias_tokens else 0.0
    sequence_score = SequenceMatcher(None, text, alias).ratio()
    return max(token_score, sequence_score)

  @staticmethod
  def _normalize(value: str) -> str:
    ascii_value = "".join(
      character for character in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(character)
    )
    return re.sub(r"[^a-z0-9]+", " ", ascii_value).strip()

  @staticmethod
  def _contains_phrase(text: str, phrase: str) -> bool:
    return f" {phrase} " in f" {text} "

  async def process(self, message: str, language: str, context: dict[str, Any], tags: list[str]) -> tuple[str, Any]:
    device = str(context.get("device") or "").strip()
    state = context.get("state")
    original_text = str(context.get(ORIGINAL_TEXT_CONTEXT_KEY) or "").strip()
    command_texts = [contextualized_text(message, context), original_text]

    if not self.client or not self.client.is_connected():
      raise ComponentUnavailable(Service.ZIGBEE, "MQTT is disconnected")

    match_reason = "explicit context"
    match_score = 1.0

    if device:
      bridge_device, display_name = self._resolve_device(device)
    else:
      extracted_device = self._extract_device(command_texts)

      if extracted_device:
        bridge_device, display_name, match_reason, match_score = extracted_device
        device = display_name
      else:
        bridge_device = ""
        display_name = ""

    if state is None:
      state = self._extract_state(command_texts)

    logger.debug(
      f"Zigbee command extraction: device={display_name or None!r} bridge_device={bridge_device or None!r} "
      f"state={state!r} reason={match_reason!r} score={match_score:.2f}"
    )

    if not device or state is None:
      message = "Specify a device and state." if language == "en" else "Précisez un appareil et son état."
      required = []

      if not device:
        required.append("device")
      if state is None:
        required.append("state")

      return message, {"required": required}

    payload = state if isinstance(state, dict) else {"state": state}
    info = await asyncio.to_thread(self.client.publish, f"zigbee2mqtt/{bridge_device}/set", json.dumps(payload))

    if info.rc != mqtt.MQTT_ERR_SUCCESS:
      raise ComponentUnavailable(Service.ZIGBEE, mqtt.error_string(info.rc))

    message = f"Command sent to {display_name}." if language == "en" else f"Commande envoyée à {display_name}."

    return message, {"device": display_name, "command": payload}
