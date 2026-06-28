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
from ..core.exceptions import NoResultFound
from ..utils.http_retry import request_with_retry
from ..utils.request_context import contextualized_text

USER_AGENT = "oremi-akorin/1.0 (https://gitlab.com/demsking/oremi-akorin)"


class WikipediaService:
  def __init__(self, client: httpx.AsyncClient) -> None:
    self.client = client

  async def process(self, text: str, language: str, context: dict[str, Any], tags: dict[str, str]) -> tuple[str, Any]:
    wiki_language = language if language in {"en", "fr"} else "en"
    search_text = contextualized_text(text, context)

    try:
      response = await request_with_retry(
        lambda: self.client.get(
          f"https://{wiki_language}.wikipedia.org/w/api.php",
          params={
            "action": "query",
            "generator": "search",
            "gsrsearch": search_text,
            "gsrlimit": 1,
            "prop": "extracts|info",
            "exintro": 1,
            "exsentences": 3,
            "explaintext": 1,
            "inprop": "url",
            "format": "json",
            "formatversion": 2,
          },
          headers={"User-Agent": USER_AGENT},
        ),
        Service.WIKIPEDIA.value,
      )

      response.raise_for_status()

      data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
      raise ComponentUnavailable(Service.WIKIPEDIA, str(exc)) from exc

    pages = data.get("query", {}).get("pages", [])
    page = pages[0] if pages else None

    if not page or not page.get("extract"):
      raise NoResultFound(Service.WIKIPEDIA)

    result = {
      "source": "Wikipedia",
      "title": page.get("title"),
      "url": page.get("fullurl"),
      "language": wiki_language,
      "license": "CC BY-SA",
    }

    return str(page["extract"]).strip(), result
