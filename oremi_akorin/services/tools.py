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
import ast
import json
import math
import operator
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from typing import ClassVar
from typing import Protocol
from zoneinfo import ZoneInfo
from zoneinfo import ZoneInfoNotFoundError


_BINARY_OPERATORS: dict[type[ast.operator], Callable[[float, float], float]] = {
  ast.Add: operator.add,
  ast.Sub: operator.sub,
  ast.Mult: operator.mul,
  ast.Div: operator.truediv,
  ast.FloorDiv: operator.floordiv,
  ast.Mod: operator.mod,
  ast.Pow: operator.pow,
}
_UNARY_OPERATORS: dict[type[ast.unaryop], Callable[[float], float]] = {
  ast.UAdd: operator.pos,
  ast.USub: operator.neg,
}
_CONSTANTS = {"pi": math.pi, "e": math.e, "tau": math.tau}

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


@dataclass(frozen=True, slots=True)
class ToolResult:
  name: str
  data: dict[str, Any]

  def as_message_content(self) -> str:
    return json.dumps(self.data, ensure_ascii=False)


class OllamaTool(Protocol):
  name: str
  definition: dict[str, Any]

  async def execute(self, arguments: dict[str, Any], context: dict[str, Any]) -> ToolResult: ...


class DateTimeTool:
  name = "get_current_datetime"
  definition: ClassVar[dict[str, Any]] = {
    "type": "function",
    "function": {
      "name": name,
      "description": "Get the real current local date and time. Use this for every question about the current time, date, or day.",
      "parameters": {
        "type": "object",
        "properties": {
          "timezone": {
            "type": "string",
            "description": "Optional IANA timezone such as Europe/Paris when explicitly known.",
          },
        },
      },
    },
  }

  def __init__(self, clock: Callable[[], datetime] | None = None):
    self.clock = clock or (lambda: datetime.now().astimezone())

  async def execute(self, arguments: dict[str, Any], context: dict[str, Any]) -> ToolResult:
    timezone = arguments.get("timezone") or context.get("timezone")
    now = self._now(timezone)

    return ToolResult(
      name=self.name,
      data={
        "datetime": now.isoformat(),
        "date": now.date().isoformat(),
        "time": now.strftime("%H:%M:%S"),
        "timezone": str(now.tzinfo),
      },
    )

  def _now(self, timezone: Any) -> datetime:
    now = self.clock()

    if not timezone:
      return now

    try:
      return now.astimezone(ZoneInfo(str(timezone)))
    except ZoneInfoNotFoundError:
      return now


class CalculatorTool:
  name = "calculate"
  definition: ClassVar[dict[str, Any]] = {
    "type": "function",
    "function": {
      "name": name,
      "description": "Evaluate arithmetic accurately. Supports parentheses, +, -, *, /, //, %, **, pi, e, and tau.",
      "parameters": {
        "type": "object",
        "properties": {
          "expression": {
            "type": "string",
            "description": "Arithmetic expression, for example (12.5 * 4) + 7 or pi * 3 ** 2.",
          },
        },
        "required": ["expression"],
      },
    },
  }

  async def execute(self, arguments: dict[str, Any], context: dict[str, Any]) -> ToolResult:
    expression = str(arguments.get("expression", "")).strip()

    try:
      if not expression or len(expression) > 200:
        raise ValueError("Expression must contain between 1 and 200 characters")
      value = self._evaluate(ast.parse(expression, mode="eval").body)
      if not math.isfinite(value) or abs(value) > 1e100:
        raise ValueError("Result is outside the supported range")
    except (SyntaxError, TypeError, ValueError, ZeroDivisionError, OverflowError) as exc:
      return ToolResult(name=self.name, data={"error": str(exc) or "Invalid expression"})

    return ToolResult(name=self.name, data={"expression": expression, "result": value})

  def _evaluate(self, node: ast.AST, depth: int = 0) -> float:
    if depth > 20:
      raise ValueError("Expression is too complex")
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
      return float(node.value)
    if isinstance(node, ast.Name) and node.id in _CONSTANTS:
      return _CONSTANTS[node.id]
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
      return _UNARY_OPERATORS[type(node.op)](self._evaluate(node.operand, depth + 1))
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
      left = self._evaluate(node.left, depth + 1)
      right = self._evaluate(node.right, depth + 1)
      if isinstance(node.op, ast.Pow) and abs(right) > 100:
        raise ValueError("Exponent is outside the supported range")
      return _BINARY_OPERATORS[type(node.op)](left, right)
    raise ValueError("Expression contains an unsupported operation")


class UnitConversionTool:
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

  async def execute(self, arguments: dict[str, Any], context: dict[str, Any]) -> ToolResult:
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


class ToolRegistry:
  def __init__(self, tools: list[OllamaTool] | None = None):
    configured_tools = tools if tools is not None else [DateTimeTool(), CalculatorTool(), UnitConversionTool()]
    self.tools = {tool.name: tool for tool in configured_tools}

  @property
  def definitions(self) -> list[dict[str, Any]]:
    return [tool.definition for tool in self.tools.values()]

  async def execute(self, name: str, arguments: dict[str, Any], context: dict[str, Any]) -> ToolResult:
    tool = self.tools.get(name)
    if tool is None:
      return ToolResult(name=name, data={"error": f"Unknown tool: {name}"})
    return await tool.execute(arguments, context)
