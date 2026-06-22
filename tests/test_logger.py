import logging

import httpx
import pytest

from oremi_akorin.core.logger import DebugTracebackFilter
from oremi_akorin.utils.http_logging import enable_http_request_logging


def test_uvicorn_traceback_filter_hides_traceback_outside_debug():
  log_filter = DebugTracebackFilter()
  uvicorn_record = logging.LogRecord(
    "uvicorn.error",
    logging.ERROR,
    __file__,
    1,
    "Traceback (most recent call last):\nRuntimeError: startup failed",
    (),
    None,
  )

  app_logger = logging.getLogger("oremi-akorin")
  previous_level = app_logger.level

  try:
    app_logger.setLevel(logging.INFO)
    assert log_filter.filter(uvicorn_record) is False

    app_logger.setLevel(logging.DEBUG)
    assert log_filter.filter(uvicorn_record) is True
  finally:
    app_logger.setLevel(previous_level)


@pytest.mark.asyncio
async def test_http_request_debug_trace_includes_options_and_redacts_secrets(caplog):
  async with httpx.AsyncClient(
    transport=httpx.MockTransport(lambda request: httpx.Response(200)),
  ) as client:
    enable_http_request_logging(client)

    with caplog.at_level(logging.DEBUG, logger="oremi-akorin"):
      await client.get(
        "https://user:password@weather.test/api/climate",
        params={"q": "weather in Paris", "language": "en", "access_token": "private"},
      )

  message = next(record.getMessage() for record in caplog.records if record.getMessage().startswith("HTTP request:"))
  assert "method=GET" in message
  assert "url=https://weather.test/api/climate" in message
  assert "params={'q': 'weather in Paris', 'language': 'en', 'access_token': '***'}" in message
  assert "password" not in message
  assert "private" not in message
