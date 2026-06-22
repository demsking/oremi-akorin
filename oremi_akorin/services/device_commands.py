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
import re
from typing import Any

from pydantic import ValidationError

from ..core.constants import Language
from ..core.constants import Service
from ..core.logger import logger
from ..core.models import AlarmCommand
from ..core.models import CancelScheduledCommand
from ..core.models import MuteCommand
from ..core.models import OremiDeviceCommand
from ..core.models import PauseCommand
from ..core.models import PlayCommand
from ..core.models import ProcessResponse
from ..core.models import ReminderCommand
from ..core.models import ResumeCommand
from ..core.models import SetVoiceCommand
from ..core.models import SetVolumeCommand
from ..core.models import SpeakCommand
from ..core.models import StopCommand

_VOLUME_PATTERN = re.compile(
  r"^(?:set|change|turn) (?:the )?volume(?: (?:to|at))? (?P<volume>\d{1,3})(?:\s*%)?$"
  r"|^(?:mets?|règle|regle) (?:le )?volume(?: (?:à|a|sur))? (?P<volume_fr>\d{1,3})(?:\s*%)?$",
  re.IGNORECASE,
)
_VOICE_PATTERN = re.compile(
  r"^(?:set|change|use) (?:the )?voice(?: (?:to|as))? (?P<voice>[^.?!]+)$"
  r"|^(?:mets?|utilise|choisis) (?:la )?voix(?: (?:de|à|a))? (?P<voice_fr>[^.?!]+)$",
  re.IGNORECASE,
)


def select_device_commands(response: ProcessResponse) -> list[OremiDeviceCommand]:
  """Translate a successful service result into ordered Oremi Device commands."""
  if not response.ok or not isinstance(response.data, dict):
    return []

  try:
    if response.service == Service.REDIYO:
      return _media_commands(response.message, _nested(response.data, "station", "url"))

    if response.service == Service.KANSA:
      episodes = _nested(response.data, "podcast", "episodes")
      media_url = episodes[0].get("media_url") if isinstance(episodes, list) and episodes else None
      return _media_commands(response.message, media_url)

    if response.service == Service.ISINMI:
      return _schedule_commands(response.message, response.data)
  except (TypeError, ValidationError, ValueError) as exception:
    logger.warning(f"Could not select Oremi Device commands for {response.service}: {exception}")

  return []


def select_direct_device_command(text: str, language: Language) -> tuple[str, OremiDeviceCommand] | None:  # pylint: disable=too-many-return-statements
  """Recognize device-local controls that should bypass conversational processing."""
  normalized = " ".join(text.strip().split()).casefold().rstrip(".!?")
  messages = _DIRECT_MESSAGES[language]

  volume_match = _VOLUME_PATTERN.fullmatch(normalized)

  if volume_match:
    volume = int(volume_match.group("volume") or volume_match.group("volume_fr"))

    if not 0 <= volume <= 100:
      return None

    return messages["volume"].format(volume=volume), SetVolumeCommand(volume=volume)

  voice_match = _VOICE_PATTERN.fullmatch(text.strip())

  if voice_match:
    voice = (voice_match.group("voice") or voice_match.group("voice_fr")).strip()

    return messages["voice"].format(voice=voice), SetVoiceCommand(voice=voice)

  if normalized in {"pause", "pause playback", "pause the music", "pause the radio", "mets en pause", "met en pause"}:
    return messages["pause"], PauseCommand()

  if normalized in {
    "resume",
    "resume playback",
    "resume the music",
    "resume the radio",
    "continue",
    "reprends",
    "reprend",
    "reprends la lecture",
  }:
    return messages["resume"], ResumeCommand()

  if normalized in {
    "stop",
    "stop playback",
    "stop the music",
    "stop the radio",
    "arrête",
    "arrete",
    "arrête la lecture",
    "arrete la lecture",
    "arrête la musique",
    "arrete la musique",
  }:
    return messages["stop"], StopCommand()

  if normalized in {"mute", "mute the sound", "coupe le son", "mode silencieux"}:
    return messages["mute"], MuteCommand(muted=True)

  if normalized in {"unmute", "unmute the sound", "remets le son", "réactive le son", "reactive le son"}:
    return messages["unmute"], MuteCommand(muted=False)

  return None


_DIRECT_MESSAGES = {
  Language.EN: {
    "pause": "Playback paused.",
    "resume": "Playback resumed.",
    "stop": "Playback stopped.",
    "mute": "Sound muted.",
    "unmute": "Sound unmuted.",
    "volume": "Volume set to {volume} percent.",
    "voice": "Voice set to {voice}.",
  },
  Language.FR: {
    "pause": "Lecture mise en pause.",
    "resume": "Lecture reprise.",
    "stop": "Lecture arrêtée.",
    "mute": "Son coupé.",
    "unmute": "Son réactivé.",
    "volume": "Volume réglé à {volume} pour cent.",
    "voice": "Voix réglée sur {voice}.",
  },
}


def _media_commands(message: str, url: Any) -> list[OremiDeviceCommand]:
  if not isinstance(url, str) or not url:
    return []

  return [SpeakCommand(text=message), PlayCommand(url=url)]  # type: ignore


def _schedule_commands(message: str, data: dict[str, Any]) -> list[OremiDeviceCommand]:
  action = data.get("action")
  schedule_id = data.get("id")

  if action == "delete" and schedule_id:
    return [SpeakCommand(text=message), CancelScheduledCommand(id=str(schedule_id))]

  if action not in {"create", "update"} or not schedule_id:
    return []

  schedule = data.get("data")
  if not isinstance(schedule, dict):
    return []

  schedule_type = data.get("type") or schedule.get("type")
  scheduled_at = schedule.get("scheduled_time") or schedule.get("time")
  label = str(schedule.get("label") or message)

  if schedule_type == "reminder":
    command: OremiDeviceCommand = ReminderCommand(
      id=str(schedule_id),
      at=scheduled_at,  # type: ignore
      message=label,
    )
  elif schedule_type in {"alarm", "timer"}:
    command = AlarmCommand(
      id=str(schedule_id),
      at=scheduled_at,  # type: ignore
      message=label,
    )
  else:
    return []

  return [SpeakCommand(text=message), command]


def _nested(data: dict[str, Any], *path: str) -> Any:
  value: Any = data
  for key in path:
    if not isinstance(value, dict):
      return None
    value = value.get(key)
  return value
