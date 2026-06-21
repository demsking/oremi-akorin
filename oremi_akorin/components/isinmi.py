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

from pydantic import BaseModel

from ..core.exceptions import ComponentRequestError
from .base import ComponentClient


class NaturalLanguageRequest(BaseModel):
  text: str
  timezone: str
  tags: list[str]


class IsinmiClient(ComponentClient):
  endpoint_path = "/api/agent/message"

  async def process(self, text: str, language: str, context: dict[str, Any], tags: dict[str, str]) -> tuple[str, Any]:
    timezone = context.get("timezone")

    if not timezone:
      raise ComponentRequestError(
        self.name,
        "context.timezone is required",
        message_en="Please specify your timezone so I can schedule this at the correct time.",
        message_fr="Veuillez préciser votre fuseau horaire pour que je puisse programmer cela à la bonne heure.",
      )

    payload = NaturalLanguageRequest(
      text=text,
      timezone=str(timezone),
      tags=[f"{name}:{value}" for name, value in tags.items()],
    )

    data = await self.request_json(
      "POST",
      params={"language": language},
      json=payload.model_dump(),
    )

    return self.parse_response(data)
