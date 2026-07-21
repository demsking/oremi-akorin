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
from __future__ import annotations

import logging

import httpx
import ollama
from ollama import ResponseError

from akorin.core.settings import Settings

logger = logging.getLogger(__name__)


async def load_ollama_model(settings: Settings) -> None:
  if not settings.should_use_ollama:
    return

  client = ollama.AsyncClient(host=settings.ollama_base_url_string)

  try:
    logger.info(f"Pulling model {settings.ollama_model_name}...")
    await client.pull(settings.ollama_model_name, stream=False)

    logger.info(f"Loading model {settings.ollama_model_name}...")
    await client.generate(model=settings.ollama_model_name, keep_alive=-1, stream=False)
  except httpx.ReadTimeout as error:
    _log_model_load_timeout(settings.ollama_model_name, error)
    return
  except ResponseError as error:
    if error.status_code != 499:
      raise

    _log_model_load_timeout(settings.ollama_model_name, error)
    return

  logger.info(f"Ollama model ready: {settings.ollama_model_name}")


def _log_model_load_timeout(model_name: str, error: Exception) -> None:
  logger.warning(
    "Ollama model load timed out for %s; continuing startup and the model may finish loading in the background: %s",
    model_name,
    error,
  )
