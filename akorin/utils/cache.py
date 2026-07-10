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

import copy
import hashlib
import json
import logging
from collections import OrderedDict
from collections.abc import Awaitable
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic
from typing import Any
from typing import TypeVar


logger = logging.getLogger(__name__)

T = TypeVar("T")
VOLATILE_CONTEXT_KEYS = frozenset(("datetime", "date", "time", "timestamp", "now"))


@dataclass(slots=True)
class CacheEntry:
  expires_at: float
  value: Any


class SmartCache:
  """Bounded in-memory cache for repeated internal request work."""

  def __init__(self, *, enabled: bool, max_entries: int, clock: Callable[[], float] = monotonic) -> None:
    self.enabled = enabled and max_entries > 0
    self.max_entries = max_entries
    self._clock = clock
    self._entries: OrderedDict[str, CacheEntry] = OrderedDict()

  @property
  def size(self) -> int:
    return len(self._entries)

  def make_key(self, namespace: str, payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(raw.encode()).hexdigest()

    return f"{namespace}:{digest}"

  def get(self, key: str) -> Any | None:
    if not self.enabled:
      return None

    entry = self._entries.get(key)

    if entry is None:
      return None

    if entry.expires_at <= self._clock():
      self._entries.pop(key, None)
      logger.debug("Smart cache expired: key=%s", key)

      return None

    self._entries.move_to_end(key)
    logger.debug("Smart cache hit: key=%s", key)

    return copy.deepcopy(entry.value)

  def set(self, key: str, value: Any, ttl_seconds: float) -> None:
    if not self.enabled or ttl_seconds <= 0:
      return

    self._entries[key] = CacheEntry(expires_at=self._clock() + ttl_seconds, value=copy.deepcopy(value))
    self._entries.move_to_end(key)

    while len(self._entries) > self.max_entries:
      self._entries.popitem(last=False)

    logger.debug("Smart cache stored: key=%s ttl_seconds=%s size=%s", key, ttl_seconds, len(self._entries))

  async def get_or_set(self, key: str, ttl_seconds: float, factory: Callable[[], Awaitable[T]]) -> T:
    cached = self.get(key)

    if cached is not None:
      return cached

    value = await factory()
    self.set(key, value, ttl_seconds)

    return value


def has_volatile_context(value: Any) -> bool:
  if isinstance(value, dict):
    for key, item in value.items():
      if str(key).casefold() in VOLATILE_CONTEXT_KEYS:
        return True

      if has_volatile_context(item):
        return True

  if isinstance(value, list):
    return any(has_volatile_context(item) for item in value)

  return False
