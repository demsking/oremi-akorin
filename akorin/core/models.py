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
from typing import Annotated
from typing import Any
from typing import Literal

from pydantic import AliasChoices
from pydantic import AnyHttpUrl
from pydantic import AwareDatetime
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from .constants import Language
from .constants import Service


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
      "Who is the president of Nigeria?",
      "Qui est le président du Nigeria ?",
      "Set a reminder for tomorrow at 9 AM",
      "Rappelle-moi demain à 9 h d'appeler maman",
      "Hello, how are you?",
      "Bonjour, comment vas-tu ?",
    ],
  )

  language: Language | None = Field(
    default=None, description="Optional language code for the input text. If not provided, will be auto-detected."
  )

  context: dict[str, Any] = Field(
    default_factory=dict,
    description=(
      "Optional contextual information for the request. Used to maintain "
      "conversation state or provide additional processing context.\n\n"
      "Context carries structured data needed by a service, such as an IANA "
      "timezone, coordinates, temperature unit, or device state."
    ),
    examples=[
      {
        "timezone": "Africa/Lagos",
      },
      {
        "timezone": "Europe/Paris",
        "latitude": 48.8566,
        "longitude": 2.3522,
        "temperature_unit": "celsius",
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
      "Optional key-value tags for request categorization and filtering.\n\n"
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


class DeviceCommand(BaseModel):
  """Base model for commands understood by Oremi Device."""

  model_config = ConfigDict(extra="forbid")


class SpeakCommand(DeviceCommand):
  type: Literal["speak"] = "speak"
  text: str = Field(min_length=1)
  voice: str | None = None


class AnnounceCommand(DeviceCommand):
  type: Literal["announce"] = "announce"
  text: str = Field(min_length=1)
  voice: str | None = None


class PlayCommand(DeviceCommand):
  type: Literal["play"] = "play"
  url: AnyHttpUrl


class PauseCommand(DeviceCommand):
  type: Literal["pause"] = "pause"


class ResumeCommand(DeviceCommand):
  type: Literal["resume"] = "resume"


class StopCommand(DeviceCommand):
  type: Literal["stop"] = "stop"


class AlarmCommand(DeviceCommand):
  type: Literal["alarm"] = "alarm"
  id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")  # pylint: disable=invalid-name
  at: AwareDatetime  # pylint: disable=invalid-name
  message: str | None = None
  url: AnyHttpUrl | None = None
  voice: str | None = None


class ReminderCommand(DeviceCommand):
  type: Literal["reminder"] = "reminder"
  id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")  # pylint: disable=invalid-name
  at: AwareDatetime  # pylint: disable=invalid-name
  message: str = Field(min_length=1)
  voice: str | None = None


class CancelScheduledCommand(DeviceCommand):
  type: Literal["cancel_scheduled"] = "cancel_scheduled"
  id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")  # pylint: disable=invalid-name


class SetVolumeCommand(DeviceCommand):
  type: Literal["set_volume"] = "set_volume"
  volume: int = Field(ge=0, le=100)


class MuteCommand(DeviceCommand):
  type: Literal["mute"] = "mute"
  muted: bool


class SetVoiceCommand(DeviceCommand):
  type: Literal["set_voice"] = "set_voice"
  voice: str = Field(min_length=1)


OremiDeviceCommand = Annotated[
  SpeakCommand
  | AnnounceCommand
  | PlayCommand
  | PauseCommand
  | ResumeCommand
  | StopCommand
  | AlarmCommand
  | ReminderCommand
  | CancelScheduledCommand
  | SetVolumeCommand
  | MuteCommand
  | SetVoiceCommand,
  Field(discriminator="type"),
]


class ProcessResponse(BaseModel):
  """Response model for NLP processing results."""

  ok: bool = Field(default=True, description="Indicates whether the processing was successful.")  # pylint: disable=invalid-name
  input: str = Field(description="Original input text that was processed.")
  language: Language = Field(description="Detected or specified language of the input text.")
  service: Service = Field(description="Service that handled the request (e.g., 'ollama', 'search', or external service).")
  message: str = Field(description="Human-readable response message containing the processing result or error details.")
  data: Any = Field(
    default_factory=dict,
    description="Additional structured data from the processing. Content varies based on the service and request type.",
  )
  confidence: float = Field(
    ge=0, le=1, description="Confidence score for the response, ranging from 0.0 (lowest) to 1.0 (highest)."
  )
  commands: list[OremiDeviceCommand] = Field(
    default_factory=list,
    description="Ordered commands selected by Akọrin for the requesting Oremi Device node.",
  )
