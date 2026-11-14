#!/usr/bin/env python3
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
"""Reproducible benchmark harness for Oremi Akọrin inference backends.

Two distinct levels are measured and never mixed:

* Level 1 (runtime): raw OpenAI-compatible `/v1/chat/completions` calls against the
  inference server. This isolates the inference runtime (Ollama, SGLang, MAX).
* Level 2 (Oremi): the complete Akọrin request path
  (FastAPI -> Orchestrator -> AgentClient -> backend -> model) driven through the real
  ASGI application, using :class:`akorin.core.agent.AgentClient` for the configured backend.

Oremi's public HTTP contract is non-streaming, so Level 2 reports total response latency
("time to useful result"); TTFT is a Level 1 metric. Results are written as JSON.

Example:
  uv run python scripts/benchmark_backends.py --backend max --base-url http://127.0.0.1:8000 --model qwen2.5:3b --output build/bench/results/max.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import statistics
import subprocess
import time
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any

import httpx2

from akorin.core.app import create_app
from akorin.core.settings import Settings


CHAT_SYSTEM_PROMPT = (
  "You are Oremi, a concise and helpful personal assistant. "
  "Give only the answer intended for the user. Reply in the requested language."
)

LONG_CONTEXT = (
  "Oremi device context: the user is in Deido, Douala, Cameroun (Africa/Douala). "
  "Preferred units are metric, temperature in celsius, distance in kilometers, time format 24h. "
) * 12

STRUCTURED_SCHEMA: dict[str, Any] = {
  "name": "route_decision",
  "strict": True,
  "schema": {
    "type": "object",
    "properties": {
      "service": {"type": "string", "enum": ["isinmi", "ojo", "rediyo", "kansa", "isakoso", "chat"]},
      "confidence": {"type": "number"},
    },
    "required": ["service", "confidence"],
    "additionalProperties": False,
  },
}

TOOL_SCHEMA: list[dict[str, Any]] = [
  {
    "type": "function",
    "function": {
      "name": "get_current_datetime",
      "description": "Get the real current local date and time.",
      "parameters": {
        "type": "object",
        "properties": {"timezone": {"type": "string", "description": "IANA timezone, e.g. Europe/Paris."}},
      },
    },
  }
]

WORKLOADS = ("chat", "structured", "tool", "long_context", "repeated")


@dataclass
class Sample:
  latency_ms: float
  ttft_ms: float | None
  output_tokens: int
  ok: bool
  error: str | None = None


@dataclass
class Sampler:
  """Sample resident memory of the benchmark client and an optional server process."""

  server_pid: int | None = None
  interval: float = 0.2
  peaks_kb: dict[str, int] = field(default_factory=dict)
  _task: asyncio.Task[None] | None = None

  def _read_rss_kb(self, pid: int) -> int | None:
    try:
      with Path(f"/proc/{pid}/status").open() as handle:
        for line in handle:
          if line.startswith("VmRSS:"):
            return int(line.split()[1])
    except OSError:
      return None

    return None

  def _sample(self) -> None:
    for name, pid in (("client", os.getpid()), ("server", self.server_pid)):
      if pid is None:
        continue

      rss = self._read_rss_kb(pid)

      if rss is None:
        continue

      self.peaks_kb[name] = max(self.peaks_kb.get(name, 0), rss)

  async def _run(self) -> None:
    while True:
      self._sample()
      await asyncio.sleep(self.interval)

  async def __aenter__(self) -> "Sampler":
    self._task = asyncio.create_task(self._run())

    return self

  async def __aexit__(self, *exc: object) -> None:
    if self._task is not None:
      self._task.cancel()

      try:
        await self._task
      except asyncio.CancelledError:
        pass


def percentile(values: list[float], percent: float) -> float:
  if not values:
    return float("nan")

  ordered = sorted(values)
  index = (len(ordered) - 1) * percent / 100.0
  lower = int(index)
  upper = min(lower + 1, len(ordered) - 1)
  weight = index - lower

  return ordered[lower] * (1 - weight) + ordered[upper] * weight


def summarize(samples: list[Sample], wall_seconds: float, ok_false: int = 0) -> dict[str, Any]:
  latencies = [s.latency_ms for s in samples]
  ttfts = [s.ttft_ms for s in samples if s.ttft_ms is not None]
  output_tokens = sum(s.output_tokens for s in samples)
  errors = [s for s in samples if not s.ok]
  success = len(samples) - len(errors)

  return {
    "requests": len(samples),
    "successful": success,
    "failed": len(errors),
    "ok_false": ok_false,
    "error_rate": round(len(errors) / len(samples), 4) if samples else 0.0,
    "latency_ms": {
      "min": round(min(latencies), 2) if latencies else None,
      "p50": round(percentile(latencies, 50), 2) if latencies else None,
      "p95": round(percentile(latencies, 95), 2) if latencies else None,
      "p99": round(percentile(latencies, 99), 2) if latencies else None,
      "max": round(max(latencies), 2) if latencies else None,
      "mean": round(statistics.fmean(latencies), 2) if latencies else None,
    },
    "ttft_ms": {
      "min": round(min(ttfts), 2) if ttfts else None,
      "p50": round(percentile(ttfts, 50), 2) if ttfts else None,
      "p95": round(percentile(ttfts, 95), 2) if ttfts else None,
      "p99": round(percentile(ttfts, 99), 2) if ttfts else None,
      "max": round(max(ttfts), 2) if ttfts else None,
      "mean": round(statistics.fmean(ttfts), 2) if ttfts else None,
      "measured": len(ttfts),
    },
    "output_tokens": output_tokens,
    "throughput_rps": round(len(samples) / wall_seconds, 3) if wall_seconds > 0 else None,
    "tokens_per_second": round(output_tokens / wall_seconds, 3) if wall_seconds > 0 else None,
    "wall_seconds": round(wall_seconds, 3),
    "errors": sorted({s.error or "unknown" for s in errors}),
  }


def build_messages(workload: str, index: int) -> list[dict[str, str]]:
  if workload == "chat":
    return [
      {"role": "system", "content": CHAT_SYSTEM_PROMPT},
      {"role": "user", "content": "What is a fun fact about the ocean?"},
    ]

  if workload == "structured":
    return [
      {"role": "system", "content": "Classify the request. Return only the JSON object."},
      {"role": "user", "content": "Allume la lumière du salon."},
    ]

  if workload == "tool":
    return [
      {"role": "system", "content": CHAT_SYSTEM_PROMPT},
      {"role": "user", "content": "What time is it in Paris right now?"},
    ]

  if workload == "long_context":
    return [
      {"role": "system", "content": CHAT_SYSTEM_PROMPT + " Context: " + LONG_CONTEXT},
      {"role": "user", "content": "Given the context, which units should I use?"},
    ]

  return [
    {"role": "system", "content": CHAT_SYSTEM_PROMPT + " Context: " + LONG_CONTEXT},
    {"role": "user", "content": f"Question number {index}: summarize the context in one line."},
  ]


def build_payload(workload: str, model: str, index: int, stream: bool) -> dict[str, Any]:
  payload: dict[str, Any] = {
    "model": model,
    "messages": build_messages(workload, index),
    "temperature": 0.0,
    "max_tokens": 64,
    "stream": stream,
  }

  if workload == "structured":
    payload["response_format"] = {"type": "json_schema", "json_schema": STRUCTURED_SCHEMA}

  if workload == "tool":
    payload["tools"] = TOOL_SCHEMA

  return payload


def uses_streaming(workload: str) -> bool:
  return workload in {"chat", "long_context", "repeated"}


async def runtime_request(
  client: httpx2.AsyncClient,
  url: str,
  workload: str,
  model: str,
  index: int,
  timeout: float,
) -> Sample:
  stream = uses_streaming(workload)
  payload = build_payload(workload, model, index, stream)
  started = time.perf_counter()

  try:
    if stream:
      first_chunk: float | None = None
      text_parts: list[str] = []

      async with client.stream("POST", url, json=payload, timeout=timeout) as response:
        if response.status_code >= 400:
          body = (await response.aread()).decode("utf-8", "replace")
          raise RuntimeError(f"HTTP {response.status_code}: {body[:200]}")

        async for line in response.aiter_lines():
          if not line.startswith("data:"):
            continue

          data = line[5:].strip()

          if data == "[DONE]":
            continue

          chunk = json.loads(data)
          choices = chunk.get("choices") or []

          if not choices:
            continue

          delta = choices[0].get("delta") or {}
          content = delta.get("content")

          if content:
            if first_chunk is None:
              first_chunk = time.perf_counter()

            text_parts.append(content)

      latency_ms = (time.perf_counter() - started) * 1000.0
      ttft_ms = (first_chunk - started) * 1000.0 if first_chunk is not None else None
      output_tokens = max(1, int(len("".join(text_parts).split()) * 1.3))

      return Sample(latency_ms=latency_ms, ttft_ms=ttft_ms, output_tokens=output_tokens, ok=True)

    response = await client.post(url, json=payload, timeout=timeout)
    latency_ms = (time.perf_counter() - started) * 1000.0

    if response.status_code >= 400:
      return Sample(latency_ms=latency_ms, ttft_ms=None, output_tokens=0, ok=False, error=f"HTTP {response.status_code}")

    body = response.json()
    output_tokens = int((body.get("usage") or {}).get("completion_tokens") or 0)

    return Sample(latency_ms=latency_ms, ttft_ms=None, output_tokens=output_tokens, ok=True)
  except Exception as exception:
    latency_ms = (time.perf_counter() - started) * 1000.0

    return Sample(
      latency_ms=latency_ms, ttft_ms=None, output_tokens=0, ok=False, error=f"{type(exception).__name__}: {str(exception)[:120]}"
    )


async def run_concurrent(coro_factory: Any, iterations: int, concurrency: int) -> tuple[list[Sample], float]:
  semaphore = asyncio.Semaphore(concurrency)
  samples: list[Sample] = []
  lock = asyncio.Lock()

  async def worker(index: int) -> None:
    async with semaphore:
      sample = await coro_factory(index)

    async with lock:
      samples.append(sample)

  wall_started = time.perf_counter()
  await asyncio.gather(*(worker(index) for index in range(iterations)))
  wall_seconds = time.perf_counter() - wall_started

  return samples, wall_seconds


async def run_level1(args: argparse.Namespace, workload: str, concurrency: int) -> dict[str, Any]:
  url = args.base_url.rstrip("/") + "/v1/chat/completions"

  async with httpx2.AsyncClient() as client:
    for warmup in range(args.warmup):
      await runtime_request(client, url, workload, args.model, warmup, args.timeout)

    samples, wall_seconds = await run_concurrent(
      lambda index: runtime_request(client, url, workload, args.model, index, args.timeout),
      args.iterations,
      concurrency,
    )

  return summarize(samples, wall_seconds)


def oremi_settings(args: argparse.Namespace) -> Settings:
  root = args.base_url.rstrip("/")
  values: dict[str, Any] = {
    "server_host": "127.0.0.1",
    "server_port": 5020,
    "llm_request_timeout": max(1, min(300, int(args.timeout))),
    "llm_temperature": 0.0,
    "llm_max_response_tokens": 128,
    "llm_cache_enabled": args.app_cache,
    "request_budget_seconds": max(5.0, min(300.0, args.timeout + 5.0)),
    "route_timeout_seconds": max(5.0, min(60.0, args.timeout)),
    "component_circuit_breaker_enabled": False,
    "isinmi_url": None,
    "ojo_url": None,
    "rediyo_url": None,
    "kansa_url": None,
    "isakoso_url": None,
  }

  if args.backend == "ollama":
    values["llm_model"] = f"ollama:{args.model}"
    values["ollama_base_url"] = root
  else:
    values["llm_model"] = args.model
    values["llm_backend"] = args.backend
    values["llm_base_url"] = root + "/v1"

  return Settings(**values)


def oremi_message(workload: str, index: int) -> dict[str, Any]:
  if workload == "tool":
    return {"message": "What time is it in Paris right now?", "context": {"timezone": "Europe/Paris"}}

  if workload == "long_context":
    return {"message": "Given my preferences, which units should I use?", "context": {"preferences": {"temperature_unit": "celsius"}}}

  if workload == "structured":
    return {"message": "Remind me to call Ada tomorrow at 9 AM.", "context": {}}

  if workload == "repeated":
    return {"message": f"Question number {index}: what can you help me with?", "context": {"preferences": {"timezone": "Africa/Douala"}}}

  return {"message": "What is a fun fact about the ocean?", "context": {}}


async def run_level2(args: argparse.Namespace, workload: str, concurrency: int) -> dict[str, Any]:
  settings = oremi_settings(args)
  app = create_app(settings)

  async with app.router.lifespan_context(app):
    transport = httpx2.ASGITransport(app=app)

    async with httpx2.AsyncClient(transport=transport, base_url="http://oremi.test", timeout=args.timeout) as client:

      async def request(index: int) -> Sample:
        payload = oremi_message(workload, index)
        started = time.perf_counter()

        try:
          response = await client.post("/api/agent/", json=payload)
          latency_ms = (time.perf_counter() - started) * 1000.0

          if response.status_code != 200:
            return Sample(latency_ms=latency_ms, ttft_ms=None, output_tokens=0, ok=False, error=f"HTTP {response.status_code}")

          body = response.json()
          ok = bool(body.get("ok", False))
          message = body.get("message") or ""
          output_tokens = max(1, int(len(message.split()) * 1.3))

          return Sample(latency_ms=latency_ms, ttft_ms=None, output_tokens=output_tokens, ok=ok, error=None if ok else "ok=false")
        except Exception as exception:
          latency_ms = (time.perf_counter() - started) * 1000.0

          return Sample(
            latency_ms=latency_ms, ttft_ms=None, output_tokens=0, ok=False, error=f"{type(exception).__name__}: {str(exception)[:120]}"
          )

      for warmup in range(args.warmup):
        await request(warmup)

      samples, wall_seconds = await run_concurrent(request, args.iterations, concurrency)

  return summarize(samples, wall_seconds)


def detect_hardware() -> dict[str, Any]:
  hardware: dict[str, Any] = {
    "platform": platform.platform(),
    "machine": platform.machine(),
    "python": platform.python_version(),
  }

  try:
    with Path("/proc/cpuinfo").open() as handle:
      for line in handle:
        if line.startswith("model name"):
          hardware["cpu"] = line.split(":", 1)[1].strip()
          break
  except OSError:
    hardware["cpu"] = platform.processor()

  try:
    with Path("/proc/meminfo").open() as handle:
      for line in handle:
        if line.startswith("MemTotal:"):
          hardware["memory_gb"] = round(int(line.split()[1]) / 1024 / 1024, 1)
          break
  except OSError:
    pass

  try:
    result = subprocess.run(
      ["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
      capture_output=True,
      text=True,
      timeout=10,
      check=False,
    )
    hardware["gpu"] = result.stdout.strip() or "unavailable"
  except (OSError, subprocess.SubprocessError):
    hardware["gpu"] = "unavailable"

  return hardware


async def main() -> None:
  parser = argparse.ArgumentParser(description="Benchmark Oremi Akọrin inference backends.")
  parser.add_argument("--backend", choices=["ollama", "sglang", "max"], required=True)
  parser.add_argument("--base-url", required=True, help="Server root, e.g. http://127.0.0.1:11434")
  parser.add_argument("--model", required=True, help="Model name served by the backend.")
  parser.add_argument("--runtime-version", default="unknown")
  parser.add_argument("--quantization", default="unknown")
  parser.add_argument("--levels", default="1,2", help="Comma-separated levels to run (1,2).")
  parser.add_argument("--workloads", default=",".join(WORKLOADS))
  parser.add_argument("--concurrency", default="1,2,4", help="Comma-separated concurrency levels.")
  parser.add_argument("--iterations", type=int, default=5)
  parser.add_argument("--warmup", type=int, default=1)
  parser.add_argument("--timeout", type=float, default=180.0)
  parser.add_argument("--app-cache", action="store_true", help="Enable the Oremi SmartCache (disabled by default).")
  parser.add_argument("--server-pid", type=int, default=None, help="Optional inference server PID for memory sampling.")
  parser.add_argument("--output", default=None, help="Write the full JSON report to this path.")
  args = parser.parse_args()

  levels = [int(level) for level in args.levels.split(",")]
  workloads = [workload.strip() for workload in args.workloads.split(",") if workload.strip()]
  concurrency_levels = [int(value) for value in args.concurrency.split(",")]

  report: dict[str, Any] = {
    "meta": {
      "timestamp": datetime.now(timezone.utc).isoformat(),
      "backend": args.backend,
      "base_url": args.base_url,
      "model": args.model,
      "runtime_version": args.runtime_version,
      "quantization": args.quantization,
      "iterations": args.iterations,
      "warmup": args.warmup,
      "timeout_seconds": args.timeout,
      "app_cache": args.app_cache,
      "levels": levels,
      "workloads": workloads,
      "concurrency": concurrency_levels,
      "hardware": detect_hardware(),
    },
    "results": [],
  }

  async with Sampler(server_pid=args.server_pid) as sampler:
    for level in levels:
      for workload in workloads:
        for concurrency in concurrency_levels:
          print(f"[level {level}] workload={workload} concurrency={concurrency} ...", flush=True)

          if level == 1:
            summary = await run_level1(args, workload, concurrency)
          else:
            summary = await run_level2(args, workload, concurrency)

          entry = {"level": level, "workload": workload, "concurrency": concurrency, **summary}
          report["results"].append(entry)
          print(
            f"  p50={summary['latency_ms']['p50']}ms p95={summary['latency_ms']['p95']}ms "
            f"errors={summary['failed']}/{summary['requests']} rps={summary['throughput_rps']}",
            flush=True,
          )

    report["resources"] = {
      "peak_rss_mb": {name: round(kb / 1024, 1) for name, kb in sampler.peaks_kb.items()},
    }

  if args.output:
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2))
    print(f"Report written to {output}")

  print(json.dumps(report["resources"], indent=2))


if __name__ == "__main__":
  asyncio.run(main())
