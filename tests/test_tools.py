from datetime import datetime
from datetime import timedelta
from datetime import timezone

import pytest

from oremi_akorin.services.tools import DateTimeTool
from oremi_akorin.services.tools import ToolRegistry


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
async def test_registry_returns_structured_error_for_unknown_tool():
  result = await ToolRegistry([]).execute("missing_tool", {}, {})

  assert result.data == {"error": "Unknown tool: missing_tool"}
