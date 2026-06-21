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
from typing import Literal

from ..core.exceptions import ComponentRequestError
from .base import ComponentClient

TemperatureUnit = Literal["celsius", "fahrenheit"]
AlertService = Literal["weather", "air-quality", "pollen"]


class WeatherClient(ComponentClient):
  endpoint_path = "/api/agent/climate"

  async def process(self, text: str, language: str, context: dict[str, Any], tags: dict[str, str]) -> tuple[str, Any]:
    data = await self.request_json(
      "GET",
      params={
        "q": text,
        "timezone": str(context.get("timezone", "UTC")),
        "temperature-unit": self._temperature_unit(context),
      },
    )

    return self.parse_response(data)

  def _temperature_unit(self, context: dict[str, Any]) -> TemperatureUnit:
    unit = context.get("temperature_unit", "celsius")

    if unit not in {"celsius", "fahrenheit"}:
      raise ComponentRequestError(
        self.name,
        "context.temperature_unit must be celsius or fahrenheit",
        message_en="Please choose Celsius or Fahrenheit for the temperature unit.",
        message_fr="Veuillez choisir Celsius ou Fahrenheit comme unité de température.",
      )

    return unit


class WeatherAlertsClient(WeatherClient):
  endpoint_path = "/api/agent/alerts"

  async def process(self, text: str, language: str, context: dict[str, Any], tags: dict[str, str]) -> tuple[str, Any]:
    service = context.get("service") or context.get("alert_service")
    latitude = context.get("lat")
    longitude = context.get("lon")

    if service not in {"weather", "air-quality", "pollen"}:
      raise ComponentRequestError(
        self.name,
        "context.alert_service must be weather, air-quality, or pollen",
        message_en="Please specify whether you want weather, air-quality, or pollen alerts.",
        message_fr="Veuillez préciser si vous souhaitez des alertes météo, de qualité de l'air ou de pollen.",
      )

    if latitude is None or longitude is None:
      raise ComponentRequestError(
        self.name,
        "context.lat and context.lon are required",
        message_en="Please share a location so I can check alerts for that area.",
        message_fr="Veuillez indiquer un lieu pour que je puisse vérifier les alertes dans cette zone.",
      )

    data = await self.request_json(
      "GET",
      params={
        "service": service,
        "lat": latitude,
        "lon": longitude,
        "timezone": str(context.get("timezone", "UTC")),
        "language": language,
        "temperature-unit": self._temperature_unit(context),
      },
    )

    return self.parse_response(data)
