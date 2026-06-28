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
from ..utils.request_context import contextualized_text


class SearchService:
  def __init__(self, client: httpx.AsyncClient, timeout: float = 10.0) -> None:
    self.client = client
    self.timeout = timeout

  async def process(self, text: str, language: str, context: dict[str, Any], tags: dict[str, str]) -> tuple[str, Any]:
    query = contextualized_text(text, context)

    try:
      response = await request_with_retry(
        lambda: self.client.get(
          "https://api.duckduckgo.com/",
          params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
          timeout=self.timeout,
        ),
        Service.SEARCH.value,
      )

      response.raise_for_status()

      data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
      raise ComponentUnavailable(Service.SEARCH, str(exc)) from exc

    answer = data.get("Answer") or data.get("AbstractText")
    source_url = data.get("AbstractURL")
    source_name = data.get("AbstractSource") or "DuckDuckGo"

    if not answer:
      topics = data.get("RelatedTopics") or []
      results = list(self._topic_results(topics))
      first = results[0] if results else None
      answer = first.get("text") if first else None
      source_url = first.get("url") if first else None
    else:
      results = list(self._topic_results(data.get("RelatedTopics") or []))

    if not answer:
      answer = "No direct result was found." if language == "en" else "Aucun résultat direct n'a été trouvé."

    result = {
      "source": source_name,
      "url": source_url,
      "heading": data.get("Heading") or None,
      "results": results[:5],
    }

    return str(answer).strip(), result

  @classmethod
  def _topic_results(cls, topics: list[Any]):
    for item in topics:
      if not isinstance(item, dict):
        continue

      if item.get("Text"):
        yield {"text": str(item["Text"]).strip(), "url": item.get("FirstURL")}

      nested = item.get("Topics")

      if isinstance(nested, list):
        yield from cls._topic_results(nested)
