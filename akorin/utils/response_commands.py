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
from typing import Any

from pydantic import ValidationError

from akorin.core.response import AlarmCommand
from akorin.core.response import CancelScheduledCommand
from akorin.core.response import OremiDeviceCommand
from akorin.core.response import PlayCommand
from akorin.core.response import ProcessResponse
from akorin.core.response import ReminderCommand
from akorin.core.response import SpeakCommand
from akorin.core.service import Service


logger = logging.getLogger(__name__)


def select_device_commands(response: ProcessResponse) -> list[OremiDeviceCommand]:
  """Translate a successful service result into ordered Oremi Device commands."""
  if not response.ok or not isinstance(response.data, dict):
    return []

  try:
    if response.service == Service.OREMI_REDIYO:
      return _media_commands(response.message, _nested(response.data, "station", "url"))

    if response.service == Service.OREMI_KANSA:
      episodes = _nested(response.data, "podcast", "episodes")
      media_url = episodes[0].get("media_url") if isinstance(episodes, list) and episodes else None

      return _media_commands(response.message, media_url)

    if response.service == Service.OREMI_ISINMI:
      return _schedule_commands(response.message, response.data)
  except (TypeError, ValidationError, ValueError) as exception:
    logger.warning(f"Could not select Oremi Device commands for {response.service}: {exception}")

  return []


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
