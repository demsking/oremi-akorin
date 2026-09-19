---
name: oremi-akorin-architecture-review
description: Architecture review workflow for Oremi Akọrin. Use before or during significant changes to routing, orchestration, agents, MCP, tools, public APIs, or cross-cutting infrastructure.
---

# Oremi Akọrin Architecture Review

The existing architecture is authoritative. The purpose of this skill is to prevent accidental architectural drift.

## Boundaries

- `api/`: HTTP surface only.
- `core/orchestrator.py`: pipeline coordination, routing order, dispatch, budgets, failure policy.
- `core/agent.py`: centralized LLM backend selection, caching, and tool-loop mechanics.
- `agents/`: prompt/configuration-specific LLM behavior.
- `core/components.py`: MCP lifecycle, caching, circuit breaker.
- `components/`: service-specific MCP client identities.
- `core/tools.py`: tool contracts and registry.
- `tools/`: native tools.
- `routers/`: routing strategies.
- `utils/`: stateless helpers.

## Review questions

1. Does the change belong in the proposed layer?
2. Can an existing abstraction be extended instead?
3. Does it preserve router precedence?
4. Does it preserve the `AgentClient` funnel?
5. Does it preserve MCP lifecycle and failure isolation?
6. Does it preserve `app.state` dependency injection?
7. Does it preserve public request/response contracts?
8. Does it introduce new latency into the critical path?
9. Does it add a dependency that existing code cannot already support?
10. Does it create a new abstraction where an existing one is sufficient?

## Architectural red flags

Stop and reconsider if a change:
- calls Ollama or Pydantic AI directly from an agent subclass,
- creates an HTTP client inside a request handler,
- places business logic in `api/`,
- bypasses MCP component clients,
- duplicates caching or circuit-breaker logic,
- introduces synchronous I/O,
- changes routing order without explicit justification,
- adds a dependency for functionality already provided by the standard library or current dependencies,
- performs broad refactoring while implementing an unrelated feature.

## Decision record

For significant architectural changes, document:
- current behavior,
- problem,
- constraints,
- proposed change,
- alternatives considered,
- latency impact,
- compatibility impact,
- test strategy,
- rollback considerations.

Prefer incremental changes over architectural rewrites.
