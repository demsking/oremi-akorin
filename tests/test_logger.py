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
