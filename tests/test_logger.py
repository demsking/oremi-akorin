import logging

from akorin.utils.logger import configure_logging


def test_configure_logging_suppresses_watchfiles_noise():
  root = logging.getLogger()
  original_level = root.level
  original_handlers = list(root.handlers)
  watchfiles_logger = logging.getLogger("watchfiles")
  watchfiles_main_logger = logging.getLogger("watchfiles.main")
  original_watchfiles_level = watchfiles_logger.level
  original_watchfiles_main_level = watchfiles_main_logger.level

  try:
    configure_logging("INFO", None)

    assert watchfiles_logger.level == logging.WARNING
    assert watchfiles_main_logger.level == logging.WARNING
  finally:
    root.handlers.clear()
    root.handlers.extend(original_handlers)
    root.setLevel(original_level)
    watchfiles_logger.setLevel(original_watchfiles_level)
    watchfiles_main_logger.setLevel(original_watchfiles_main_level)
