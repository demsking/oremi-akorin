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
from typing import Any

from akorin.core.request import ProcessRequestContext
from akorin.core.service import Service


_TEMPORAL_CONTEXT_KEYS = frozenset(("timezone", "datetime", "date_format", "time_format", "first_day_of_week"))
_UNIT_CONTEXT_KEYS = frozenset(("temperature_unit", "measurement_system", "distance_unit", "preferred_currency"))
_WEATHER_UNIT_CONTEXT_KEYS = frozenset(("temperature_unit", "measurement_system", "distance_unit"))
_LOCATION_CONTEXT_KEYS = frozenset(("location", "address", "latitude", "longitude", "lat", "lon"))

_SERVICE_CONTEXT_KEYS: dict[Service, frozenset[str]] = {
  Service.CHAT: _TEMPORAL_CONTEXT_KEYS | _UNIT_CONTEXT_KEYS,
  Service.TOOL: _TEMPORAL_CONTEXT_KEYS | _UNIT_CONTEXT_KEYS,
  Service.OREMI_ISINMI: _TEMPORAL_CONTEXT_KEYS,
  Service.OREMI_OJO: _TEMPORAL_CONTEXT_KEYS
  | _WEATHER_UNIT_CONTEXT_KEYS
  | _LOCATION_CONTEXT_KEYS
  | frozenset(("alert_service", "service")),
  Service.OREMI_REDIYO: frozenset(),
  Service.OREMI_KANSA: frozenset(),
  Service.OREMI_ISAKOSO: frozenset(("device", "state", "room", "area", "zone")),
}


def context_for_service(service: Service, context: ProcessRequestContext) -> ProcessRequestContext:
  """Select the context keys a downstream service can use."""
  allowed_keys = _SERVICE_CONTEXT_KEYS.get(service, frozenset())

  if not allowed_keys or not context:
    return {}

  selected: ProcessRequestContext = {}
  preferences = context.get("preferences")

  if isinstance(preferences, dict):
    selected.update({key: value for key, value in preferences.items() if key in allowed_keys})

  selected.update({key: value for key, value in context.items() if key in allowed_keys})

  if service == Service.OREMI_OJO:
    selected = _normalize_weather_context(selected)

  return selected


def _normalize_weather_context(context: ProcessRequestContext) -> dict[str, Any]:
  selected = dict(context)

  if selected.get("lat") is None and selected.get("latitude") is not None:
    selected["lat"] = selected["latitude"]

  if selected.get("lon") is None and selected.get("longitude") is not None:
    selected["lon"] = selected["longitude"]

  return selected
