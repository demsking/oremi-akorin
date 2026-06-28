from datetime import datetime
from datetime import timedelta
from datetime import timezone

import pytest

from oremi_akorin.services.tools import DateTimeTool
from oremi_akorin.services.tools import CalculatorTool
from oremi_akorin.services.tools import ToolRegistry
from oremi_akorin.services.tools import UnitConversionTool


@pytest.mark.asyncio
async def test_datetime_tool_returns_real_clock_data():
  current = datetime(2026, 6, 20, 14, 32, tzinfo=timezone(timedelta(hours=2)))
  registry = ToolRegistry([DateTimeTool(clock=lambda: current)])

  result = await registry.execute("get_current_datetime", {}, {})

  assert result.name == "get_current_datetime"
  assert result.data == {
    "datetime": "2026-06-20T14:32:00+02:00",
    "date": "2026-06-20",
    "time": "14:32:00",
    "timezone": "UTC+02:00",
  }


@pytest.mark.asyncio
async def test_tool_registry_uses_context_arguments_as_defaults():
  current = datetime(2026, 6, 20, 14, 32, tzinfo=timezone.utc)
  registry = ToolRegistry([DateTimeTool(clock=lambda: current)])

  result = await registry.execute(
    "get_current_datetime",
    {},
    {"tools": {"get_current_datetime": {"timezone": "Europe/Paris"}}},
  )

  assert result.data["time"] == "16:32:00"
  assert result.data["timezone"] == "Europe/Paris"


@pytest.mark.asyncio
async def test_tool_registry_keeps_explicit_arguments_over_context_defaults():
  current = datetime(2026, 6, 20, 14, 32, tzinfo=timezone.utc)
  registry = ToolRegistry([DateTimeTool(clock=lambda: current)])

  result = await registry.execute(
    "get_current_datetime",
    {"timezone": "UTC"},
    {"tools": {"get_current_datetime": {"timezone": "Europe/Paris"}}},
  )

  assert result.data["time"] == "14:32:00"
  assert result.data["timezone"] == "UTC"


@pytest.mark.asyncio
async def test_registry_returns_structured_error_for_unknown_tool():
  result = await ToolRegistry([]).execute("missing_tool", {}, {})

  assert result.data == {"error": "Unknown tool: missing_tool"}


@pytest.mark.asyncio
async def test_calculator_evaluates_arithmetic_and_constants():
  result = await CalculatorTool().execute({"expression": "pi * 3 ** 2"}, {})

  assert result.data["expression"] == "pi * 3 ** 2"
  assert result.data["result"] == pytest.approx(28.2743338823)


@pytest.mark.asyncio
@pytest.mark.parametrize("expression", ["1 / 0", "__import__('os')", "2 ** 101", ""])
async def test_calculator_rejects_unsafe_or_invalid_expressions(expression):
  result = await CalculatorTool().execute({"expression": expression}, {})

  assert "error" in result.data


@pytest.mark.asyncio
@pytest.mark.parametrize(
  ("arguments", "expected"),
  [
    ({"value": 5, "from_unit": "kilometers", "to_unit": "mi"}, 3.1068559612),
    ({"value": 32, "from_unit": "fahrenheit", "to_unit": "celsius"}, 0),
    ({"value": 1, "from_unit": "cup", "to_unit": "ml"}, 236.5882365),
  ],
)
async def test_unit_conversion_supports_common_quantities(arguments, expected):
  result = await UnitConversionTool().execute(arguments, {})

  assert result.data["result"] == pytest.approx(expected)


@pytest.mark.asyncio
async def test_unit_conversion_rejects_incompatible_units():
  result = await UnitConversionTool().execute({"value": 1, "from_unit": "kg", "to_unit": "km"}, {})

  assert result.data == {"error": "Cannot convert kg to km: units measure different quantities"}


def test_default_registry_exposes_practical_tools():
  names = [definition["function"]["name"] for definition in ToolRegistry().definitions]

  assert names == ["get_current_datetime", "calculate", "convert_units"]
