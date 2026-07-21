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
import logging
import math
from typing import Any
from typing import ClassVar

from akorin.core.request import ProcessRequestContext
from akorin.core.tools import OllamaTool
from akorin.core.tools import ToolResult


logger = logging.getLogger(__name__)

_UNIT_GROUPS: dict[str, dict[str, tuple[float, float]]] = {
  "length": {
    "mm": (0.001, 0),
    "cm": (0.01, 0),
    "m": (1, 0),
    "km": (1000, 0),
    "in": (0.0254, 0),
    "ft": (0.3048, 0),
    "yd": (0.9144, 0),
    "mi": (1609.344, 0),
  },
  "mass": {
    "mg": (0.000001, 0),
    "g": (0.001, 0),
    "kg": (1, 0),
    "oz": (0.028349523125, 0),
    "lb": (0.45359237, 0),
  },
  "temperature": {"c": (1, 0), "f": (5 / 9, -32), "k": (1, -273.15)},
  "volume": {
    "ml": (0.001, 0),
    "l": (1, 0),
    "tsp": (0.00492892159375, 0),
    "tbsp": (0.01478676478125, 0),
    "cup": (0.2365882365, 0),
    "pt": (0.473176473, 0),
    "gal": (3.785411784, 0),
  },
  "speed": {"m/s": (1, 0), "km/h": (1 / 3.6, 0), "mph": (0.44704, 0), "knot": (0.5144444444444445, 0)},
}

_UNIT_ALIASES = {
  "meter": "m",
  "meters": "m",
  "metre": "m",
  "metres": "m",
  "kilometer": "km",
  "kilometers": "km",
  "kilometre": "km",
  "kilometres": "km",
  "mile": "mi",
  "miles": "mi",
  "foot": "ft",
  "feet": "ft",
  "inch": "in",
  "inches": "in",
  "kilogram": "kg",
  "kilograms": "kg",
  "pound": "lb",
  "pounds": "lb",
  "liter": "l",
  "liters": "l",
  "litre": "l",
  "litres": "l",
  "celsius": "c",
  "fahrenheit": "f",
  "kelvin": "k",
  "knots": "knot",
}


class UnitConversionTool(OllamaTool):
  name = "convert_units"
  definition: ClassVar[dict[str, Any]] = {
    "type": "function",
    "function": {
      "name": name,
      "description": "Convert length, mass, temperature, volume, or speed values between common metric and imperial units.",
      "parameters": {
        "type": "object",
        "properties": {
          "value": {"type": "number", "description": "Numeric value to convert."},
          "from_unit": {"type": "string", "description": "Source unit, for example km, lb, celsius, cup, or mph."},
          "to_unit": {"type": "string", "description": "Target unit, for example mi, kg, fahrenheit, ml, or km/h."},
        },
        "required": ["value", "from_unit", "to_unit"],
      },
    },
  }

  async def execute(self, arguments: dict[str, Any], context: ProcessRequestContext) -> ToolResult:
    try:
      value = float(arguments["value"])

      if not math.isfinite(value):
        raise ValueError("Value must be finite")

      source = self._normalize_unit(arguments["from_unit"])
      target = self._normalize_unit(arguments["to_unit"])
      category, source_conversion = self._find_unit(source)
      target_category, target_conversion = self._find_unit(target)

      if category != target_category:
        raise ValueError(f"Cannot convert {source} to {target}: units measure different quantities")

      base_value = (value + source_conversion[1]) * source_conversion[0]
      result = (base_value / target_conversion[0]) - target_conversion[1]
    except (KeyError, TypeError, ValueError) as exc:
      return ToolResult(name=self.name, data={"error": str(exc) or "Invalid conversion"})

    return ToolResult(
      name=self.name,
      data={"value": value, "from_unit": source, "to_unit": target, "result": result, "category": category},
    )

  @staticmethod
  def _normalize_unit(value: Any) -> str:
    unit = str(value).strip().casefold().replace("°", "")
    return _UNIT_ALIASES.get(unit, unit)

  @staticmethod
  def _find_unit(unit: str) -> tuple[str, tuple[float, float]]:
    for category, units in _UNIT_GROUPS.items():
      if unit in units:
        return category, units[unit]
    raise ValueError(f"Unsupported unit: {unit}")
