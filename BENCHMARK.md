# Oremi Akọrin — LLM Inference Backend Benchmark

This document records an empirical comparison of three LLM inference backends
that Oremi Akọrin can select through `AgentClient`:

1. **Ollama** (native and OpenAI-compatible)
2. **SGLang** (OpenAI-compatible)
3. **Modular MAX** (OpenAI-compatible)

It does not declare a universal winner. It records what was measured, on which
hardware and model, what could not be measured, and what each result means for
Oremi Akọrin's interactive request path. Every number below comes from a
reproducible command; anything that could not be run is marked as such.

> Raw machine-readable results are written to `build/bench/results/` by the
> benchmark harness. That directory is git-ignored, so large generated results
> are not committed.

## 1. Architectural constraint

`AgentClient` remains the single LLM boundary. The rest of Oremi Akọrin is not
coupled to any runtime:

```text
Oremi Akọrin → Orchestrator → AgentClient ─┬─ Ollama (native client)
                                           ├─ SGLang (OpenAI-compatible)
                                           └─ MAX    (OpenAI-compatible)
                                                        ↓
                                                      LLM
```

Backend selection is configuration only:

| Setting | Values | Meaning |
| --- | --- | --- |
| `OREMI_AKORIN_LLM_BACKEND` | `auto`, `ollama`, `sglang`, `max` | `auto` keeps the historical behaviour |
| `OREMI_AKORIN_LLM_BASE_URL` | URL incl. `/v1` | Required for `sglang` and `max` |
| `OREMI_AKORIN_LLM_MODEL` | model id | Provider-prefixed for Ollama/Pydantic AI; served name for SGLang/MAX |

The change in `akorin/core/agent.py` is small: `build_model` now returns an
`OpenAIChatModel` configured with the OpenAI-compatible base URL for the
`sglang` and `max` backends, while the native Ollama and generic Pydantic AI
paths are unchanged. Tool calling, structured output, timeouts, retries, and the
`SmartCache` continue to flow through `AgentClient`.

## 2. What was added to the repository

- `Settings.llm_backend`, `Settings.llm_base_url`, `Settings.llm_api_key` plus
  `resolved_llm_backend`, `should_use_ollama`, `should_use_openai_compatible`,
  `llm_base_url_string`, and a fail-fast backend/base-URL validator.
- `AgentClient.build_model` / `AgentClient._build_openai_compatible_model`.
- `tests/test_llm_backends.py` — 19 offline tests (selection, validation,
  unavailable/timeout/HTTP errors, structured output, tool calling, and
  preservation of the native Ollama path).
- `scripts/benchmark_backends.py` — the reproducible harness (Level 1 and
  Level 2), and the `make benchmark` target.
- `.env.example` and `DOCUMENTATION.md` backend settings.

No orchestrator, router, MCP, caching, API-contract, or language-preservation
behaviour was changed.

## 3. Hardware and environment

| Item | Value |
| --- | --- |
| CPU | 13th Gen Intel(R) Core(TM) i9-13900HK — 14 cores / 20 threads |
| RAM | 62.5 GiB |
| Swap | 15 GiB |
| GPU | NVIDIA GeForce RTX 5070 (GB205), 12,227 MiB VRAM, compute capability 12.0 (Blackwell sm_120) |
| GPU driver / CUDA | NVIDIA 615.71.09; CUDA UMD 13.4 |
| GPU access | **Accessible through Docker** (`--gpus all`, runtime `nvidia`). The bare sandbox shell cannot see the device (no `/dev/nvidia*`, `nvidia-smi` fails); Docker is the project's real runtime and Ollama runs in a container. |
| OS | Fedora Linux 44 (Workstation), kernel 7.2.5-200.fc44.x86_64 |
| Runtime isolation | The shell sandbox uses a separate PID namespace and a read-only cache outside the workspace; GPU containers are unaffected |

Sections 1–6 are the **CPU baseline**, measured before the GPU was reached, and
are preserved unchanged. GPU measurements are in
**GPU Benchmark — NVIDIA RTX 5070** below.

## 4. Model and runtime configuration

| Backend | Version | Model | Quantization | Endpoint | Device |
| --- | --- | --- | --- | --- | --- |
| Ollama | 0.32.3 (Docker `ollama/ollama:0.32.3`) | `qwen2.5:3b` (Qwen2.5-3B-Instruct) | GGUF **Q4_K_M** (1.93 GB) | `http://127.0.0.1:11434` | CPU |
| SGLang | 0.5.20 (latest on PyPI) | not served | BF16 safetensors would be the closest option | — | **not runnable here** |
| Modular MAX | 26.6.0 (`modular`) | `Qwen/Qwen2.5-3B-Instruct` | **float32** safetensors | `http://127.0.0.1:8000` | CPU |

> **Scope.** This section and section 6 describe the **CPU baseline**. GPU
> configurations and results are in **GPU Benchmark — NVIDIA RTX 5070**;
> statements below about SGLang being unrunnable or the GPU being inaccessible
> apply to that CPU baseline only and are superseded there.

### Same-model parity

All three runtimes could in principle serve the Qwen2.5-3B-Instruct family. Exact
parity is **not** achievable across all three on this host:

- Ollama's `qwen2.5:3b` is Q4_K_M, and the official Qwen2.5-3B-Instruct GGUF
  Q4_K_M file exists, so Ollama and MAX *could* share identical weights.
- In this environment MAX's CPU engine rejected `q4_k` ("quantization_encoding
  of 'q4_k' not supported by MAX engine") and then `bfloat16` ("The encoding
  'bfloat16' is not compatible with the selected device type 'cpu'"); only
  `float32` was accepted for `Qwen2ForCausalLM` on CPU.
- Therefore the measured Ollama-vs-MAX comparison is **Ollama Q4_K_M vs MAX
  float32** on the same base model. The difference in memory footprint and
  throughput cannot be attributed to the runtime alone; it also reflects the
  quantization. Results are reported side by side, not as a controlled
  iso-quantization experiment.
- SGLang (0.5.20) documents an OpenAI-compatible server and a CPU server path,
  but its CPU path requires Intel AMX (4th-generation or newer Intel Xeon
  Scalable). This host's mobile Raptor Lake i9 has no AMX, so SGLang was not
  evaluated on CPU here. It **was** served successfully on the RTX 5070 (see the
  GPU section).

### Runtimes recorded from the servers themselves

- Ollama `/api/show` for `qwen2.5:3b`: `format=gguf`, `family=qwen2`,
  `parameter_size=3.1B`, `quantization_level=Q4_K_M`, `context_length=4096`.
- MAX startup log: `Qwen2ForCausalLM`, `quantization_encoding=float32`,
  `prefix_caching=True`, `chunked_prefill=True`, structured-output backend
  `xgrammar`, `cache_memory=297 MiB`, `memory_utilization=90%`, and
  `max_batch_size=1` on CPU.
- MAX model worker startup took **267.1 s** (spawn 2.6 s, compile 65.8 s, other
  197.2 s) after a 192 s weight download. That is a cold-start cost, not a
  per-request cost.

## 5. Methodology

### Two levels, never mixed

**Level 1 — runtime.** The harness posts to the OpenAI-compatible
`/v1/chat/completions` of the inference server only:

```text
benchmark client → Ollama / SGLang / MAX → model
```

This isolates the inference runtime. Streamed workloads record time-to-first-token
(TTFT).

**Level 2 — Oremi.** The harness builds the real FastAPI application with
`create_app(settings)`, drives it through `httpx2.ASGITransport`, and posts to
`/api/agent/`:

```text
benchmark client → FastAPI → Orchestrator → AgentClient (selected backend) → model
```

This is the complete Oremi request path, including language detection, the
routing chain, the chat/tool agent, response shaping, and device-command
selection. Oremi's public HTTP contract returns a single JSON response and does
not stream, so Level 2 reports **total response latency** (time to useful result);
TTFT is only meaningful at Level 1.

### Workloads (A–F)

| Workload | Level 1 prompt | Level 2 message |
| --- | --- | --- |
| `chat` | Short system prompt + "What is a fun fact about the ocean?" | same |
| `structured` | Route-classification prompt with a JSON schema `response_format` | "Remind me to call Ada tomorrow at 9 AM." |
| `tool` | Date/time question with a `get_current_datetime` tool schema | "What time is it in Paris right now?" |
| `long_context` | Oremi device context (~1.2 KB) + a question | same context + preferences |
| `repeated` | Fixed Oremi context prefix, varied user suffix | same |

### Metrics

Per (level, workload, concurrency): request count, success/failure counts,
error rate, latency min/p50/p95/p99/max/mean, TTFT min/p50/p95/p99/max/mean
(streamed Level 1 only), output tokens, requests/second, tokens/second, and wall
time. Peak client RSS is sampled throughout; the server's memory is recorded
separately where measurable.

### Caching is explicitly separated

The application-level `SmartCache` is **disabled** for the benchmark
(`--app-cache` is opt-in), so Level 1 and Level 2 both measure the inference
engine, not Oremi's cache. The `repeated` workload therefore exercises the
engine's own prefix/prompt cache (Ollama prompt cache, MAX `prefix_caching=True`,
SGLang RadixAttention), not `SmartCache`. Any cache benefit observed in
`repeated` must not be attributed to `SmartCache`.

### Reproduce

```sh
# Ollama (native model store already populated)
make benchmark BENCH_BACKEND=ollama BENCH_BASE_URL=http://127.0.0.1:11434 BENCH_MODEL=qwen2.5:3b

# MAX (OpenAI-compatible on :8000)
make benchmark BENCH_BACKEND=max BENCH_BASE_URL=http://127.0.0.1:8000 BENCH_MODEL=qwen2.5:3b \
  BENCH_LEVELS=1,2 BENCH_WORKLOADS=chat,tool BENCH_CONCURRENCY=1,2

# SGLang (from a host with an accessible GPU, or Intel AMX for its CPU server)
# python -m sglang.launch_server --model-path Qwen/Qwen2.5-3B-Instruct --port 30000
# make benchmark BENCH_BACKEND=sglang BENCH_BASE_URL=http://127.0.0.1:30000 BENCH_MODEL=qwen2.5:3b

# Full control
uv run python scripts/benchmark_backends.py --help
```

## 6. Results

### 6.1 Level 1 — raw runtime, Ollama, CPU, Q4_K_M, concurrency 1

4 requests per cell after 1 warmup. TTFT is only available for streamed
workloads; `structured` and `tool` were measured non-streamed.

| Workload | TTFT p50 (ms) | TTFT p95 (ms) | Total p50 (ms) | Total p95 (ms) | Output tok/s |
| --- | ---: | ---: | ---: | ---: | ---: |
| chat | 191.28 | 209.95 | 311.66 | 331.63 | 70.0 |
| structured | — | — | 625.10 | 646.95 | 60.7 |
| tool | — | — | 345.21 | 355.39 | 66.5 |
| long_context | 185.89 | 200.28 | 303.84 | 317.90 | 65.8 |
| repeated | 207.45 | 218.14 | 425.20 | 436.40 | 68.9 |

### 6.2 Level 1 — latency and throughput under concurrency

Cells are `total p50 (ms) / requests per second`. All cells completed with zero
errors.

| Workload | c = 1 | c = 2 | c = 4 |
| --- | --- | --- | --- |
| chat | 311.66 / 3.18 | 419.70 / 4.72 | 542.70 / 5.45 |
| structured | 625.10 / 1.60 | 1107.45 / 1.67 | 1479.94 / 1.73 |
| tool | 345.21 / 2.89 | 360.70 / 4.76 | 518.59 / 5.62 |
| long_context | 303.84 / 3.29 | 336.43 / 4.98 | 558.83 / 5.37 |
| repeated | 425.20 / 2.34 | 451.28 / 3.65 | 801.59 / 3.55 |

Throughput rises with concurrency while per-request latency grows, which is the
expected continuous-batching trade-off. The structured workload is consistently
the slowest per request (JSON-schema constrained decoding).

### 6.3 Level 2 — end-to-end Oremi, Ollama

Cells are `total p50 / p95 (ms)`. 4 requests per cell plus 1 warmup; the
application `SmartCache` is disabled.

| Workload | c = 1 | c = 2 | c = 4 |
| --- | --- | --- | --- |
| chat | 942.35 / 965.42 | 892.15 / 1103.81 | 1227.38 / 1523.98 |
| structured\* | 330.28 / 341.63 | 394.05 / 429.85 | 523.64 / 616.50 |
| tool | 350.33 / 364.02 | 409.64 / 438.59 | 483.85 / 570.07 |
| long_context | 667.70 / 690.99 | 783.20 / 794.55 | 891.72 / 995.68 |
| repeated | 848.84 / 882.44 | 839.73 / 960.62 | 1228.76 / 1508.79 |

\* The `structured` message ("Remind me to call Ada tomorrow at 9 AM") routes to
the **Isinmi** component, which is intentionally not configured in this
chat-only benchmark. Every response is therefore `ok=false` with a generated
user-facing failure message. This is a **service-configuration** result, not an
inference failure: the latency reflects one LLM call (the failure response), and
these 12 requests account for all 12 failures in the run.

The `chat` and `repeated` workloads cost roughly **two LLM calls** per request
(one structured routing classification, then the chat completion), which is why
Level 2 latency is about 2–3× the Level 1 chat latency. This is the real Oremi
request cost, not harness overhead.

### 6.4 MAX — reduced matrix (CPU, float32)

MAX was measured with 1 sample per cell because the float32 3B model drove the
host into swap; these are point measurements, not distributions.

| Level | Workload | Concurrency | n | Total latency (ms) | Output tok/s | Result |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| 1 | chat | 1 | 1 | 21,059.94 | — | success |
| 2 | chat | 1 | 1 | 107,729.15 | 0.15 | success, cold |
| 2 | tool | 1 | 1 | 12,762.52 | 0.71 | success, `get_current_datetime` executed |

The Level 2 `chat` figure includes routing plus chat and was the first
application request after the model worker started; it is dominated by cold
effects and memory pressure. The warm Level 2 `tool` request is the more
representative MAX CPU number (~12.8 s), and it demonstrated a real tool call
(`{"timezone": "Europe/Paris"}`) plus structured routing succeeding through
`AgentClient`.

SGLang produced **no measurements** (see §4 and §11).

### 6.5 Reliability and resources

| Metric | Ollama | MAX | SGLang |
| --- | ---: | ---: | ---: |
| Requests measured | 120 | 3 | 0 |
| Failed requests | 12 (all expected `ok=false`, Isinmi unconfigured) | 0 | n/a |
| Transport/timeout errors | 0 | 0 | n/a |
| Peak benchmark-client RSS | 248.1 MB | 242.2 MB | n/a |
| Model size | 1.93 GB (Q4_K_M GGUF; 2.16 GB resident per `/api/ps`) | ~12 GB (float32) | n/a |
| Observed server memory | container RSS ≈ 1.1 GiB sampled during the run | host RAM rose from ≈34 GiB idle to ≈51–52 GiB while serving | n/a |
| Cold start | model resident; Ollama load logged as instant | 192 s download + 267.1 s worker startup | n/a |
| Max batch size | n/a (Ollama-managed) | `1` on CPU | n/a |

### 6.6 What the numbers show

- **Interactive latency:** Ollama keeps Level 1 TTFT at ~190–220 ms and Level 1
  chat under ~0.55 s even at concurrency 4. End-to-end chat (two LLM calls) stays
  around 0.9–1.2 s p50. That is the range an interactive gateway needs.
- **Throughput vs. latency:** Ollama trades latency for throughput as concurrency
  rises (chat: 3.18 → 5.45 req/s from c=1 to c=4, p50 312 → 543 ms). No
  unbounded collapse was observed at c=4.
- **Structured output is the expensive path** at Level 1 (625 ms vs 312 ms chat).
- **MAX on this CPU is not interactive:** ~21 s for one raw chat and ~12.8 s for
  one warm end-to-end tool request, at float32 and batch size 1. It is
  functionally compatible but not latency-viable on this host.
- **Application cache was disabled**, so these are engine-level numbers; the
  `repeated` workload therefore reflects engine prefix/prompt caching, not
  `SmartCache`.


## GPU Benchmark — NVIDIA RTX 5070

> This section was added after the CPU baseline and does not modify sections 1–6.

### GPU diagnosis correction

The earlier conclusion — "the GPU is not accessible" — was an artifact of the
shell sandbox, not of the host. The same command behaves differently depending on
where it runs:

| Environment | `nvidia-smi` | `/dev/nvidia*` | CUDA visible | Verdict |
| --- | --- | --- | --- | --- |
| Sandboxed shell (`run_code` bash) | fails | absent | no | not usable |
| Docker container (`--gpus all`, runtime `nvidia`) | works | present | yes | **usable** |
| Container Python (SGLang image) | — | — | `torch.cuda.is_available()=True`, capability `(12, 0)` | **usable** |

Oremi already runs Ollama in Docker, so Docker is the project's real GPU runtime.
The host shell cannot see the device because the sandbox does not bind
`/dev/nvidia*`.

### Verified GPU

| Item | Value |
| --- | --- |
| GPU | NVIDIA GeForce RTX 5070 (GB205), compute capability 12.0 (Blackwell sm_120) |
| VRAM | 12,227 MiB total |
| Driver | NVIDIA 615.71.09 |
| CUDA | UMD 13.4; container torch 2.13.0+cu130 reports CUDA 13.0 |
| Date | 2026-09-19 |
| OS / kernel | Fedora Linux 44 / 7.2.5-200.fc44.x86_64 |

### Other GPU consumers

`nvidia-smi --query-compute-apps` (host PID namespace) showed nine
`magnitude-inference` processes (~1.5 GiB total) that do **not** belong to this
project. They were left running. The project's Ollama container was stopped
temporarily to free ~3.2 GiB for SGLang/MAX and restarted afterwards; no other
users' processes were killed.

### GPU configurations measured

| Backend | Version | Model | Precision | Startup | Notes |
| --- | --- | --- | --- | --- | --- |
| Ollama | 0.32.3 | `qwen2.5:3b` | Q4_K_M GGUF | model resident | `size_vram == size` → fully offloaded |
| SGLang | 0.5.20 | `Qwen/Qwen2.5-3B-Instruct-GPTQ-Int4` | GPTQ-Int4 | load 20.5 s, CUDA-graph prefill 196 s | `--mem-fraction-static 0.65` |
| SGLang | 0.5.20 | `Qwen/Qwen2.5-3B-Instruct` | BF16 | load 11.8 s, CUDA-graph prefill 28 s | `--mem-fraction-static 0.80` |
| MAX | 26.6.0 | `Qwen/Qwen2.5-3B-Instruct` | BF16 | worker 176.9 s (compile 164.8 s), `max_batch_size=512` | `--enable-structured-output` |

MAX rejected GPTQ (`quantization_encoding of 'gptq' not supported by MAX engine`),
so MAX could not use SGLang's GPTQ-Int4 weights. SGLang BF16 and MAX BF16 use
identical weights; Ollama and SGLang-GPTQ are both ~4-bit but different formats.

### Level 1 — GPU, concurrency 1

TTFT p50 / total p50 (ms), 4 requests per cell plus 1 warmup:

| Backend / precision | chat | structured | tool | long_context | repeated | chat tok/s |
| --- | --- | --- | --- | --- | --- | ---: |
| Ollama Q4_K_M | 188 / 309 | — / 785 | — / 398 | 302 / 425 | 266 / 491 | 71.7 |
| SGLang GPTQ-Int4 | 28 / 150 | — / 136 | — / 134 | 34 / 135 | 29 / 166 | 157.8 |
| SGLang BF16 | 37 / 499 | — / 285 | — / 270 | 31 / 284 | 26 / 422 | 69.5 |
| MAX BF16 | 25 / 376 | — / 387 | — / 256 | 27 / 251 | 28 / 450 | 74.5 |

### Level 1 — concurrency (chat total p50 ms / req·s⁻¹)

| Backend / precision | c = 1 | c = 2 | c = 4 |
| --- | --- | --- | --- |
| Ollama Q4_K_M | 309 / 3.26 | 455 / 3.86 | 655 / 4.73 |
| SGLang GPTQ-Int4 | 150 / 6.57 | 192 / 10.42 | 179 / 22.26 |
| SGLang BF16 | 499 / 1.74 | 737 / 2.71 | 523 / 7.64 |
| MAX BF16 | 376 / 2.66 | 315 / 5.93 | 405 / 8.46 |

### Level 2 — end-to-end Oremi, concurrency 1 (total p50 ms)

| Workload | Ollama Q4_K_M | SGLang GPTQ-Int4 | SGLang BF16 | MAX BF16 |
| --- | ---: | ---: | ---: | ---: |
| chat | 869 | 276 | 480 | 529 |
| structured\* | 294 (ok=false) | 97 (ok=false) | 148 (ok=false) | 138 (ok=false) |
| tool | 746 | 194 | 319 | 294 |
| long_context | 657 | 268 | 295 | 272 |
| repeated | 828 | 286 | 595 | 698 |

\* `structured` routes to the unconfigured Isinmi component, so `ok=false` is an
expected service-configuration result, not an inference failure.

### Level 2 — concurrency (chat total p50 ms)

| Backend / precision | c = 1 | c = 2 | c = 4 |
| --- | ---: | ---: | ---: |
| Ollama Q4_K_M | 869 | 903 | 1428 |
| SGLang GPTQ-Int4 | 276 | 353 | 441 |
| SGLang BF16 | 480 | 559 | 645 |
| MAX BF16 | 529 | crashed | crashed |

### MAX structured-decoding crash (exact cause)

At concurrency ≥ 2, MAX's model worker aborts during schema-constrained decoding:

~~~~text
RuntimeError: Generated out-of-vocabulary token_id=151694 for request ... (valid range: [0, 151665))
{"levelname": "ERROR", "message": "Worker crashed (1), shutting down..."}
~~~~

- Reproduced with `--structured-output-backend xgrammar` (token ids 151758 and
  151694) and with `llguidance` (151694).
- At concurrency 1, structured routing succeeds 6/6. At concurrency 2 the worker
  crashes after 2 requests; at 4 and 8 every request fails.
- This affects Oremi's `CommandAgent` routing, so MAX Level 2 is valid only at
  concurrency 1. MAX Level 1 non-structured workloads are stable at c = 1, 2, 4.

### Why the first SGLang/MAX attempts failed (exact causes)

| Attempt | Exact failure | Cause |
| --- | --- | --- |
| SGLang BF16, `--mem-fraction-static 0.8` | `Loaded weights leave no GPU memory for the KV cache ... Raise --mem-fraction-static above 0.890` | KV fraction too low |
| SGLang BF16, `0.90` | `torch.OutOfMemoryError` in flashinfer prefill | Ollama's `qwen3.5:2b` (3.2 GiB) + magnitude held VRAM |
| SGLang GPTQ-Int4, `0.65`, Ollama stopped | served successfully | correct configuration |
| MAX, `--quantization-encoding gptq` | `quantization_encoding of 'gptq' not supported by MAX engine` | MAX quantization-format limitation |
| MAX BF16, structured request | `response_format requires --enable-structured-output` | MAX serve flag |

### VRAM measured

| Backend | Observed GPU memory | Notes |
| --- | --- | --- |
| magnitude-inference (other) | ~1.5 GiB | nine processes, not this project |
| Ollama Q4_K_M | `size_vram` = 2.16 GB for `qwen2.5:3b`; 7063 MiB total with two project models + magnitude resident | fully offloaded |
| SGLang GPTQ-Int4 | 9531 MiB total (incl. magnitude) | pool from `mem-fraction-static=0.65` |
| SGLang BF16 | ~10.3 GiB total; 0.82 GiB free after init | tight |
| MAX BF16 | 11401 MiB total (incl. magnitude) | `max_batch_size=512`, 90% memory pool |

### GPU diagnostic table

| Component | GPU visible | CUDA works | Model loads | Inference works | Exact failure |
| --- | --- | --- | --- | --- | --- |
| Ollama | yes | yes | yes | yes | none (fully offloaded) |
| SGLang | yes | yes (cap 12.0) | yes | yes at c = 1, 2, 4 (GPTQ-Int4 and BF16) | none |
| MAX | yes | yes | yes | yes at c = 1; no at c ≥ 2 structured | OOV token in structured decoding → worker crash |
| OpenJev/SGLang | yes | not exercised | — | — | classification path not benchmarked here |

### GPU findings

- The RTX 5070 successfully runs Ollama, SGLang and MAX; the previous
  "GPU unavailable" conclusion is superseded.
- SGLang GPTQ-Int4 is the fastest configuration measured for Oremi's interactive
  path (L1 chat 150 ms, TTFT 28 ms; L2 chat 276 ms) and scales to c = 4.
- MAX BF16 is competitive at c = 1 (TTFT 25 ms; L2 chat 529 ms) but crashes on
  Oremi's structured routing above c = 1.
- Ollama Q4_K_M is fully offloaded yet, for this 3B model, GPU latency is close to
  CPU latency and it is the slowest at Level 2.

## 7. Compatibility differences

| Capability | Ollama 0.32.3 | SGLang 0.5.20 | MAX 26.6.0 |
| --- | --- | --- | --- |
| OpenAI `/v1/chat/completions` | Yes (verified) | Yes (documented) | Yes (verified) |
| Streaming | Yes | Yes | Yes |
| Tool calling | Yes (documented/verified path) | Yes (documented) | Yes — a real `get_current_datetime` call was executed end-to-end |
| Structured output | Yes (`format`/JSON schema) | Yes (documented) | Yes (`xgrammar`) |
| Prompt/prefix cache | Yes | Yes (RadixAttention) | Yes (`prefix_caching=True`) |
| Continuous batching | Limited on this CPU | Yes (GPU) | `max_batch_size=1` on CPU |
| CPU execution | Yes | Only with Intel AMX; not on this host | Yes, but float32 only for this model |

Ollama's OpenAI-compatible endpoint is a compatibility subset of the native API.
In an early probe, a small model served through Ollama's `/v1` endpoint did not
reliably satisfy the JSON-schema `response_format` used by the harness and
emitted a tool call as text rather than as a tool-call object. That is an
Ollama-compatibility observation from a small model, not a claim about SGLang or
MAX. Through MAX, Oremi's structured routing (`CommandAgent` →
`RouteSemanticDecision`) and tool calling both completed successfully.

## 8. Integration complexity

All three share one integration: the `sglang` and `max` values route through
Pydantic AI's `OpenAIChatModel` with an `OpenAIProvider` configured from
`OREMI_AKORIN_LLM_BASE_URL`/`OREMI_AKORIN_LLM_API_KEY`. SGLang and MAX were not
integrated separately, precisely because both expose the same OpenAI-compatible
contract.

- **Ollama:** already integrated (native `ollama.AsyncClient`). Unchanged.
- **SGLang / MAX:** one new model-construction branch in `AgentClient.build_model`
  (~20 lines) plus three settings and validation. No new dependency: `openai` is
  a hard dependency of the already-required `pydantic-ai`.
- **Structured-output profile (GPU finding).** Local OpenAI-compatible servers
  return schema-constrained output more reliably than pydantic-ai's default
  tool-based mode. `_build_openai_compatible_model` sets
  `OpenAIModelProfile(default_structured_output_mode="native")`. Without it,
  SGLang failed Oremi's `CommandAgent` routing with `UnexpectedModelBehavior`
  (the model returned a `final_result` tool call that pydantic-ai validated as the
  output model). MAX additionally needs its own `--enable-structured-output` flag.
- The `build_model` seam is preserved, so the existing test strategy
  (`TestModel`/`FunctionModel` monkeypatching) still works.

## 9. Operational complexity

- **Ollama** runs as a single container, pulls GGUF models, and defaults to a
  quantized format (Q4_K_M here) that fits modest RAM. It was already the
  project's default.
- **SGLang** requires a GPU deployment in practice; its CPU server needs Intel
  AMX. Serving and model management are typical of a GPU inference stack.
- **MAX** installed cleanly via `uv pip install modular` and served on CPU, but:
  - Mojo needed writable `~/.cache/modular` and `~/.local/share/modular`;
  - the CPU encoding for this architecture is `float32` (≈12 GB of weights);
  - the model worker took 267 s to become ready and ran with `max_batch_size=1`;
  - MAX spawns a metrics worker via `multiprocessing` (spawn); in this sandbox the
    model worker only started once `PYTHONHOME`/`PYTHONPATH` were pinned
    explicitly, and the metrics worker still failed to import `encodings`. That is
    an environment/sandbox finding, but it shows MAX's process model is more
    involved than Ollama's single container.

## 10. Real-time behaviour

Oremi is interactive. The metrics that matter most are Level 1 TTFT (how quickly
the first token appears), Level 1 total latency, and Level 2 total latency (how
long the user waits for a complete answer, including routing).

- On CPU, Ollama's Q4_K_M model keeps TTFT in the low hundreds of milliseconds
  and total chat latency well under a second at concurrency 1, degrading
  gracefully as concurrency rises.
- MAX's float32 model is memory-bandwidth bound on the same CPU; a single Level 1
  chat request took ≈21 s and a cold Level 2 chat request took ≈108 s, while a
  warm Level 2 tool request took ≈12.8 s. Under the memory pressure created by a
  ~12 GB float32 model on a 62 GB machine that was already running other
  services, swap usage reached ~9 GiB and throughput collapsed further.
- This is a statement about **this CPU deployment at these quantizations**, not a
  statement about MAX on a GPU. On an accessible GPU with a supported encoding,
  the picture would be different and is not measured here.

## 11. Limitations and threats to validity

1. **Not iso-precision across all backends.** Ollama Q4_K_M, SGLang GPTQ-Int4,
   SGLang BF16 and MAX BF16 are all Qwen2.5-3B-Instruct variants but at three
   precisions. SGLang BF16 and MAX BF16 share identical weights; Ollama and
   SGLang-GPTQ are both ~4-bit but different formats.
2. **MAX cannot be compared above concurrency 1 for structured work.** MAX 26.6.0
   crashes its worker with an out-of-vocabulary token during schema-constrained
   decoding at c ≥ 2, so MAX Level 2 is reported only at concurrency 1.
3. **Shared GPU.** Nine `magnitude-inference` processes (~1.5 GiB) outside this
   project stayed resident. The project's Ollama container was stopped temporarily
   for SGLang/MAX and restarted afterwards; no other process was killed.
4. **Small matrices.** 4 samples per cell (plus 1 warmup); 1 sample per cell for
   the earlier MAX CPU runs. p99 equals the max and is not a stable tail estimate.
   CUDA-graph capture adds a one-time ~28–196 s startup.
5. **Shared host.** The host runs the Oremi Docker stack, other services, and a
   desktop session; it is not a dedicated benchmark machine.
6. **Estimated Level 2 tokens.** Oremi's response does not expose token usage, so
   Level 2 output tokens are approximated from the response text.
7. **ASGI Level 2.** Level 2 uses `httpx2.ASGITransport` (in-process) rather than
   a separate uvicorn process; it exercises the full application path but not the
   socket/TLS stack.
8. **OpenJev + SGLang routing was not benchmarked here.** The OpenJev
   classification path is separate from `AgentClient` and was outside this run.

## 12. Conclusion

No backend is declared a winner. The measurements support a narrower,
requirement-driven reading:

- **SGLang (GPTQ-Int4, RTX 5070)** gave the lowest interactive latency: Level 1
  chat TTFT p50 28 ms / total 150 ms, Level 2 chat 276 ms at c = 1, scaling to
  22.3 req/s (Level 1, c = 4).
- **MAX (BF16, RTX 5070)** is fast at c = 1 (TTFT 25 ms, Level 2 chat 529 ms) but
  its worker crashes on Oremi's structured routing at c ≥ 2, so it is not yet safe
  as a general backend for this pipeline.
- **Ollama (Q4_K_M)** is fully GPU-offloaded, but for this 3B model GPU latency is
  close to CPU latency and it is the slowest GPU configuration at Level 2.
- **SGLang BF16 vs MAX BF16** (identical weights) is the most controlled GPU
  comparison: SGLang is faster at every measured concurrency.

The decision depends on the target. SGLang is the strongest GPU option measured;
MAX needs the structured-decoding defect fixed before it can serve Oremi's
routing; Ollama remains the simplest default and is CPU-competitive for small
models.

## Appendix — Repository changes

| File | Change |
| --- | --- |
| `akorin/core/settings.py` | Backend/base-URL/API-key settings, resolution properties, validation |
| `akorin/core/agent.py` | OpenAI-compatible model construction in `build_model`, including the native structured-output profile for SGLang/MAX |
| `akorin/core/app.py` | Log the backend and base URL at startup |
| `tests/test_llm_backends.py` | 19 offline backend tests |
| `scripts/benchmark_backends.py` | Level 1/Level 2 benchmark harness |
| `Makefile` | `make benchmark` target |
| `.env.example`, `DOCUMENTATION.md` | Backend configuration reference |
