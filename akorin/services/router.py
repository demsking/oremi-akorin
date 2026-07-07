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
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from ..core.constants import Service


@dataclass(frozen=True, slots=True)
class RoutingMatch:
  service: Service
  confidence: float
  reason: str


def rule_route(text: str, context: dict[str, Any] | None = None) -> RoutingMatch | None:
  normalized = _normalize(text)
  words = set(normalized.split())
  context = context or {}

  context_service = _context_service(context)

  if context_service is not None:
    match = RoutingMatch(context_service, 0.99, "explicit service context")
  elif context.get("device") or context.get("state") is not None:
    match = RoutingMatch(Service.ZIGBEE, 0.99, "structured device/state context")
  else:
    match = None

  zigbee_actions = (
    "turn on",
    "turn off",
    "switch on",
    "switch off",
    "light up",
    "allume",
    "allumer",
    "eteins",
    "eteinds",
    "eteindre",
    "eteint",
    "eteignez",
    "dim",
    "brighten",
    "activate",
    "deactivate",
    "active",
    "activer",
    "desactive",
    "desactiver",
    "open",
    "close",
    "ouvre",
    "ouvrir",
    "ferme",
    "fermer",
    "lock",
    "unlock",
  )
  zigbee_devices = {
    "blind",
    "bulb",
    "device",
    "door",
    "heater",
    "lamp",
    "light",
    "lock",
    "outlet",
    "plug",
    "shutter",
    "switch",
    "thermostat",
    "lumiere",
    "lampe",
    "interrupteur",
    "volet",
    "prise",
    "porte",
    "chauffage",
  }

  if match is None and (
    "zigbee" in words or (_contains_any(normalized, zigbee_actions) and words & zigbee_devices)
  ):
    match = RoutingMatch(Service.ZIGBEE, 0.98, "device action and device noun")

  if match is None and (words & {"podcast", "podcasts"} or "podcast episode" in normalized):
    match = RoutingMatch(Service.KANSA, 0.96, "podcast terminology")

  radio_actions = {"listen", "play", "stream", "tune"}
  if match is None and (
    "radio" in words
    or ("station" in words and words & radio_actions)
    or _contains_any(normalized, ("tune in", "radio station"))
  ):
    match = RoutingMatch(Service.REDIYO, 0.96, "radio terminology")

  if match is None and (
    words & {"alarm", "reminder", "timer"}
    or _contains_any(
      normalized,
      ("remind me", "wake me", "schedule a", "set an alarm", "set a timer"),
    )
  ):
    match = RoutingMatch(Service.ISINMI, 0.96, "scheduling terminology")

  if match is None and (
    words & {"weather", "forecast", "temperature", "pollen", "alert", "alerts", "warning", "warnings"}
    or "air quality" in normalized
  ):
    match = RoutingMatch(Service.WEATHER, 0.95, "weather terminology")

  return match


def _normalize(text: str) -> str:
  ascii_text = "".join(
    character for character in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(character)
  )
  return re.sub(r"[^a-z0-9]+", " ", ascii_text).strip()


def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
  return any(phrase in text for phrase in phrases)


def _context_service(context: dict[str, Any]) -> Service | None:
  for key in ("route_to", "target_service", "service"):
    value = context.get(key)

    if value is None:
      continue

    try:
      return Service(str(value))
    except ValueError:
      continue

  return None
