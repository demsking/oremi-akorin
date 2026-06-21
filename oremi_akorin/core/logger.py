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
import os

from .package import APP_NAME

# Map log level strings to their corresponding integer values
LOG_LEVEL_MAP = {
  "DEBUG": logging.DEBUG,
  "INFO": logging.INFO,
  "WARNING": logging.WARNING,
  "ERROR": logging.ERROR,
  "CRITICAL": logging.CRITICAL,
}

# Get log level from environment variable or default to 'INFO'
LOG_LEVEL_STR = os.environ.get("LOG_LEVEL", "INFO").upper()
log_file = os.environ.get("LOG_FILE")

# Convert log level string to integer
log_level = LOG_LEVEL_MAP.get(LOG_LEVEL_STR, logging.INFO)  # Default to INFO if invalid

# Set global log level and create logger
logger = logging.getLogger(APP_NAME)
logger.setLevel(log_level)


def tracebacks_enabled() -> bool:
  return logger.isEnabledFor(logging.DEBUG)


class DebugTracebackFilter(logging.Filter):
  def filter(self, record: logging.LogRecord) -> bool:
    return tracebacks_enabled() or not record.getMessage().lstrip().startswith("Traceback (most recent call last):")


class LowercaseLevelFormatter(logging.Formatter):
  def format(self, record: logging.LogRecord) -> str:
    record.levelname = record.levelname.lower()
    return super().format(record)


uvicorn_error_logger = logging.getLogger("uvicorn.error")

if not any(isinstance(log_filter, DebugTracebackFilter) for log_filter in uvicorn_error_logger.filters):
  uvicorn_error_logger.addFilter(DebugTracebackFilter())

# Create formatter
formatter = LowercaseLevelFormatter(fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

# Avoid adding multiple handlers if the logger is imported multiple times
if not logger.handlers:
  # Create handlers
  if log_file:
    handler = logging.FileHandler(log_file)
  else:
    handler = logging.StreamHandler()

  handler.setFormatter(formatter)
  logger.addHandler(handler)
