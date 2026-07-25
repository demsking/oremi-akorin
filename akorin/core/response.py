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
from typing import Annotated
from typing import Any
from typing import Literal

from pydantic import AnyHttpUrl
from pydantic import AwareDatetime
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from akorin.core.service import Service
from akorin.utils.language import Language


logger = logging.getLogger(__name__)


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
  id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
  at: AwareDatetime
  message: str | None = None
  url: AnyHttpUrl | None = None
  voice: str | None = None


class ReminderCommand(DeviceCommand):
  type: Literal["reminder"] = "reminder"
  id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
  at: AwareDatetime
  message: str = Field(min_length=1)
  voice: str | None = None


class CancelScheduledCommand(DeviceCommand):
  type: Literal["cancel_scheduled"] = "cancel_scheduled"
  id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


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

  ok: bool = Field(default=True, description="Indicates whether the processing was successful.")
  input: str = Field(description="Original input text that was processed.")
  language: Language = Field(description="Detected language of the input text in ISO 639-1 format.")
  service: Service = Field(description="Service that handled the request (e.g., 'chat', 'tool', or external service).")
  message: str = Field(description="Human-readable response message containing the processing result or error details.")
  data: dict[str, Any] | None = Field(
    default=None,
    description="Additional structured data from the processing. Content varies based on the service and request type.",
  )
  confidence: float = Field(
    ge=0, le=1, description="Confidence score for the response, ranging from 0.0 (lowest) to 1.0 (highest)."
  )
  commands: list[OremiDeviceCommand] = Field(
    default_factory=list,
    description="Ordered commands selected by Akọrin for the requesting Oremi Device node.",
  )

  def __str__(self) -> str:
    return (
      f"Response("
      f"ok={self.ok}, "
      f"input={self.input}, "
      f"language={self.language}, "
      f"service={self.service.value}, "
      f"message={self.message or 'None'}, "
      f"data={list(self.data.keys()) if self.data else None}, "
      f"confidence={self.confidence}, "
      f"commands={len(self.commands)}"
      f")"
    )
