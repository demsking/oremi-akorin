---
name: oremi-akorin-coding-agent
description: Repository-specific AI coding workflow for Oremi Akọrin. Use for implementation, debugging, refactoring, testing, architecture changes, performance work, and code review in this repository.
---

# Oremi Akọrin Coding Agent

Use the repository's `AGENTS.md` as the primary source of truth. The existing human-written implementation takes precedence over generic best practices.

## Operating priorities

1. Preserve the existing architecture and behavior.
2. Keep request latency low and throughput high enough for real-time interaction.
3. Make the smallest coherent change.
4. Prefer existing abstractions and dependencies.
5. Validate behavior with tests and repository tooling.
6. Never trade correctness or security for speculative performance.

## Mandatory workflow

### 1. Understand
- Read `AGENTS.md`.
- Read the target module and its direct callers.
- Identify the affected architectural layer.
- Read related tests before editing.
- Search for existing helpers, abstractions, settings, exceptions, agents, tools, and patterns.

### 2. Plan
- State the minimal files that need to change.
- Identify synchronous/blocking work in the request path.
- Identify concurrency opportunities only where operations are independent.
- Identify public API, cache, routing, MCP, and LLM behavior that must remain compatible.
- Avoid redesign unless explicitly requested.

### 3. Implement
- Follow existing Python conventions exactly.
- Keep API logic in `api/`, orchestration in `core/orchestrator.py`, LLM mechanics in `core/agent.py`, MCP lifecycle in `core/components.py`, native tools in `tools/`, and pure helpers in `utils/`.
- Route all new LLM behavior through `AgentClient`.
- Reuse the shared `httpx2.AsyncClient`; never create ad-hoc HTTP clients in request handlers.
- Keep I/O asynchronous.
- Use bounded timeouts and the existing request budget.
- Use `asyncio.gather` for genuinely independent operations.
- Preserve cache semantics and volatile-context handling.
- Never introduce `eval`/`exec`, arbitrary outbound URLs, hardcoded secrets, or unnecessary dependencies.

### 4. Performance rules
Oremi Akọrin is an interactive natural-language gateway. Optimize for perceived response time as well as total throughput.

- Do not add sequential network calls when they can safely run concurrently.
- Do not perform blocking CPU, filesystem, subprocess, or network work on the async request path.
- Keep fast-path routing fast; avoid invoking an LLM when deterministic routing can safely answer the routing question.
- Preserve the existing router precedence: fast deterministic matching before more expensive semantic/LLM routing.
- Reuse clients, connections, caches, and MCP sessions according to existing lifecycle rules.
- Avoid unnecessary serialization, copying, prompt construction, or repeated discovery.
- Respect request budgets and component circuit breakers.
- Avoid unbounded concurrency; use bounded concurrency when fan-out can grow.
- Measure before optimizing non-obvious hotspots.
- Do not add caching to volatile or user-specific data without understanding correctness implications.
- Never sacrifice timeout/error isolation merely to reduce latency.

### 5. Validate
At minimum, run:
- `ruff check .`
- `uv run pytest tests/ -q`
- `devbox run prek run --all-files` when the environment supports it.

For performance-sensitive changes, also compare before/after behavior with a reproducible benchmark or timing measurement when practical.

### 6. Review
Before finishing:
- Inspect the git diff.
- Check that unrelated files were not modified.
- Check public API compatibility.
- Check generated-file and secret rules.
- Check latency implications.
- Check that tests cover changed behavior.
- Update `.env.example` and `DOCUMENTATION.md` when settings or public behavior changes.

## Definition of done

A change is complete only when it is minimal, tested, architecturally consistent, security-conscious, and does not introduce avoidable latency in the interactive request path.
