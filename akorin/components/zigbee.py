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
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

import paho.mqtt.client as mqtt
from pydantic import BaseModel

from ..core.constants import Service
from ..core.exceptions import ComponentUnavailable
from ..core.mqtt import MQTTService
from ..utils.request_context import contextualized_text

DEVICES_TOPIC = "zigbee2mqtt/bridge/devices"
DEVICE_TOPIC_PREFIX = "zigbee2mqtt/"
ORIGINAL_TEXT_CONTEXT_KEY = "_oremi_original_text"
DEVICE_MATCH_THRESHOLD = 0.72
DEVICE_SUGGESTION_THRESHOLD = 0.5
DEVICE_MATCH_MARGIN = 0.1
ZIGBEE_GET_ACCESS = 1
ZIGBEE_SET_ACCESS = 2

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ZigbeeOperation:
  property: str
  type: str
  description: str = ""
  values: tuple[Any, ...] = ()
  value_on: Any = None
  value_off: Any = None
  value_min: float | None = None
  value_max: float | None = None
  unit: str | None = None

  def as_catalog(self) -> dict[str, Any]:
    data: dict[str, Any] = {
      "property": self.property,
      "type": self.type,
    }

    if self.description:
      data["description"] = self.description

    if self.values:
      data["values"] = list(self.values)

    if self.value_on is not None:
      data["value_on"] = self.value_on

    if self.value_off is not None:
      data["value_off"] = self.value_off

    if self.value_min is not None:
      data["min"] = self.value_min

    if self.value_max is not None:
      data["max"] = self.value_max

    if self.unit:
      data["unit"] = self.unit

    return data


@dataclass(frozen=True, slots=True)
class ZigbeeState:
  property: str
  type: str
  description: str = ""
  values: tuple[Any, ...] = ()
  unit: str | None = None

  def as_catalog(self) -> dict[str, Any]:
    data: dict[str, Any] = {
      "property": self.property,
      "type": self.type,
    }

    if self.description:
      data["description"] = self.description

    if self.values:
      data["values"] = list(self.values)

    if self.unit:
      data["unit"] = self.unit

    return data


class ZigbeeComponent:
  def __init__(
    self,
    mqtt_service: MQTTService,
    command_selector: Callable[[list[str], list[dict[str, Any]]], Awaitable[Any]] | None = None,
    response_generator: Callable[[str, str, dict[str, Any]], Awaitable[str]] | None = None,
  ) -> None:
    self.mqtt = mqtt_service
    self.client = mqtt_service.client
    self.command_selector = command_selector
    self.response_generator = response_generator
    self.devices: dict[str, dict[str, Any]] = {}
    self.operations: dict[str, dict[str, ZigbeeOperation]] = {}
    self.states: dict[str, dict[str, ZigbeeState]] = {}
    self.device_states: dict[str, dict[str, Any]] = {}
    self._state_topics: dict[str, str] = {}

  def start(self) -> None:
    self.mqtt.subscribe(DEVICES_TOPIC, self._update_devices)
    logger.info(f"Zigbee device discovery subscribed: topic={DEVICES_TOPIC}")

  def stop(self) -> None:
    self.mqtt.unsubscribe(DEVICES_TOPIC)
    for topic in list(self._state_topics):
      self.mqtt.unsubscribe(topic)
    self._state_topics = {}
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

      devices = {}
      operations = {}
      states = {}

      for friendly_name, device in bridge_devices:
        if friendly_name in devices:
          logger.warning(f"Duplicate Zigbee device name ignored: {friendly_name}")
          continue

        devices[friendly_name] = device
        operations[friendly_name] = self._extract_operations(device)
        states[friendly_name] = self._extract_states(device)

        logger.info(
          f"Zigbee device found: name={friendly_name!r} ieee_address={device.get('ieee_address', 'unknown')!r} "
          f"operations={sorted(operations[friendly_name])} states={sorted(states[friendly_name])}"
        )

      self.devices = devices
      self.operations = operations
      self.states = states
      self.device_states = {name: self.device_states.get(name, {}) for name in devices}
      self._sync_state_subscriptions(devices)
      logger.info(f"Loaded {len(devices)} Zigbee devices")
    except (json.JSONDecodeError, ValueError, TypeError) as exception:
      logger.warning(f"Ignoring invalid Zigbee device list: {exception}")

  def _resolve_device(self, name: str) -> tuple[str, str]:
    normalized = self._normalize(name)

    for device_name, device in self.devices.items():
      friendly_name = device.get("friendly_name")
      ieee_address = device.get("ieee_address")

      if (
        self._normalize(device_name) == normalized
        or (isinstance(friendly_name, str) and self._normalize(friendly_name) == normalized)
        or (isinstance(ieee_address, str) and ieee_address.casefold() == normalized)
      ):
        return str(friendly_name), device_name

    return name, name

  def _device_catalog(self) -> list[dict[str, Any]]:
    catalog = []

    for device_name, device in self.devices.items():
      friendly_name = str(device.get("friendly_name", ""))
      operation_catalog = [operation.as_catalog() for operation in self.operations.get(device_name, {}).values()]
      state_catalog = [state.as_catalog() for state in self.states.get(device_name, {}).values()]

      if not operation_catalog and not state_catalog:
        continue

      catalog.append(
        {
          "name": device_name,
          "mqtt_topic": friendly_name,
          "model": device.get("model") or device.get("model_id"),
          "manufacturer": device.get("manufacturer"),
          "operations": operation_catalog,
          "states": state_catalog,
        }
      )

    return catalog

  def _device_catalog_for(self, device_name: str) -> list[dict[str, Any]]:
    normalized = self._normalize(device_name)

    return [
      device
      for device in self._device_catalog()
      if self._normalize(str(device.get("name") or "")) == normalized
      or self._normalize(str(device.get("mqtt_topic") or "")) == normalized
    ]

  def _extract_operations(self, device: dict[str, Any]) -> dict[str, ZigbeeOperation]:
    operations: dict[str, ZigbeeOperation] = {}
    exposes = self._device_exposes(device)

    if not isinstance(exposes, list):
      return operations

    for expose in exposes:
      self._collect_operations(expose, operations, inherited_access=None)

    return operations

  def _extract_states(self, device: dict[str, Any]) -> dict[str, ZigbeeState]:
    states: dict[str, ZigbeeState] = {}
    exposes = self._device_exposes(device)

    if not isinstance(exposes, list):
      return states

    for expose in exposes:
      self._collect_states(expose, states, inherited_access=None)

    return states

  @staticmethod
  def _device_exposes(device: dict[str, Any]) -> list[Any] | None:
    exposes = device.get("exposes")

    if isinstance(exposes, list):
      return exposes

    definition = device.get("definition")

    if isinstance(definition, dict) and isinstance(definition.get("exposes"), list):
      return definition["exposes"]

    return None

  def _collect_operations(
    self,
    expose: Any,
    operations: dict[str, ZigbeeOperation],
    *,
    inherited_access: Any,
  ) -> None:
    if not isinstance(expose, dict):
      return

    access = expose.get("access", inherited_access)
    features = expose.get("features")

    if isinstance(features, list):
      for feature in features:
        self._collect_operations(feature, operations, inherited_access=access)

    property_name = expose.get("property")

    if not isinstance(property_name, str) or not property_name:
      return

    if not self._is_settable(access):
      return

    operation = self._operation_from_expose(property_name, expose)

    if operation is not None:
      operations[property_name] = operation

  def _collect_states(
    self,
    expose: Any,
    states: dict[str, ZigbeeState],
    *,
    inherited_access: Any,
  ) -> None:
    if not isinstance(expose, dict):
      return

    access = expose.get("access", inherited_access)
    features = expose.get("features")

    if isinstance(features, list):
      for feature in features:
        self._collect_states(feature, states, inherited_access=access)

    property_name = expose.get("property")

    if not isinstance(property_name, str) or not property_name:
      return

    if not self._is_readable(access):
      return

    state = self._state_from_expose(property_name, expose)

    if state is not None:
      states[property_name] = state

  @staticmethod
  def _is_readable(access: Any) -> bool:
    if isinstance(access, bool):
      return access

    if isinstance(access, int):
      return bool(access & ZIGBEE_GET_ACCESS)

    return False

  @staticmethod
  def _is_settable(access: Any) -> bool:
    if isinstance(access, bool):
      return access

    if isinstance(access, int):
      return bool(access & ZIGBEE_SET_ACCESS)

    return False

  def _state_from_expose(self, property_name: str, expose: dict[str, Any]) -> ZigbeeState | None:
    expose_type = str(expose.get("type") or "unknown")
    description = str(expose.get("description") or "").strip()
    values = expose.get("values")

    return ZigbeeState(
      property=property_name,
      type=expose_type,
      description=description,
      values=tuple(values) if isinstance(values, list) else (),
      unit=str(expose.get("unit")) if expose.get("unit") is not None else None,
    )

  def _operation_from_expose(self, property_name: str, expose: dict[str, Any]) -> ZigbeeOperation | None:
    expose_type = str(expose.get("type") or "unknown")
    description = str(expose.get("description") or "").strip()

    if expose_type == "binary":
      return ZigbeeOperation(
        property=property_name,
        type=expose_type,
        description=description,
        value_on=expose.get("value_on"),
        value_off=expose.get("value_off"),
      )

    if expose_type == "enum":
      values = expose.get("values")
      if not isinstance(values, list) or not values:
        return None
      return ZigbeeOperation(
        property=property_name,
        type=expose_type,
        description=description,
        values=tuple(values),
      )

    if expose_type == "numeric":
      return ZigbeeOperation(
        property=property_name,
        type=expose_type,
        description=description,
        value_min=self._number_or_none(expose.get("value_min")),
        value_max=self._number_or_none(expose.get("value_max")),
        unit=str(expose.get("unit")) if expose.get("unit") is not None else None,
      )

    if expose_type in {"text", "composite"}:
      return ZigbeeOperation(property=property_name, type=expose_type, description=description)

    return None

  def _extract_device(self, texts: list[str]) -> tuple[str, str, str, float] | None:
    normalized_texts = [self._normalize(text) for text in texts if text]
    exact_matches = []

    for device_name, device in self.devices.items():
      friendly_name = str(device.get("friendly_name", ""))

      for alias_type, alias in (("name", device_name), ("mqtt_topic", friendly_name)):
        normalized_alias = self._normalize(alias)

        if normalized_alias and any(self._contains_phrase(text, normalized_alias) for text in normalized_texts):
          exact_matches.append((len(normalized_alias), friendly_name, device_name, f"{alias_type} exact", 1.0))

    if exact_matches:
      _, bridge_name, device_name, reason, score = max(exact_matches)
      return bridge_name, device_name, reason, score

    fuzzy_matches = self._device_candidates(normalized_texts)

    if not fuzzy_matches or fuzzy_matches[0][0] < DEVICE_MATCH_THRESHOLD:
      return None

    best_score, bridge_name, device_name = fuzzy_matches[0]
    runner_up_score = fuzzy_matches[1][0] if len(fuzzy_matches) > 1 else 0.0

    logger.debug(f"Zigbee fuzzy device candidates: best={device_name!r}:{best_score:.2f} runner_up={runner_up_score:.2f}")

    if best_score - runner_up_score < DEVICE_MATCH_MARGIN:
      logger.warning(
        f"Ambiguous Zigbee device name: best={device_name!r} score={best_score:.2f} runner_up_score={runner_up_score:.2f}"
      )
      return None

    return bridge_name, device_name, "fuzzy", best_score

  def _suggest_devices(self, texts: list[str]) -> list[str]:
    candidates = self._device_candidates([self._normalize(text) for text in texts if text])

    if not candidates or candidates[0][0] < DEVICE_SUGGESTION_THRESHOLD:
      return []

    best_score = candidates[0][0]

    return [
      device_name
      for score, _, device_name in candidates[:3]
      if score >= DEVICE_SUGGESTION_THRESHOLD and best_score - score <= DEVICE_MATCH_MARGIN
    ]

  def _device_candidates(self, normalized_texts: list[str]) -> list[tuple[float, str, str]]:
    candidates = []

    for device_name, device in self.devices.items():
      friendly_name = str(device.get("friendly_name", ""))
      aliases = {self._normalize(device_name), self._normalize(friendly_name)}
      score = max(
        (self._device_similarity(text, alias) for text in normalized_texts for alias in aliases if alias),
        default=0.0,
      )
      candidates.append((score, friendly_name, device_name))

    return sorted(candidates, reverse=True)

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

  def _device_exists(self, device_name: str) -> bool:
    normalized = self._normalize(device_name)

    return any(
      self._normalize(name) == normalized or self._normalize(str(device.get("friendly_name") or "")) == normalized
      for name, device in self.devices.items()
    )

  def _available_device_names(self) -> list[str]:
    return sorted(self.devices)

  def _has_device_reference(self, texts: list[str]) -> bool:
    device_words = {
      "device",
      "heater",
      "interrupteur",
      "lamp",
      "lampe",
      "light",
      "lights",
      "lumiere",
      "lumieres",
      "plug",
      "prise",
      "radiateur",
      "switch",
      "thermostat",
    }

    return any(set(self._normalize(text).split()) & device_words for text in texts if text)

  def _requested_device_hint(self, texts: list[str]) -> str | None:
    for text in texts:
      if self._normalize(text):
        return text

    return None

  @staticmethod
  def _normalize(value: str) -> str:
    ascii_value = "".join(
      character for character in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(character)
    )
    return re.sub(r"[^a-z0-9]+", " ", ascii_value).strip()

  @staticmethod
  def _number_or_none(value: Any) -> float | None:
    if isinstance(value, bool):
      return None

    try:
      return float(value)
    except (TypeError, ValueError):
      return None

  @staticmethod
  def _contains_phrase(text: str, phrase: str) -> bool:
    return f" {phrase} " in f" {text} "

  def _sync_state_subscriptions(self, devices: dict[str, dict[str, Any]]) -> None:
    next_topics = {}

    for device_name, device in devices.items():
      friendly_name = str(device.get("friendly_name") or device_name)

      if not self.states.get(device_name):
        continue

      topic = f"{DEVICE_TOPIC_PREFIX}{friendly_name}"
      next_topics[topic] = device_name

      if self._state_topics.get(topic) == device_name:
        continue

      self.mqtt.subscribe(topic, lambda payload, name=device_name: self._update_device_state(name, payload))

    for topic in set(self._state_topics) - set(next_topics):
      self.mqtt.unsubscribe(topic)

    self._state_topics = next_topics

  def _update_device_state(self, device_name: str, payload: bytes) -> None:
    try:
      state = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as exception:
      logger.warning(f"Ignoring invalid Zigbee state payload: device={device_name!r} error={exception}")
      return

    if not isinstance(state, dict):
      logger.warning(f"Ignoring non-object Zigbee state payload: device={device_name!r}")
      return

    known_states = self.states.get(device_name, {})

    if not known_states:
      return

    cached = dict(self.device_states.get(device_name, {}))

    for property_name, value in state.items():
      if str(property_name) in known_states:
        cached[str(property_name)] = value

    self.device_states[device_name] = cached
    logger.debug(f"Zigbee state updated: device={device_name!r} keys={sorted(cached)}")

  async def process(self, message: str, language: str, context: dict[str, Any], tags: list[str]) -> tuple[str, Any]:
    explicit_device = str(context.get("device") or "").strip()
    original_text = str(context.get(ORIGINAL_TEXT_CONTEXT_KEY) or "").strip()
    command_texts = [contextualized_text(message, context), original_text]

    if not self.client or not self.client.is_connected():
      raise ComponentUnavailable(Service.ZIGBEE, "MQTT is disconnected")

    match_reason = "explicit context"
    match_score = 1.0

    if self.command_selector is None:
      return await self._missing_command_response(
        language,
        device_missing=not explicit_device,
        payload_missing=True,
        reason="command_selector_unavailable",
      )

    if explicit_device:
      bridge_device, display_name = self._resolve_device(explicit_device)
    else:
      extracted_device = self._extract_device(command_texts)

      if extracted_device:
        bridge_device, display_name, match_reason, match_score = extracted_device
      else:
        bridge_device = ""
        display_name = ""

    catalog = self._device_catalog_for(display_name) if display_name else self._device_catalog()

    if not catalog:
      reason = "requested_device_not_found" if display_name or explicit_device else "no_devices_available"
      return await self._missing_command_response(
        language,
        device_missing=True,
        payload_missing=not display_name,
        reason=reason,
        requested_device=display_name or explicit_device or None,
        suggested_devices=self._suggest_devices([display_name, explicit_device, *command_texts]),
      )

    try:
      decision = await self.command_selector([text for text in command_texts if text], catalog)
    except Exception as exception:
      logger.warning(f"Could not select Zigbee command with LLM: {exception}")
      decision = {}

    if isinstance(decision, BaseModel):
      decision = decision.model_dump()

    logger.debug(f"Zigbee LLM command decision: {decision!r}")

    if isinstance(decision, dict) and isinstance(decision.get("device"), str):
      bridge_device, display_name = self._resolve_device(decision["device"])

      if not self._device_exists(display_name):
        suggested_devices = self._suggest_devices([decision["device"], *command_texts])
        return await self._missing_command_response(
          language,
          device_missing=True,
          payload_missing=False,
          reason="device_confirmation_required" if suggested_devices else "requested_device_not_found",
          requested_device=decision["device"],
          suggested_devices=suggested_devices,
        )

    if self._is_read_decision(decision):
      state_properties = decision.get("state_properties") if isinstance(decision, dict) else None
      return await self._read_device_state(display_name, state_properties, language)

    payload = decision.get("payload") if isinstance(decision, dict) else None
    validated_payload = self._validate_payload(display_name, payload)

    logger.debug(
      f"Zigbee command extraction: device={display_name or None!r} bridge_device={bridge_device or None!r} "
      f"payload={validated_payload!r} reason={match_reason!r} score={match_score:.2f}"
    )

    if not display_name or not validated_payload:
      device_missing = not display_name
      reason = "missing_operation"

      suggested_devices = self._suggest_devices(command_texts) if device_missing else []

      if suggested_devices:
        reason = "device_confirmation_required"
      elif device_missing and self._has_device_reference(command_texts):
        reason = "requested_device_not_found"
      elif device_missing:
        reason = "missing_device"

      return await self._missing_command_response(
        language,
        device_missing=device_missing,
        payload_missing=not validated_payload and not suggested_devices,
        reason=reason,
        requested_device=(
          self._requested_device_hint(command_texts)
          if reason in {"device_confirmation_required", "requested_device_not_found"}
          else None
        ),
        suggested_devices=suggested_devices,
      )

    info = await asyncio.to_thread(self.client.publish, f"zigbee2mqtt/{bridge_device}/set", json.dumps(validated_payload))

    if info.rc != mqtt.MQTT_ERR_SUCCESS:
      raise ComponentUnavailable(Service.ZIGBEE, mqtt.error_string(info.rc))

    self._merge_device_state(display_name, validated_payload)

    message = await self._generate_response(
      "zigbee_command_sent",
      language,
      {"device": display_name, "command": validated_payload},
    )

    return message, {"device": display_name, "command": validated_payload}

  @staticmethod
  def _is_read_decision(decision: Any) -> bool:
    if not isinstance(decision, dict):
      return False

    intent = decision.get("intent")
    state_properties = decision.get("state_properties")

    return intent == "read" or (isinstance(state_properties, list) and bool(state_properties) and not decision.get("payload"))

  async def _read_device_state(self, display_name: str, state_properties: Any, language: str) -> tuple[str, dict[str, Any]]:
    if not display_name:
      return await self._missing_command_response(
        language,
        device_missing=True,
        payload_missing=False,
        reason="missing_device",
      )

    readable_states = self.states.get(display_name, {})
    cached_state = self.device_states.get(display_name, {})
    requested = self._validate_state_properties(display_name, state_properties)

    if not requested:
      requested = [property_name for property_name in readable_states if property_name in cached_state]

    values = {property_name: cached_state[property_name] for property_name in requested if property_name in cached_state}

    if not values:
      message = await self._generate_response(
        "zigbee_state_unavailable",
        language,
        {"device": display_name, "requested_state": requested},
      )
      return message, {"device": display_name, "required": ["state"]}

    message = await self._generate_response(
      "zigbee_state",
      language,
      {
        "device": display_name,
        "state": values,
        "state_catalog": {property_name: readable_states[property_name].as_catalog() for property_name in values},
      },
    )

    return message, {"device": display_name, "state": values}

  def _validate_state_properties(self, display_name: str, state_properties: Any) -> list[str]:
    if not isinstance(state_properties, list):
      return []

    readable_states = self.states.get(display_name, {})
    requested = []

    for property_name in state_properties:
      normalized_property = str(property_name)

      if normalized_property in readable_states and normalized_property not in requested:
        requested.append(normalized_property)
      else:
        logger.warning(f"Ignoring unsupported Zigbee state for {display_name}: {property_name}")

    return requested

  def _merge_device_state(self, display_name: str, values: dict[str, Any]) -> None:
    known_states = self.states.get(display_name, {})

    if not known_states:
      return

    cached = dict(self.device_states.get(display_name, {}))

    for property_name, value in values.items():
      if property_name in known_states:
        cached[property_name] = value

    self.device_states[display_name] = cached

  def _validate_payload(self, display_name: str, payload: Any) -> dict[str, Any]:
    if not display_name or not isinstance(payload, dict):
      return {}

    operations = self.operations.get(display_name, {})
    validated = {}

    for property_name, value in payload.items():
      operation = operations.get(str(property_name))

      if operation is None:
        logger.warning(f"Ignoring unsupported Zigbee property for {display_name}: {property_name}")
        continue

      normalized_value = self._validate_value(operation, value)

      if normalized_value is not None:
        validated[operation.property] = normalized_value
      else:
        logger.warning(
          f"Ignoring invalid Zigbee value for {display_name}: property={operation.property} "
          f"value={value!r} operation={operation.as_catalog()!r}"
        )

    return validated

  def _validate_value(self, operation: ZigbeeOperation, value: Any) -> Any:
    if operation.type == "binary":
      if value in (operation.value_on, operation.value_off):
        return value

      if isinstance(value, bool):
        return operation.value_on if value else operation.value_off

      if isinstance(value, str):
        if isinstance(operation.value_on, str) and value.casefold() == operation.value_on.casefold():
          return operation.value_on

        if isinstance(operation.value_off, str) and value.casefold() == operation.value_off.casefold():
          return operation.value_off

      return None

    if operation.type == "enum":
      if value in operation.values:
        return value

      if isinstance(value, str):
        for option in operation.values:
          if isinstance(option, str) and value.casefold() == option.casefold():
            return option

      return None

    if operation.type == "numeric":
      if isinstance(value, bool):
        return None

      try:
        number = float(value)
      except (TypeError, ValueError):
        return None

      if operation.value_min is not None and number < operation.value_min:
        return None

      if operation.value_max is not None and number > operation.value_max:
        return None

      return int(number) if number.is_integer() else number

    if operation.type == "text":
      return value if isinstance(value, str) else None

    if operation.type == "composite":
      return value if isinstance(value, dict) else None

    return None

  async def _missing_command_response(
    self,
    language: str,
    *,
    device_missing: bool,
    payload_missing: bool,
    reason: str,
    requested_device: str | None = None,
    suggested_devices: list[str] | None = None,
  ) -> tuple[str, dict[str, Any]]:
    required = []

    if device_missing:
      required.append("device")

    if payload_missing:
      required.append("operation")

    data: dict[str, Any] = {"required": required, "reason": reason}

    if requested_device:
      data["requested_device"] = requested_device

    if suggested_devices:
      data["suggested_devices"] = suggested_devices
      if len(suggested_devices) == 1:
        data["suggested_device"] = suggested_devices[0]

    available_devices = self._available_device_names()

    if available_devices:
      data["available_devices"] = available_devices

    message = await self._generate_response("zigbee_missing_command", language, data)

    return message, data

  async def _generate_response(self, event: str, language: str, details: dict[str, Any]) -> str:
    if self.response_generator is None:
      raise ComponentUnavailable(Service.ZIGBEE, "response generator is not configured")

    message = (await self.response_generator(event, language, details)).strip()

    if not message:
      raise ComponentUnavailable(Service.ZIGBEE, "response generator returned an empty message")

    return message
