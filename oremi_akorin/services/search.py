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
from typing import Any

import httpx

from ..core.constants import Service
from ..core.exceptions import ComponentUnavailable
from ..utils.http_retry import request_with_retry


class SearchService:
  def __init__(self, client: httpx.AsyncClient) -> None:
    self.client = client

  async def process(self, text: str, language: str, context: dict[str, Any], tags: dict[str, str]) -> tuple[str, Any]:
    try:
      response = await request_with_retry(
        lambda: self.client.get(
          "https://api.duckduckgo.com/",
          params={"q": text, "format": "json", "no_html": 1, "skip_disambig": 1},
        ),
        Service.SEARCH.value,
      )

      response.raise_for_status()

      data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
      raise ComponentUnavailable(Service.SEARCH, str(exc)) from exc

    answer = data.get("Answer") or data.get("AbstractText")

    if not answer:
      topics = data.get("RelatedTopics") or []
      first = next((item.get("Text") for item in topics if isinstance(item, dict) and item.get("Text")), None)
      answer = first

    if not answer:
      answer = "No direct result was found." if language == "en" else "Aucun résultat direct n'a été trouvé."

    return answer, data
