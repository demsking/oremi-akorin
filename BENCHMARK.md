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

## OpenJev + SGLang Semantic Routing Benchmark

> Added after the backend benchmark above. No earlier section is modified.
> GPU measurements were completed on 2026-09-20 while the GPU was available; the
> results, the end-to-end route audit, and the two GPU/driver faults observed
> during the run are documented below. The existing-router CPU baseline is kept.

### Architecture

Current routing (baseline A):

~~~~text
request -> SpacyRouter -> McpPromptRouter -> SemanticRouter -> CommandAgent
        -> AgentClient -> SGLang /v1/chat/completions (native JSON-schema output)
~~~~

OpenJev is an optional specialized classifier inserted **before** the existing
SemanticRouter and **after** the deterministic routers. It never replaces
AgentClient and is never the general-purpose LLM backend:

~~~~text
request -> SpacyRouter -> McpPromptRouter -> OpenJevRouter
        -> OpenJev /v1/systemone (one-token logprob choice)
              high confidence -> RouteSemanticDecision
              low confidence / any failure -> SemanticRouter (AgentClient -> SGLang)
        -> AgentClient -> SGLang -> response
~~~~

Router order is asserted by `tests/test_openjev_router.py`:
`SpacyRouter, McpPromptRouter, OpenJevRouter, SemanticRouter` (OpenJev is omitted
when `OREMI_AKORIN_OPENJEV_URL` is unset).

### OpenJev API verification (upstream)

The local, open-source OpenJev (no paid TypeSafe service) was installed from
`github.com/ekzhang/openjev-sglang` at commit
`604664a22b2cf44c6cc499e503092ae4e3c24c03` (2026-09-18), package `openjev 0.1.0`.

Verified against upstream source (`models.py`):

- `POST /v1/systemone` with `state` (string or chat transcript) and `questions`.
- `{"type": "choice", "instructions": "...", "criteria": {key: description}}`
  with 2-64 criteria; option keys identify response fields.
- Response `answers.<key>`: `type`, `choice` (argmax key), `probabilities`
  (sum to 1), and `confidence` = `1 - normalized entropy`, explicitly **not**
  calibrated correctness.
- Internals: the question is rendered as an extra user turn; SGLang `/generate`
  is called with `max_new_tokens=1` and `token_ids_logprob`; N+1 one-token calls
  per N questions (one radix-cache warm-up plus one branch per question).
- Qwen tokenizers expose the required 64 single-token answer labels; verified for
  `Qwen/Qwen2.5-3B-Instruct-GPTQ-Int4` with `openjev smoke` (64-way logits,
  `target` selected, probabilities sum to 1).

The repository client (`akorin/routers/openjev.py`) matches this contract and
needed no API change. The only routing-code change is a fail-safe catch so
**any** classifier exception degrades to the existing SemanticRouter.

### Versions and configuration

| Item | Value |
| --- | --- |
| OpenJev | 0.1.0, commit `604664a` (2026-09-18) |
| SGLang | `lmsysorg/sglang:latest`, reports `0.5.20` (Python 3.12, torch 2.13.0+cu130) |
| Model | `Qwen/Qwen2.5-3B-Instruct-GPTQ-Int4`, 4-bit GPTQ |
| GPU | NVIDIA GeForce RTX 5070, 12,227 MiB, sm_120, driver 615.71.09, CUDA UMD 13.4 |
| OpenJev backend | SGLang on `127.0.0.1:30000`, API on `127.0.0.1:8090` |
| SGLang flags | `--context-length 4096 --mem-fraction-static 0.65` |

**Why GPTQ-Int4 and not BF16.** The pre-registered plan used
`Qwen/Qwen2.5-3B-Instruct` in BF16. On the retagged `latest` image the KV
profiler requires `--mem-fraction-static > 0.815` while the physical headroom
with ~1.5 GiB of unrelated GPU consumers (`magnitude-inference` processes) caps
the fraction below ~0.873; `0.88` then OOMs during CUDA-graph capture. GPTQ-Int4
is the same Qwen2.5-3B-Instruct model and tokenizer at 4-bit, is the
configuration the earlier backend benchmark found fastest, and serves both the
OpenJev and the baseline classifier from the same server, so the routing
comparison remains same-model. The Ollama `qwen3.5:2b` model (2.42 GB VRAM) was
unloaded for the GPU runs; it is unrelated to this project.

The served model name must equal `--model`: a request naming
`Qwen/Qwen2.5-3B-Instruct` against a server named `...-GPTQ-Int4` returns
`HTTP 422 {"error":{"message":"Unknown model: ..."}}`.

### GPU measurements - direct classification

Direct `POST /v1/systemone` (`openjev` level) versus the existing
`SemanticRouter -> CommandAgent -> SGLang` `/v1/chat/completions` structured
output (`baseline` level). 39 cases x 3 repeats = **117 samples** per
concurrency, **0 errors at every point**.

| c | OpenJev p50 | p95 | p99 | req/s | Baseline p50 | p95 | p99 | req/s |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 54.24 | 76.33 | 136.55 | 17.12 | 94.38 | 111.28 | 252.06 | 8.56 |
| 2 | 99.14 | 150.92 | 191.03 | 19.65 | 136.52 | 158.61 | 528.16 | 13.75 |
| 4 | 92.58 | 118.41 | 122.33 | 40.85 | 131.49 | 146.05 | 156.04 | 29.52 |
| 8 | 100.39 | 142.35 | 152.35 | 71.33 | 165.76 | 287.47 | 295.43 | 45.00 |

The one-token-logprob classifier is **faster and scales better** than the
structured-output chat classification at every measured concurrency: ~1.7x
lower p50 at c=1 and ~1.6x the throughput at c=8. That is the only category in
which OpenJev wins, and it is not sufficient (see quality and stability).

### GPU measurements - routing quality

Quality is measured on the same 39 cases (accuracy over 117 samples). It is
independent of concurrency.

| Level | Accuracy | FP | FN | per-route accuracy |
| --- | ---: | ---: | ---: | --- |
| SemanticRouter baseline | **0.9487** | 6 | 6 | chat 1.00, isakoso 0.889, isinmi 1.00, kansa 1.00, ojo 1.00, rediyo 0.75 |
| OpenJev | **0.7692** | 27 | 27 | chat **0.00**, isakoso 1.00, isinmi 0.889, kansa 0.667, ojo 1.00, rediyo 0.75 |

OpenJev is **confidently wrong**: mean `confidence` 0.9872, p50 0.9999, min
0.889. `confidence` is distribution concentration (`1 - normalized entropy`),
not calibrated correctness, so it does not track accuracy.

Per-case replay shows the failure is systematic, not noise: **every** chat and
no-match case (general chat EN/FR, "Quelle heure est-il ?", joke, capital,
explain) and `Lancer un podcast (FR)`, `ambig-rain-reminder`, `ambig-play-music`
were misrouted, almost all to **`isakoso`** (the longest criterion description,
which lists many command words) with `chat` probability near zero. The label bias
makes the `choice` question unusable with this label set.

Threshold sweep over OpenJev confidence (fallbacks are requests below the
threshold that would defer to the SemanticRouter):

| Threshold | Accuracy (accepted) | Fallback rate |
| ---: | ---: | ---: |
| 0.70 | 0.7692 | 0.0000 |
| 0.80 | 0.7692 | 0.0000 |
| 0.90 | 0.7895 | 0.0256 |
| 0.95 | 0.8529 | 0.1282 |

No threshold reaches the baseline, because the errors carry high confidence:
raising the threshold only drops a few confident-wrong cases into the (correct)
fallback while still not matching the existing router.

### GPU measurements - end-to-end Oremi

Full `POST /api/agent/` path (FastAPI -> Orchestrator -> routers -> AgentClient
-> SGLang), 6 CHAT cases x 3 repeats = 18 samples per sub-run, concurrency 1.

| Sub-run | p50 | p95 | p99 | req/s |
| --- | ---: | ---: | ---: | ---: |
| `e2e-baseline` (no OpenJev) | 457.42 | 739.21 | 759.38 | 2.452 |
| `e2e-openjev` | 172.32 | 190.46 | 191.53 | 5.911 |
| `e2e-baseline` (warm rerun) | 450.76 | 732.24 | 742.44 | 2.521 |
| `e2e-openjev` (warm rerun) | 177.03 | 200.22 | 223.56 | 5.610 |

The OpenJev path is ~2.5x faster end to end, but the route audit shows the speed
is an artefact of misrouting: with the OpenJev router enabled, **5 of 6** chat
cases returned `service=isakoso`, and the orchestrator log shows
`ComponentUnavailable: isakoso unavailable: component is not configured` (the
chat fallback then answered, masking the misroute as `ok=true`). If `isakoso`
were configured, those chat requests would have issued smart-home device
commands. With OpenJev disabled, all 6 chat cases routed to `chat` with no
component errors. The E2E latency win is therefore not a fair comparison: it
bypasses correct classification and takes the failed-component fallback.

### Fallback behavior

The classifier is fail-safe by construction and by test: timeout, connection
failure, HTTP error, malformed response, unknown label, low confidence, or any
unexpected exception makes `OpenJevRouter.route` return `None` and the existing
`SemanticRouter` handles the request. Measured at c=1:

| Scenario | Sub-run | p50 | p95 | p99 | req/s | errors |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Hard outage (connection refused, :8098) | `e2e-baseline` | 490.89 | 710.58 | 716.60 | 2.541 | 0 |
| Hard outage (connection refused, :8098) | `e2e-openjev` | 347.48 | 759.22 | 780.07 | 2.644 | 0 |
| Hung OpenJev (accepts, never responds, :8099) | `e2e-baseline` | 487.18 | 741.20 | 753.54 | 2.407 | 0 |
| Hung OpenJev (accepts, never responds, :8099) | `e2e-openjev` | **4343.19** | 4706.43 | 4718.58 | 0.271 | 0 |

A hard outage adds negligible overhead (the `e2e-baseline` sub-run always runs
first and absorbs cold-start, so its p50 is the higher of the two). A **hung**
OpenJev is the dangerous case: each request waits the full ~4 s
`openjev_request_timeout` before falling back, so p50 grows ~9x (487 ms ->
4.34 s) while the fallback still succeeds (0 errors). Unit tests cover every
fallback path (`tests/test_openjev_router.py`, 24 tests).

### Caching

OpenJev results are cached in the existing `SmartCache` (key = model + labels +
text) and failures are not cached; this is application-level caching and is
independent of SGLang's radix prefix cache. The direct `openjev` level bypasses
`SmartCache`, so its numbers are the raw classifier latency; the `e2e` level
includes `SmartCache`. OpenJev exposes
`Server-Timing`/`x-openjev-prefix-tokens`/`x-openjev-cached-tokens` for
engine-level cache evidence; the benchmark records those headers.

### VRAM and GPU contention

| State | GPU memory |
| --- | --- |
| Idle (unrelated consumers only) | 1,557 MiB used / 10,310 MiB free |
| SGLang GPTQ-Int4, `mem-fraction-static=0.65` (direct run) | 9,531 MiB used before, 10,231 MiB after (29% util) |
| During E2E c=1 | 10,231 MiB used / 1,636 MiB free (44% util) |

SGLang's static pool is `0.65 x 12,227 = 7,948 MiB` plus ~1.5 GiB of unrelated
consumers, leaving ~1.6 GiB free. The OpenJev API process consumes **no GPU
memory of its own** (its Python frontend logs "PyTorch was not found" and only
loads the tokenizer). Concurrent SGLang load from OpenJev and from chat is
therefore exactly the contention scenario that the end-to-end level exercises -
and it is what crashes (below).

### Stability - SGLang crash under mixed concurrency

Direct OpenJev (c=1/2/4/8) and baseline (c=1/2/4/8) are stable. But when OpenJev
`token_ids_logprob` requests and chat `/v1/chat/completions` decoding are in
flight **together** (E2E c>=2), the SGLang 0.5.20 scheduler aborted:

~~~~text
[2026-09-20 06:58:44] Scheduler hit an exception: Traceback (most recent call last):
  ...
  File ".../sglang/srt/managers/scheduler_components/batch_result_processor.py", line 1113, in _normalize_decode_outputs
    v.tolist() for v in logits_output.next_token_token_ids_logprobs_val
AttributeError: 'list' object has no attribute 'tolist'
~~~~

The scheduler process exited and the server shut down; the E2E c=2 sub-run
recorded 16/18 errors and the recorded VRAM after that run shows the server gone
(1,557 MiB used). This is an SGLang bug in the per-request token-logprob path,
triggered by colocating the OpenJev classifier and the chat model on one server.
Retrying with `--disable-overlap-schedule` did not produce a usable matrix
(the server died again - see below), so E2E results at c>=2 are **not measured**
and the c=8 end-to-end comparison is unavailable.

### GPU fault - bus loss recurrence

During the `--disable-overlap-schedule` rerun the scheduler failed with

~~~~text
torch.AcceleratorError: CUDA error: unspecified launch failure
~~~~

and the GPU disappeared (container `nvidia-smi`: `No devices were found`), so
that run recorded `error_rate=1.0`. This is the same class of driver/hardware
fault first seen at 02:37 during this work:

~~~~text
Sep 20 02:37:20 NVRM: GPU0 kgmmuInvalidateTlb_GM107: TLB invalidation failed waiting for prior invalidate (status=0x0000000f)
Sep 20 02:37:20 NVRM: GPU0 nvCheckOkFailedNoLog: Check failed: GPU lost from the bus [NV_ERR_GPU_IS_LOST]
~~~~

Recovery requires an `nvidia` module reload or a reboot (root), which this
environment does not have. All results above were obtained **before** the second
fault. This host's RTX 5070/driver 615.71.09 combination is therefore a
reliability risk for any always-on GPU deployment, independent of OpenJev.

### Methodology (reproducible)

`scripts/benchmark_openjev_routing.py` reuses the project's own representative
examples - `akorin.api.agent.PAYLOAD_EXAMPLES` plus the expected-route mapping
from `tests/test_llm.py` - extended with ambiguous, no-match, short, long and
multilingual cases (39 cases). It has three levels: `openjev` (direct
`/v1/systemone`), `baseline` (`SemanticRouter -> CommandAgent -> LLM`) and `e2e`
(the full `/api/agent/` path with and without the OpenJev router). It computes
accuracy, per-route accuracy, false positives/negatives, fallback rate and
confidence at thresholds 0.70/0.80/0.90/0.95, and writes JSON to
`build/bench/results/` (git-ignored).

~~~~sh
# 1. SGLang GPTQ-Int4 on :30000
docker run -d --name bench-sglang --gpus all --ipc=host -p 30000:30000 \
  -v "$PWD/build/bench/hf:/root/.cache/huggingface" \
  --entrypoint python lmsysorg/sglang:latest \
  -m sglang.launch_server --model-path Qwen/Qwen2.5-3B-Instruct-GPTQ-Int4 \
  --host 0.0.0.0 --port 30000 --context-length 4096 --mem-fraction-static 0.65
# 2. OpenJev against it on :8090
cd build/bench && HF_HOME="$PWD/hf" ./openjev-venv/bin/openjev serve \
  --connect http://127.0.0.1:30000 \
  --model Qwen/Qwen2.5-3B-Instruct-GPTQ-Int4 \
  --served-model-name Qwen/Qwen2.5-3B-Instruct-GPTQ-Int4 --host 127.0.0.1 --port 8090
# 3. the benchmark
uv run python scripts/benchmark_openjev_routing.py \
  --levels openjev,baseline --concurrency 1,2,4,8 --repeats 3 \
  --model Qwen/Qwen2.5-3B-Instruct-GPTQ-Int4 \
  --output build/bench/results/openjev-routing-gpu-direct.json
~~~~

### Measured - existing router quality (CPU baseline)

With the GPU unavailable earlier, the **functional baseline** (the existing
`SemanticRouter -> CommandAgent`) was measured on CPU against the project's
Ollama server (`qwen2.5:3b`, native JSON mode). This is a routing-quality
baseline, not a latency comparison against the GPU numbers above.

| Concurrency | p50 (ms) | p95 (ms) | req/s | Accuracy | FP | FN |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 1235.46 | 1603.26 | 0.77 | 0.9487 | 2 | 2 |
| 2 | 2362.72 | 3087.35 | 0.81 | 0.9487 | 2 | 2 |
| 4 | 4939.11 | 5940.10 | 0.77 | 0.9487 | 2 | 2 |

Per-route accuracy at every concurrency: chat 1.00, isinmi 1.00, kansa 1.00,
ojo 1.00, isakoso 0.889, rediyo 0.75. The GPU baseline reproduces the same
accuracy (0.9487) with the same per-route profile, confirming the routing-quality
baseline is stable across backends.

### Integration decision

**OpenJev is not integrated.** It stays optional and off by default (present
only when `OREMI_AKORIN_OPENJEV_URL` is set); no production path was changed for
this work. The benchmark shows that, with the existing label set on this model:

- **Routing correctness regresses** (0.7692 vs 0.9487) and the errors are
  confidently wrong, so no confidence threshold recovers the baseline;
- **Colocating it with chat on one SGLang 0.5.20 server crashes the scheduler at
  c>=2**, so even the latency/throughput advantage is not reachable in the
  intended deployment; and
- A hung OpenJev adds ~4 s to every request before falling back.

A future attempt would need, at minimum: a corrected classification prompt/label
design validated by a pre-registered quality run that meets or beats 0.9487;
OpenJev pointed at its own SGLang instance (or a fixed SGLang version without the
token-logprob batching bug); and a rerun of this exact benchmark.

### Limitations

- **GPU bus loss** ended the session after the direct and c=1 end-to-end
  measurements; E2E at c=2/4/8 and the `--disable-overlap-schedule` mitigation
  could not be measured.
- The classifier model is **GPTQ-Int4**, not the pre-registered BF16, because
  BF16 could not fit alongside unrelated GPU consumers on the retagged image
  (see "Why GPTQ-Int4 and not BF16"). Baselines and OpenJev share the server.
- The `e2e-baseline` sub-run always executes before `e2e-openjev` and absorbs
  cold-start; the warm rerun is reported to bound that effect.
- OpenJev `confidence` is distribution concentration, not calibrated
  correctness; the threshold sweep is exploratory, not a calibrated operating
  point.
- The CPU baseline is Ollama `qwen2.5:3b`, not SGLang, so its latency is not
  comparable with the GPU tables; only its accuracy is directly comparable.
