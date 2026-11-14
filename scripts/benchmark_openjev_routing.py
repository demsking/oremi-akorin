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
"""Reproducible benchmark: Oremi LLM semantic routing vs OpenJev + SGLang.

Three measurements, never mixed:

* baseline - the existing SemanticRouter -> CommandAgent -> SGLang
  /v1/chat/completions structured-output classification.
* openjev  - the OpenJev /v1/systemone one-token-logprob choice
  classification, called directly.
* e2e      - the full Oremi request path (FastAPI -> Orchestrator -> routers ->
  AgentClient -> SGLang) with and without the OpenJev router enabled.

Routing quality is computed against the project's own representative examples
(akorin.api.agent.PAYLOAD_EXAMPLES plus the mapping used by tests/test_llm.py),
extended with ambiguous, no-match, short, long and multilingual cases. Quality
is never traded for latency.

Example:
  uv run python scripts/benchmark_openjev_routing.py --output build/bench/results/openjev-routing.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
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

from akorin.agents.command_agent import CommandAgent
from akorin.api.agent import PAYLOAD_EXAMPLES
from akorin.core.app import create_app
from akorin.core.request import ProcessRequest
from akorin.core.router import RouteContext
from akorin.core.service import Service
from akorin.core.settings import Settings
from akorin.routers.openjev import ROUTING_INSTRUCTIONS
from akorin.routers.openjev import ROUTING_LABELS
from akorin.routers.openjev import SERVICE_DESCRIPTIONS
from akorin.routers.semantic_router import SemanticRouter


# Mirrors tests/test_llm.py::test_command_agent_classifies_all_payload_examples.
EXPECTED_BY_EXAMPLE: dict[str, Service] = {
  "Weather forecast (EN)": Service.OREMI_OJO,
  "Météo (FR)": Service.OREMI_OJO,
  "Weather with Oremi Device context": Service.OREMI_OJO,
  "Pollen count (EN)": Service.OREMI_OJO,
  "Alerte Pollen (FR)": Service.OREMI_OJO,
  "Zigbee device command": Service.OREMI_ISAKOSO,
  "Control Zigbee device (EN)": Service.OREMI_ISAKOSO,
  "Contrôler un appareil Zigbee (FR)": Service.OREMI_ISAKOSO,
  "Allumer la lumière de la chambre (FR)": Service.OREMI_ISAKOSO,
  "Éteindre la lumière de la chambre (FR)": Service.OREMI_ISAKOSO,
  "Quelle heure est-il ? (FR)": Service.CHAT,
  "General Chat (EN)": Service.CHAT,
  "Discussion générale (FR)": Service.CHAT,
  "Set a reminder (EN)": Service.OREMI_ISINMI,
  "Créer un rappel (FR)": Service.OREMI_ISINMI,
  "Créer un rappel avec un context élargie (FR)": Service.OREMI_ISINMI,
  "Schedule recurring event (EN)": Service.OREMI_ISINMI,
  "Planifier un événement (FR)": Service.OREMI_ISINMI,
  "Play Radio (EN)": Service.OREMI_REDIYO,
  "Lancer la radio (FR)": Service.OREMI_REDIYO,
  "Play Podcast (EN)": Service.OREMI_KANSA,
  "Lancer un podcast (FR)": Service.OREMI_KANSA,
}

# Extra cases exercising the workload families the task requires.
EXTRA_CASES: list[tuple[str, str, Service, str]] = [
  ("ambig-radio-device", "Turn on the radio in the kitchen", Service.OREMI_ISAKOSO, "ambiguous"),
  ("ambig-rain-reminder", "Remind me when it will rain tomorrow", Service.OREMI_ISINMI, "ambiguous"),
  ("ambig-alarm-weather", "Set an alarm if the weather turns bad", Service.OREMI_ISINMI, "ambiguous"),
  ("ambig-play-music", "Play some music", Service.OREMI_REDIYO, "ambiguous"),
  ("nomatch-joke", "Tell me a joke about programmers", Service.CHAT, "no_match"),
  ("nomatch-capital", "What is the capital of France?", Service.CHAT, "no_match"),
  ("nomatch-explain", "Explain how a transistor works", Service.CHAT, "no_match"),
  ("short-lights-on", "Turn on the lights.", Service.OREMI_ISAKOSO, "short"),
  ("short-lights-off", "Lights off.", Service.OREMI_ISAKOSO, "short"),
  ("short-weather", "Weather?", Service.OREMI_OJO, "short"),
  ("short-remind", "Remind me at 8.", Service.OREMI_ISINMI, "short"),
  ("mcp-podcast-fr", "Trouve-moi un podcast sur l'histoire", Service.OREMI_KANSA, "mcp"),
  ("mcp-radio-fr", "Mets une station de jazz", Service.OREMI_REDIYO, "mcp"),
  ("multi-en-weather", "Is it going to rain in Douala this week?", Service.OREMI_OJO, "multilingual"),
  ("multi-fr-lights", "Peux-tu éteindre les lampes du salon ?", Service.OREMI_ISAKOSO, "multilingual"),
  (
    "long-context-reminder",
    "Je suis à Douala, il est 19h et je prépare le dîner. Peux-tu me rappeler d'arroser les plantes "
    "demain soir à 19h et de sortir les poubelles à 20h ?",
    Service.OREMI_ISINMI,
    "long",
  ),
  (
    "long-context-weather",
    "I am in Deido, Douala, Cameroon. The temperature unit is celsius and I use the metric system. "
    "Given my location and preferences, what is the weather and air quality like right now?",
    Service.OREMI_OJO,
    "long",
  ),
]


@dataclass(frozen=True)
class Case:
  name: str
  message: str
  expected: str
  kind: str
  context: dict[str, Any] = field(default_factory=dict)


@dataclass
class Record:
  case: Case
  level: str
  concurrency: int
  latency_ms: float
  ok: bool
  predicted: str | None = None
  confidence: float | None = None
  probabilities: dict[str, float] = field(default_factory=dict)
  fallback: bool = False
  detail: str | None = None
  server_timing: str | None = None
  cached_tokens: str | None = None


def percentile(values: list[float], percent: float) -> float:
  if not values:
    return float("nan")

  ordered = sorted(values)
  index = (len(ordered) - 1) * percent / 100.0
  lower = int(index)
  upper = min(lower + 1, len(ordered) - 1)
  weight = index - lower

  return ordered[lower] * (1 - weight) + ordered[upper] * weight


def build_cases() -> list[Case]:
  cases: list[Case] = []

  for name, example in PAYLOAD_EXAMPLES.items():
    expected = EXPECTED_BY_EXAMPLE.get(name)

    if expected is None:
      continue

    cases.append(
      Case(
        name=name,
        message=example["value"].message,
        expected=expected.value,
        kind="mcp" if expected not in {Service.CHAT} else "clear",
        context=example["value"].context,
      )
    )

  for name, message, expected, kind in EXTRA_CASES:
    cases.append(Case(name=name, message=message, expected=expected.value, kind=kind))

  return cases


def summarize_latency(records: list[Record], wall_seconds: float) -> dict[str, Any]:
  latencies = [record.latency_ms for record in records if record.ok]
  failures = [record for record in records if not record.ok]

  return {
    "requests": len(records),
    "successful": len(latencies),
    "failed": len(failures),
    "error_rate": round(len(failures) / len(records), 4) if records else 0.0,
    "latency_ms": {
      "min": round(min(latencies), 2) if latencies else None,
      "p50": round(percentile(latencies, 50), 2) if latencies else None,
      "p95": round(percentile(latencies, 95), 2) if latencies else None,
      "p99": round(percentile(latencies, 99), 2) if latencies else None,
      "max": round(max(latencies), 2) if latencies else None,
      "mean": round(statistics.fmean(latencies), 2) if latencies else None,
    },
    "throughput_rps": round(len(records) / wall_seconds, 3) if wall_seconds > 0 else None,
    "wall_seconds": round(wall_seconds, 3),
    "errors": sorted({record.detail or "unknown" for record in failures})[:10],
  }


def quality(records: list[Record], threshold: float | None = None) -> dict[str, Any]:
  considered = []
  fallbacks = 0

  for record in records:
    if not record.ok:
      continue

    if threshold is not None and record.confidence is not None and record.confidence < threshold:
      fallbacks += 1
      continue

    considered.append(record)

  total = len(considered)
  correct = sum(1 for record in considered if record.predicted == record.case.expected)
  per_route: dict[str, dict[str, int]] = {}
  false_positives: dict[str, int] = {}
  false_negatives: dict[str, int] = {}

  for record in considered:
    expected_bucket = per_route.setdefault(record.case.expected, {"total": 0, "correct": 0})
    expected_bucket["total"] += 1

    if record.predicted == record.case.expected:
      expected_bucket["correct"] += 1
    else:
      false_negatives[record.case.expected] = false_negatives.get(record.case.expected, 0) + 1

      if record.predicted:
        false_positives[record.predicted] = false_positives.get(record.predicted, 0) + 1

  confidences = [record.confidence for record in considered if record.confidence is not None]
  evaluated = total + fallbacks

  return {
    "threshold": threshold,
    "evaluated": evaluated,
    "accepted": total,
    "accuracy": round(correct / total, 4) if total else None,
    "fallback_rate": round(fallbacks / evaluated, 4) if evaluated else None,
    "false_positive": sum(false_positives.values()),
    "false_negative": sum(false_negatives.values()),
    "false_positives_by_route": false_positives,
    "false_negatives_by_route": false_negatives,
    "per_route_accuracy": {
      route: round(bucket["correct"] / bucket["total"], 4) for route, bucket in sorted(per_route.items())
    },
    "confidence": {
      "mean": round(statistics.fmean(confidences), 4) if confidences else None,
      "min": round(min(confidences), 4) if confidences else None,
      "p50": round(percentile(confidences, 50), 4) if confidences else None,
    },
  }


async def openjev_classify(
  client: httpx2.AsyncClient,
  url: str,
  model: str,
  text: str,
  timeout: float,
) -> tuple[str, float, dict[str, float], str | None, str | None]:
  criteria = {service.value: SERVICE_DESCRIPTIONS[service] for service in ROUTING_LABELS}
  payload = {
    "model": model,
    "state": text,
    "questions": {
      "routing": {
        "type": "choice",
        "instructions": ROUTING_INSTRUCTIONS,
        "criteria": criteria,
      }
    },
  }

  response = await client.post(f"{url.rstrip('/')}/v1/systemone", json=payload, timeout=timeout)

  if response.status_code >= 400:
    raise RuntimeError(f"OpenJev HTTP {response.status_code}")

  body = response.json()
  answer = body["answers"]["routing"]

  if answer.get("type") != "choice":
    raise RuntimeError(f"unexpected answer type {answer.get('type')!r}")

  return (
    str(answer["choice"]),
    float(answer["confidence"]),
    {str(key): float(value) for key, value in (answer.get("probabilities") or {}).items()},
    response.headers.get("server-timing"),
    response.headers.get("x-openjev-cached-tokens") or response.headers.get("x-openjev-prefix-tokens"),
  )


async def run_openjev_level(
  cases: list[Case],
  url: str,
  model: str,
  concurrency: int,
  repeats: int,
  timeout: float,
) -> tuple[list[Record], float]:
  records: list[Record] = []
  semaphore = asyncio.Semaphore(concurrency)

  async with httpx2.AsyncClient() as client:

    async def worker(case: Case) -> None:
      async with semaphore:
        started = time.perf_counter()

        try:
          predicted, confidence, probabilities, timing, cached = await openjev_classify(
            client, url, model, case.message, timeout
          )
          record = Record(
            case=case,
            level="openjev",
            concurrency=concurrency,
            latency_ms=(time.perf_counter() - started) * 1000.0,
            ok=True,
            predicted=predicted,
            confidence=confidence,
            probabilities=probabilities,
            server_timing=timing,
            cached_tokens=cached,
          )
        except Exception as exception:
          record = Record(
            case=case,
            level="openjev",
            concurrency=concurrency,
            latency_ms=(time.perf_counter() - started) * 1000.0,
            ok=False,
            fallback=True,
            detail=f"{type(exception).__name__}: {str(exception)[:100]}",
          )

        records.append(record)

    wall_started = time.perf_counter()
    await asyncio.gather(*(worker(case) for case in cases for _ in range(repeats)))
    wall_seconds = time.perf_counter() - wall_started

  return records, wall_seconds


def baseline_router(
  sglang_url: str,
  model: str,
  timeout: float,
  backend: str = "sglang",
  ollama_url: str = "http://127.0.0.1:11434",
) -> tuple[SemanticRouter, httpx2.AsyncClient, Settings]:
  values: dict[str, Any] = {
    "llm_request_timeout": max(1, min(300, int(timeout))),
    "llm_temperature": 0.0,
    "llm_max_response_tokens": 128,
    "route_timeout_seconds": max(5.0, min(60.0, timeout)),
    "llm_cache_enabled": False,
    "log_level": "WARNING",
    "isinmi_url": None,
    "ojo_url": None,
    "rediyo_url": None,
    "kansa_url": None,
    "isakoso_url": None,
  }

  if backend == "ollama":
    values.update(llm_backend="ollama", llm_model=f"ollama:{model}", ollama_base_url=ollama_url)
  else:
    values.update(llm_backend="sglang", llm_model=model, llm_base_url=sglang_url.rstrip("/") + "/v1")

  settings = Settings(**values)
  client = httpx2.AsyncClient()
  agent = CommandAgent(settings, client, None)
  router = SemanticRouter(agent, lambda started: settings.route_timeout_seconds)

  return router, client, settings


async def run_baseline_level(
  cases: list[Case],
  sglang_url: str,
  model: str,
  concurrency: int,
  repeats: int,
  timeout: float,
  backend: str = "sglang",
  ollama_url: str = "http://127.0.0.1:11434",
) -> tuple[list[Record], float]:
  router, client, _ = baseline_router(sglang_url, model, timeout, backend, ollama_url)
  records: list[Record] = []
  semaphore = asyncio.Semaphore(concurrency)

  async def worker(case: Case) -> None:
    async with semaphore:
      context = RouteContext(
        request=ProcessRequest(message=case.message),
        request_id=f"{case.name}-{concurrency}",
        language="en",
        started_at=time.perf_counter(),
      )
      started = time.perf_counter()

      try:
        decision = await router.route(context)
        record = Record(
          case=case,
          level="baseline",
          concurrency=concurrency,
          latency_ms=(time.perf_counter() - started) * 1000.0,
          ok=True,
          predicted=decision.service.value if decision else None,
          confidence=decision.confidence if decision else None,
          fallback=decision is None,
        )
      except Exception as exception:
        record = Record(
          case=case,
          level="baseline",
          concurrency=concurrency,
          latency_ms=(time.perf_counter() - started) * 1000.0,
          ok=False,
          fallback=True,
          detail=f"{type(exception).__name__}: {str(exception)[:100]}",
        )

      records.append(record)

  wall_started = time.perf_counter()
  await asyncio.gather(*(worker(case) for case in cases for _ in range(repeats)))
  wall_seconds = time.perf_counter() - wall_started
  await client.aclose()

  return records, wall_seconds


async def run_e2e_level(
  cases: list[Case],
  sglang_url: str,
  model: str,
  openjev_url: str | None,
  concurrency: int,
  repeats: int,
  timeout: float,
) -> tuple[list[Record], float]:
  settings = Settings(
    server_host="127.0.0.1",
    server_port=5020,
    llm_backend="sglang",
    llm_model=model,
    llm_base_url=sglang_url.rstrip("/") + "/v1",
    llm_request_timeout=max(1, min(300, int(timeout))),
    llm_temperature=0.0,
    llm_max_response_tokens=128,
    llm_cache_enabled=False,
    request_budget_seconds=max(5.0, min(300.0, timeout + 5.0)),
    route_timeout_seconds=max(5.0, min(60.0, timeout)),
    openjev_url=openjev_url,
    openjev_model=model,
    openjev_request_timeout=min(4.0, timeout),
    component_circuit_breaker_enabled=False,
    log_level="WARNING",
    isinmi_url=None,
    ojo_url=None,
    rediyo_url=None,
    kansa_url=None,
    isakoso_url=None,
  )
  app = create_app(settings)
  records: list[Record] = []
  semaphore = asyncio.Semaphore(concurrency)
  level = "e2e-openjev" if openjev_url else "e2e-baseline"

  async with app.router.lifespan_context(app):
    transport = httpx2.ASGITransport(app=app)

    async with httpx2.AsyncClient(transport=transport, base_url="http://oremi.test", timeout=timeout) as client:

      async def worker(case: Case) -> None:
        async with semaphore:
          started = time.perf_counter()

          try:
            response = await client.post("/api/agent/", json={"message": case.message, "context": case.context})
            body = response.json() if response.status_code == 200 else {}
            record = Record(
              case=case,
              level=level,
              concurrency=concurrency,
              latency_ms=(time.perf_counter() - started) * 1000.0,
              ok=response.status_code == 200,
              predicted=body.get("service"),
              detail=None if response.status_code == 200 else f"HTTP {response.status_code}",
            )
          except Exception as exception:
            record = Record(
              case=case,
              level=level,
              concurrency=concurrency,
              latency_ms=(time.perf_counter() - started) * 1000.0,
              ok=False,
              fallback=True,
              detail=f"{type(exception).__name__}: {str(exception)[:100]}",
            )

          records.append(record)

      wall_started = time.perf_counter()
      await asyncio.gather(*(worker(case) for case in cases for _ in range(repeats)))
      wall_seconds = time.perf_counter() - wall_started

  return records, wall_seconds


def vram() -> dict[str, Any]:
  try:
    result = subprocess.run(
      [
        "docker",
        "run",
        "--rm",
        "--gpus",
        "all",
        "--entrypoint",
        "nvidia-smi",
        "ollama/ollama:0.32.3",
        "--query-gpu=memory.used,memory.free,utilization.gpu",
        "--format=csv,noheader",
      ],
      capture_output=True,
      text=True,
      timeout=60,
      check=False,
    )
  except (OSError, subprocess.SubprocessError) as exception:
    return {"error": str(exception)}

  return {"raw": result.stdout.strip()}


async def main() -> None:
  parser = argparse.ArgumentParser(description="Benchmark Oremi routing: baseline vs OpenJev+SGLang.")
  parser.add_argument("--openjev-url", default="http://127.0.0.1:8090")
  parser.add_argument("--sglang-url", default="http://127.0.0.1:30000")
  parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
  parser.add_argument("--baseline-backend", choices=["sglang", "ollama"], default="sglang")
  parser.add_argument("--model", default="Qwen/Qwen2.5-3B-Instruct")
  parser.add_argument("--levels", default="openjev,baseline,e2e")
  parser.add_argument("--concurrency", default="1,2,4,8")
  parser.add_argument("--thresholds", default="0.70,0.80,0.90,0.95")
  parser.add_argument("--repeats", type=int, default=2)
  parser.add_argument("--timeout", type=float, default=120.0)
  parser.add_argument("--output", default=None)
  args = parser.parse_args()

  logging.getLogger().setLevel(logging.WARNING)
  levels = [value.strip() for value in args.levels.split(",") if value.strip()]
  concurrency_levels = [int(value) for value in args.concurrency.split(",")]
  thresholds = [float(value) for value in args.thresholds.split(",")]
  cases = build_cases()
  e2e_cases = [case for case in cases if case.expected == Service.CHAT.value]

  report: dict[str, Any] = {
    "meta": {
      "timestamp": datetime.now(timezone.utc).isoformat(),
      "openjev_url": args.openjev_url,
      "sglang_url": args.sglang_url,
      "model": args.model,
      "concurrency": concurrency_levels,
      "thresholds": thresholds,
      "repeats": args.repeats,
      "cases": len(cases),
      "e2e_cases": len(e2e_cases),
    },
    "vram": {"before": vram()},
    "results": [],
    "quality": {},
  }

  for concurrency in concurrency_levels:
    if "openjev" in levels:
      records, wall = await run_openjev_level(cases, args.openjev_url, args.model, concurrency, args.repeats, args.timeout)
      report["results"].append(
        {
          "level": "openjev",
          "concurrency": concurrency,
          **summarize_latency(records, wall),
          "quality": {str(threshold): quality(records, threshold) for threshold in thresholds},
        }
      )
      report["quality"].setdefault("openjev", {})[str(concurrency)] = quality(records)

    if "baseline" in levels:
      records, wall = await run_baseline_level(
        cases,
        args.sglang_url,
        args.model,
        concurrency,
        args.repeats,
        args.timeout,
        args.baseline_backend,
        args.ollama_url,
      )
      report["results"].append(
        {
          "level": "baseline",
          "concurrency": concurrency,
          **summarize_latency(records, wall),
          "quality": quality(records, None),
        }
      )

    if "e2e" in levels:
      records, wall = await run_e2e_level(e2e_cases, args.sglang_url, args.model, None, concurrency, args.repeats, args.timeout)
      report["results"].append({"level": "e2e-baseline", "concurrency": concurrency, **summarize_latency(records, wall)})

      records, wall = await run_e2e_level(
        e2e_cases, args.sglang_url, args.model, args.openjev_url, concurrency, args.repeats, args.timeout
      )
      report["results"].append({"level": "e2e-openjev", "concurrency": concurrency, **summarize_latency(records, wall)})

  report["vram"]["after"] = vram()

  if args.output:
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2))
    print(f"Report written to {output}")

  for entry in report["results"]:
    latency = entry["latency_ms"]
    print(
      f"{entry['level']:14s} c={entry['concurrency']} "
      f"p50={latency['p50']} p95={latency['p95']} rps={entry['throughput_rps']} errors={entry['failed']}"
    )

  print(json.dumps(report["vram"], indent=2))


if __name__ == "__main__":
  asyncio.run(main())
