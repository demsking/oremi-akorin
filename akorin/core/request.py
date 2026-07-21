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

from pydantic import AliasChoices
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

ProcessRequestContext = dict[str, Any]


class ProcessRequest(BaseModel):
  """Request model for NLP processing."""

  model_config = ConfigDict(str_strip_whitespace=True)

  message: str = Field(
    min_length=1,
    max_length=8000,
    validation_alias=AliasChoices("message", "text"),
    description="Input text to be processed by the NLP system. Must be between 1 and 8000 characters.",
    examples=[
      "What's the weather like in Lagos?",
      "Quel temps fait-il à Paris ?",
      "Play me some Afrobeat music",
      "Joue-moi de l'Afrobeat",
      "What time is it in Lagos?",
      "Quelle heure est-il à Paris ?",
      "Set a reminder for tomorrow at 9 AM",
      "Rappelle-moi demain à 9 h d'appeler maman",
      "Hello, how are you?",
      "Bonjour, comment vas-tu ?",
    ],
  )

  context: ProcessRequestContext = Field(
    default_factory=dict,
    description=(
      "Optional contextual information for the request. Used to maintain "
      "conversation state or provide additional processing context.\n\n"
      "Context carries structured data needed by a service, such as an IANA "
      "timezone, coordinates, temperature unit, or device state. Callers may "
      "also send device preferences under `preferences`; Akọrin selects the "
      "attributes relevant to the routed service before dispatching."
    ),
    examples=[
      {
        "timezone": "Africa/Lagos",
      },
      {
        "preferences": {
          "timezone": "Africa/Douala",
          "latitude": 48.8566,
          "longitude": 2.3522,
          "temperature_unit": "celsius",
          "time_format": "24h",
        },
      },
      {
        "device": {
          "id": "living-room-speaker",
          "location": "Living Room",
        },
      },
    ],
  )

  tags: list[str] = Field(
    default_factory=list,
    description=(
      "Optional tags for request categorization and filtering.\n\n"
      "Tags are free-form client grouping keys used to organize and filter records"
      "across the application. They are stored as normalized JSON arrays and can be"
      "attached to reminders, events, notifications, and chat requests.\n\n"
      "Use tags when you want to group records by values such as:\n"
      "- `device_id:iphone-14`\n"
      "- `device_id:web-app`\n"
      "- `user_id:alex`\n\n"
      "Tag-filtered endpoints match every requested tag, so"
      "`?tags=device_id:iphone-14,user_id:alex` returns only records that carry both"
      "tags."
    ),
    examples=[
      ["device_id:web-app"],
      ["device_id:iphone-14", "user_id:alex"],
      ["room:kitchen", "source:voice"],
    ],
  )
