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

import asyncio
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
  stale_until: float
  value: Any


@dataclass(frozen=True, slots=True)
class CacheStats:
  hits: int = 0
  misses: int = 0
  stale_hits: int = 0
  stores: int = 0
  evictions: int = 0
  singleflight_waits: int = 0
  refreshes: int = 0


class SmartCache:
  """Bounded in-memory cache for repeated internal request work."""

  def __init__(self, *, enabled: bool, max_entries: int, clock: Callable[[], float] = monotonic) -> None:
    self.enabled = enabled and max_entries > 0
    self.max_entries = max_entries
    self._clock = clock
    self._entries: OrderedDict[str, CacheEntry] = OrderedDict()
    self._inflight: dict[str, asyncio.Task[Any]] = {}
    self._refreshing: set[str] = set()
    self._background_tasks: set[asyncio.Task[None]] = set()
    self._stats = CacheStats()

  @property
  def size(self) -> int:
    return len(self._entries)

  @property
  def stats(self) -> CacheStats:
    return self._stats

  def make_key(self, namespace: str, payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(raw.encode()).hexdigest()

    return f"{namespace}:{digest}"

  def get(self, key: str) -> Any | None:
    if not self.enabled:
      return None

    entry = self._entries.get(key)

    if entry is None:
      self._record(misses=1)
      return None

    if entry.expires_at <= self._clock():
      logger.debug("Smart cache expired: key=%s", key)
      self._record(misses=1)
      self._entries.pop(key, None)
      return None

    self._entries.move_to_end(key)
    logger.debug("Smart cache hit: key=%s", key)
    self._record(hits=1)

    return copy.deepcopy(entry.value)

  def get_stale(self, key: str) -> Any | None:
    if not self.enabled:
      return None

    entry = self._entries.get(key)

    if entry is None or entry.stale_until <= self._clock():
      return None

    self._entries.move_to_end(key)
    logger.debug("Smart cache stale hit: key=%s", key)
    self._record(stale_hits=1)

    return copy.deepcopy(entry.value)

  def set(self, key: str, value: Any, ttl_seconds: float, *, stale_seconds: float = 0.0) -> None:
    if not self.enabled or ttl_seconds <= 0:
      return

    expires_at = self._clock() + ttl_seconds
    self._entries[key] = CacheEntry(
      expires_at=expires_at,
      stale_until=expires_at + max(stale_seconds, 0.0),
      value=copy.deepcopy(value),
    )
    self._entries.move_to_end(key)
    self._record(stores=1)

    while len(self._entries) > self.max_entries:
      self._entries.popitem(last=False)
      self._record(evictions=1)

    logger.debug("Smart cache stored: key=%s ttl_seconds=%s size=%s", key, ttl_seconds, len(self._entries))

  async def get_or_set(self, key: str, ttl_seconds: float, factory: Callable[[], Awaitable[T]]) -> T:
    cached = self.get(key)

    if cached is not None:
      return cached

    if key in self._entries:
      return self._entries[key].value  # type: ignore[return-value]

    value = await self._singleflight(key, factory)
    self.set(key, value, ttl_seconds)

    return value

  async def get_or_set_stale(
    self,
    key: str,
    ttl_seconds: float,
    stale_seconds: float,
    factory: Callable[[], Awaitable[T]],
  ) -> T:
    cached = self.get(key)

    if cached is not None:
      return cached

    stale = self.get_stale(key)

    if stale is not None:
      self.refresh(key, ttl_seconds, stale_seconds, factory)

      return stale

    value = await self._singleflight(key, factory)
    self.set(key, value, ttl_seconds, stale_seconds=stale_seconds)

    return value

  def refresh(
    self,
    key: str,
    ttl_seconds: float,
    stale_seconds: float,
    factory: Callable[[], Awaitable[T]],
  ) -> None:
    if not self.enabled or key in self._refreshing:
      return

    self._refreshing.add(key)
    self._record(refreshes=1)

    async def refresh_cache() -> None:
      try:
        value = await self._singleflight(key, factory)
        self.set(key, value, ttl_seconds, stale_seconds=stale_seconds)
      except Exception as exception:
        logger.debug("Smart cache background refresh failed: key=%s error=%s", key, exception)
      finally:
        self._refreshing.discard(key)

    task = asyncio.create_task(refresh_cache())
    self._background_tasks.add(task)
    task.add_done_callback(self._background_tasks.discard)

  async def _singleflight(self, key: str, factory: Callable[[], Awaitable[T]]) -> T:
    if not self.enabled:
      return await factory()

    task = self._inflight.get(key)

    if task is not None:
      self._record(singleflight_waits=1)
      return await task

    task = asyncio.create_task(factory())  # pyright: ignore
    self._inflight[key] = task

    try:
      return await task
    finally:
      if self._inflight.get(key) is task:
        self._inflight.pop(key, None)

  def _record(
    self,
    *,
    hits: int = 0,
    misses: int = 0,
    stale_hits: int = 0,
    stores: int = 0,
    evictions: int = 0,
    singleflight_waits: int = 0,
    refreshes: int = 0,
  ) -> None:
    self._stats = CacheStats(
      hits=self._stats.hits + hits,
      misses=self._stats.misses + misses,
      stale_hits=self._stats.stale_hits + stale_hits,
      stores=self._stats.stores + stores,
      evictions=self._stats.evictions + evictions,
      singleflight_waits=self._stats.singleflight_waits + singleflight_waits,
      refreshes=self._stats.refreshes + refreshes,
    )


def has_volatile_context(value: Any) -> bool:
  if isinstance(value, dict):
    for key, item in value.items():
      if str(key).casefold() in VOLATILE_CONTEXT_KEYS:
        return True

      if has_volatile_context(item):
        return True

  if isinstance(value, list):
    return any(has_volatile_context(item) for item in value)

  if isinstance(value, str):
    lowered = value.casefold()

    return any(f'"{key}":' in lowered or f"{key}=" in lowered for key in VOLATILE_CONTEXT_KEYS)

  return False
