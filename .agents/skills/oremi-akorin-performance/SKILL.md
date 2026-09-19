---
name: oremi-akorin-performance
description: Performance and latency engineering guidance for Oremi Akọrin's real-time natural-language request path. Use when changing routing, LLM calls, MCP calls, caching, concurrency, startup, or any latency-sensitive code.
---

# Oremi Akọrin Performance

Oremi Akọrin is an interactive natural-language gateway. User-perceived latency is a first-class requirement.

## Performance model

Treat the request path as:

HTTP -> language detection -> prompt/component discovery -> routing -> LLM/tool execution -> response shaping -> device commands.

For every change, identify:
- latency added to the critical path,
- calls that can execute concurrently,
- calls that can be cached,
- calls that can be skipped,
- timeout boundaries,
- failure isolation,
- memory/concurrency implications.

## Rules

### Async I/O
- All external I/O must remain asynchronous.
- Reuse the shared `httpx2.AsyncClient`.
- Reuse MCP component sessions according to `ComponentClient` lifecycle.
- Never use blocking HTTP libraries, `time.sleep`, synchronous subprocesses, or filesystem operations in request handlers.
- Use `asyncio.gather` only for independent operations.

### Routing
- Preserve deterministic fast routing before expensive LLM semantic routing.
- Do not move expensive classification earlier in the pipeline without measured justification.
- Keep router decisions bounded by the existing request budget.
- Avoid repeated language detection, prompt selection, or route classification.

### LLM
- All LLM calls go through `AgentClient`.
- Preserve `SmartCache`.
- Keep tool loops bounded.
- Avoid redundant model calls.
- Do not increase prompts or tool schemas unnecessarily.
- Prefer deterministic preprocessing when it safely eliminates an LLM call.
- Preserve streaming/interaction behavior if the surrounding API supports it; do not introduce buffering that increases time-to-first-response without an explicit reason.

### MCP and services
- Avoid serial discovery of independent component prompts.
- Preserve concurrent prompt fetching.
- Respect circuit breakers and request timeouts.
- Do not retry aggressively in the user request path.
- Fail fast for unavailable components and preserve fallback behavior.

### Cache
- Understand volatile context before adding caching.
- Do not cache personalized or time-sensitive results incorrectly.
- Prefer existing single-flight/stale-while-revalidate mechanisms over new cache implementations.
- Keep cache keys deterministic and cheap to construct.

### CPU
- Keep expensive CPU work outside the request path where possible.
- Do not introduce heavyweight NLP/model initialization per request.
- Reuse initialized spaCy and other resources.

## Measuring changes

For non-trivial performance changes, record:
- p50 latency,
- p95 latency,
- p99 latency when enough traffic exists,
- time spent in routing,
- LLM duration,
- MCP/network duration,
- cache hit/miss behavior,
- error/timeout rate.

Do not claim a performance improvement without measurement.

## Guardrails

Performance work must not:
- weaken validation,
- expose secrets,
- bypass `AgentClient`,
- bypass MCP abstractions,
- remove timeout protection,
- introduce uncontrolled concurrency,
- change public API behavior without an explicit requirement.
