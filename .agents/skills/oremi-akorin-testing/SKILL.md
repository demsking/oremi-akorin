---
name: oremi-akorin-testing
description: Testing workflow for Oremi Akọrin. Use when adding features, fixing bugs, changing routing, agents, MCP integrations, tools, caching, HTTP behavior, or performance-sensitive behavior.
---

# Oremi Akọrin Testing

Use the existing test architecture rather than introducing a new testing framework or fixture system.

## Required approach

Before changing code:
- Read the relevant tests.
- Identify the existing seam used to isolate the behavior.
- Prefer testing observable behavior over implementation details.

## Existing seams

- Outbound HTTP: `httpx2.MockTransport`.
- Application HTTP: `httpx2.ASGITransport(app=app)`.
- App lifecycle: `async with app.router.lifespan_context(app):`.
- LLM determinism: monkeypatch `AgentClient.build_model` with Pydantic AI `TestModel` or `FunctionModel`.
- MCP sessions/agents: `AsyncMock`, `MagicMock`, and `patch`.
- Settings: use the existing `isolated_settings(...)` pattern.

## Test rules

- Use pytest + pytest-asyncio.
- Follow the repository's explicit `@pytest.mark.asyncio` style.
- Keep tests independent and deterministic.
- Do not require external Oremi services for unit tests.
- Do not require a real Ollama server for unit tests.
- Add regression tests for bugs before or alongside the fix.
- Test timeout and failure paths when modifying resilience behavior.
- Test cache invalidation/volatile context when modifying caching.
- Test router precedence when modifying routing.
- Test public request/response contracts when modifying API models or endpoints.

## Performance tests

When changing latency-sensitive code:
- Establish a baseline.
- Use representative input.
- Measure enough iterations to reduce noise.
- Prefer testing the changed component separately before full-stack timing.
- Verify that concurrency does not create race conditions or resource exhaustion.
- Keep benchmarks out of the normal unit suite unless they are deterministic and intentionally maintained.

## Commands

Normal suite:

`uv run pytest tests/ -q`

Full repository gate:

`devbox run prek run --all-files`
