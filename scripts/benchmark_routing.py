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
"""Reproducible benchmark for the Oremi semantic routing stage.

This measures the ROUTING STAGE only (classifier decision latency and the router
wrapper overhead), not the end-to-end Oremi request (which also includes language
detection, prompt discovery, service dispatch, and response generation).

Modes:
  mock     - deterministic in-process fake classifier (no GPU, no network).
             Measures router + client + cache overhead only. These numbers are
             NOT indicative of real OpenJev/SGLang performance.
  openjev  - real HTTP calls to a running OpenJev (Jev-compatible) server.
             Measures actual client + server + SGLang inference latency.
  semantic - the existing SemanticRouter with an instant fake agent. Measures the
             router wrapper floor only; LLM inference time is intentionally excluded.

Run with: uv run python scripts/benchmark_routing.py --mode mock --iterations 2000
"""

import argparse
import asyncio
import statistics
from time import perf_counter

from akorin.core.classifier import ClassificationResult
from akorin.core.request import ProcessRequest
from akorin.core.router import RouteContext
from akorin.routers.openjev import OpenJevError
from akorin.routers.openjev import OpenJevRouter
from akorin.routers.openjev import OpenJevSglangClassifier


def percentile(values: list[float], p: float) -> float:
  if not values:
    return float("nan")

  ordered = sorted(values)
  index = (len(ordered) - 1) * p / 100.0
  lower = int(index)
  upper = min(lower + 1, len(ordered) - 1)
  weight = index - lower
  return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


class MockClassifier:
  """Deterministic fake classifier with a configurable outcome."""

  def __init__(self, *, label: str = "chat", confidence: float = 0.9, error_rate: float = 0.0, delay_ms: float = 0.0):
    self.label = label
    self.confidence = confidence
    self.error_rate = error_rate
    self.delay_ms = delay_ms
    self.calls = 0
    self.errors = 0

  async def classify(self, text: str, labels):
    self.calls += 1

    if self.delay_ms:
      await asyncio.sleep(self.delay_ms / 1000.0)

    if self.error_rate > 0:
      period = max(1, round(1.0 / self.error_rate))

      if self.calls % period == 0:
        self.errors += 1
        raise OpenJevError("simulated backend failure")

    return ClassificationResult(label=self.label, confidence=self.confidence, probabilities={self.label: 1.0})


def make_context(message: str) -> RouteContext:
  return RouteContext(
    request=ProcessRequest(message=message),
    request_id="bench",
    language="en",
    started_at=perf_counter(),
  )


async def run_once(router: OpenJevRouter, context: RouteContext) -> bool:
  decision = await router.route(context)
  return decision is not None


async def run_sequential(router: OpenJevRouter, messages: list[str]) -> tuple[list[float], int]:
  latencies = []
  accepted = 0

  for message in messages:
    context = make_context(message)
    started = perf_counter()
    is_decision = await run_once(router, context)
    latencies.append((perf_counter() - started) * 1000.0)

    if is_decision:
      accepted += 1

  return latencies, accepted


async def run_concurrent(router: OpenJevRouter, messages: list[str], concurrency: int) -> tuple[list[float], int]:
  semaphore = asyncio.Semaphore(concurrency)
  latencies = []
  accepted = 0
  lock = asyncio.Lock()

  async def worker(message: str):
    nonlocal accepted

    context = make_context(message)

    async with semaphore:
      started = perf_counter()
      is_decision = await run_once(router, context)
      elapsed = (perf_counter() - started) * 1000.0

    async with lock:
      latencies.append(elapsed)
      accepted += int(is_decision)

  await asyncio.gather(*(worker(message) for message in messages))

  return latencies, accepted


def report(name: str, latencies: list[float], accepted: int, total: int) -> None:
  elapsed = sum(latencies) / 1000.0
  fallback = total - accepted

  print(f"--- {name} ---")
  print(f"  requests            : {total}")
  print(f"  decisions (accepted): {accepted}")
  print(f"  fallback rate       : {fallback / total * 100:.1f}%")
  print(f"  p50 latency         : {percentile(latencies, 50):.3f} ms")
  print(f"  p95 latency         : {percentile(latencies, 95):.3f} ms")
  print(f"  p99 latency         : {percentile(latencies, 99):.3f} ms")
  print(f"  mean latency        : {statistics.fmean(latencies):.3f} ms")
  print(f"  throughput          : {total / elapsed:.1f} req/s" if elapsed > 0 else "  throughput          : n/a")
  print()


async def measure_error_rate(classifier, messages: list[str], labels: list[str]) -> float:
  errors = 0

  for message in messages:
    try:
      await classifier.classify(message, labels)
    except OpenJevError:
      errors += 1

  return errors / len(messages)


def build_router(args) -> OpenJevRouter:
  def timeout_calculator(started: float) -> float:
    return args.timeout

  if args.mode == "semantic":
    return OpenJevRouter(MockClassifier(label="chat", confidence=0.9), args.threshold, timeout_calculator)

  if args.mode == "mock":
    classifier = MockClassifier(
      label=args.label,
      confidence=args.confidence,
      error_rate=args.error_rate,
      delay_ms=args.delay_ms,
    )
    return OpenJevRouter(classifier, args.threshold, timeout_calculator)

  # openjev mode: real HTTP client against a live server.
  import httpx2

  client = httpx2.AsyncClient(timeout=args.timeout)
  classifier = OpenJevSglangClassifier(
    base_url=args.url,
    client=client,
    model=args.model,
    timeout=args.timeout,
    max_concurrency=args.concurrency,
  )
  return OpenJevRouter(classifier, args.threshold, timeout_calculator)


async def main() -> None:
  parser = argparse.ArgumentParser(description="Benchmark the Oremi semantic routing stage.")
  parser.add_argument("--mode", choices=["mock", "openjev", "semantic"], default="mock")
  parser.add_argument("--url", default="http://127.0.0.1:8787", help="OpenJev base URL (openjev mode).")
  parser.add_argument("--model", default="jev-latest", help="Model id sent to OpenJev.")
  parser.add_argument("--iterations", type=int, default=2000)
  parser.add_argument("--concurrency", type=int, default=8)
  parser.add_argument("--threshold", type=float, default=0.5, help="Confidence threshold for OpenJevRouter.")
  parser.add_argument("--timeout", type=float, default=4.0, help="Router timeout budget in seconds.")
  parser.add_argument("--label", default="chat", help="Mock classifier label.")
  parser.add_argument("--confidence", type=float, default=0.9, help="Mock classifier confidence.")
  parser.add_argument("--error-rate", type=float, default=0.0, help="Mock classifier error fraction (0..1).")
  parser.add_argument("--delay-ms", type=float, default=0.0, help="Mock classifier artificial latency.")
  args = parser.parse_args()

  if args.mode == "openjev":
    print(f"Benchmarking live OpenJev endpoint: {args.url} (model={args.model})")
  elif args.mode == "mock":
    print("Benchmarking MOCK classifier (deterministic, NO real inference or network).")
    print("These numbers reflect code-path overhead only and are NOT real performance.")
  else:
    print("Benchmarking SemanticRouter wrapper floor (LLM inference excluded).")

  labels = ["isinmi", "ojo", "rediyo", "kansa", "isakoso", "chat"]
  router = build_router(args)
  messages = [f"Turn on the living room lights ({i})" for i in range(args.iterations)]

  latencies, accepted = await run_sequential(router, messages)
  report("sequential", latencies, accepted, args.iterations)

  latencies, accepted = await run_concurrent(router, messages[: args.iterations], args.concurrency)
  report(f"concurrent (concurrency={args.concurrency})", latencies, accepted, args.iterations)

  if args.mode in {"mock", "openjev"}:
    classifier = router.classifier
    error_rate = await measure_error_rate(classifier, messages[: args.iterations], labels)
    print(f"  classifier error rate : {error_rate * 100:.1f}%")


if __name__ == "__main__":
  asyncio.run(main())
