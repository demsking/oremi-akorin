import logging

from oremi_akorin.core.logger import DebugTracebackFilter


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
