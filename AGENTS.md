# Oremi Akọrin — AI Coding Agent Guide

This document is the operating manual for AI coding agents working on
**Oremi Akọrin**. It is derived from the existing repository, which was written
by humans without LLM assistance. The existing implementation is the source of
truth: do not redesign, modernize, or refactor it to match another style. When
this document and the code disagree, trust the code and update this document.

## Project Overview

Oremi Akọrin is the natural-language gateway for the Oremi ecosystem. It
accepts user requests over HTTP, uses an LLM to understand, classify, and route
them, and dispatches each request to the appropriate Oremi service or to a
built-in tool. It preserves the user's original language.

- Package: `oremi-akorin` (import package `akorin`), version in `pyproject.toml` (currently `1.0.0b14`).
- Console entry point: `oremi-akorin = "akorin.__main__:start"`.
- Default HTTP port: `5020`. Interactive docs at `/docs/`.
- The name "Akọrin" is Yoruba for "singer"; "Oremi" comes from "ọrẹ mi" ("my friend").
- License: Apache-2.0. Every Python file must carry the header in `LICENSE_HEADER.txt`.

## Repository Structure

```
pyproject.toml          # packaging, dependency groups, pytest + (redundant) ruff config
ruff.toml               # EFFECTIVE Ruff config (takes precedence over pyproject.toml)
Makefile                # canonical command surface (install/test/lint/package/docker/release)
devbox.json             # dev toolchain: uv, ruff, prek, bandit, hadolint, spaCy runtime libs
.pre-commit-config.yaml # hook definition used by prek (pre-commit replacement)
.gitlab-ci.yml          # GitLab SAST + GitLab Pages docs deploy
Dockerfile              # multi-stage alpine image; runs `python /oremi/akorin`
compose.yaml            # local dev stack: oremi-* services, mosquitto, ollama
config/                 # mosquitto broker config
scripts/generate-docs-files.py  # generates htdocs/index.html + htdocs/openapi.json
htdocs/                 # favicon.png, logo.png (generated index/openapi are build outputs)
tests/                  # pytest suite (a package: tests/__init__.py)
akorin/
  __init__.py           # module-level `app` + `settings`; validates settings on import
  __main__.py           # CLI entry point (argparse + uvicorn)
  core/                 # settings, app factory, orchestrator, router contracts, agent base,
                        # tools registry, component client, request/response models, exceptions
  api/                  # FastAPI routers: agent.py, health.py, docs.py
  agents/               # LLM agents built on core/agent.AgentClient
  routers/              # request routers: spacy_router, mcp_router, semantic_router
  components/           # thin MCP clients per external Oremi service
  tools/                # native (local) tools: datetime, calculator, unit conversion
  utils/                # cache, logging, language, context filters, device commands, url
```

Subpackages under `akorin/` have **no** `__init__.py` (they are implicit
namespace packages). Only `akorin/__init__.py` and `tests/__init__.py` exist.
Do not add `__init__.py` files to `akorin/*` without a deliberate reason.

## Architecture

### Request pipeline

`POST {api_prefix}/api/agent/` → `akorin/api/agent.py::process_user_input` →
`akorin/core/orchestrator.py::Orchestrator.process`:

1. Detect language with `akorin/utils/language.py::detect_language` (py3langid → ISO 639-1 string).
2. Fetch prompt templates from every configured component concurrently
   (`_fetch_all_prompts`). Failures are logged and skipped, never fatal.
3. Run the routing chain in `Orchestrator.routers`, **first match wins**:
   - `SpacyRouter` (`routers/spacy_router.py`) — spaCy `blank("fr")` phrase/token
     matchers. Phrase match confidence `0.98`, token match `0.95`.
   - `McpPromptRouter` (`routers/mcp_router.py`) — picks an MCP prompt via `PromptSelectorAgent`, confidence `1.0`.
   - `SemanticRouter` (`routers/semantic_router.py`) — LLM classification via `CommandAgent`,
     bounded by `_timeout_for(...)` against `request_budget_seconds`.
   - Fallback: `RouteSemanticDecision(service=Service.CHAT, confidence=0.0)`.
4. Dispatch by service:
   - `Service.CHAT` → `_execute_chat_service`: `ChatToolsAgent` with registry tools plus
     MCP resource/prompt tools. If tools ran, the result service becomes the tool's service
     when it is one of `{rediyo, kansa, isinmi}`, otherwise `Service.TOOL`.
   - Any other service → `_execute_mcp_service`: get the component's tools, optionally
     render the selected prompt (which **replaces** the user message), run `ChatToolsAgent`,
     and use the last tool that is not `search_locations`/`reverse_geocode` as primary result.
5. Failures → `_handle_execution_failure`:
   `ComponentRequestError` → "needs more information"; `ComponentUnavailable` →
   "temporarily unavailable"; anything else → fall back to plain chat with
   `confidence = min(decision.confidence, 0.5)`. An HTTP failure during the fallback
   yields `ok=false`.
6. Build `ProcessResponse`, attach device commands via
   `akorin/utils/response_commands.py::select_device_commands`, and log duration.

HTTP behavior: the agent endpoint returns **HTTP 200** for processed requests, including
expected failures — clients must inspect the `ok` field. `422` is input validation,
`500` is an unhandled error.

### Layers and boundaries

- `api/` = HTTP surface only. It resolves dependencies from `request.app.state` and
  delegates to `Orchestrator`. Keep business/routing logic out of `api/`.
- `core/orchestrator.py` = pipeline coordination. It owns the router chain, dispatch,
  timeouts, and failure policy.
- `core/router.py` = contracts (`RouteContext`, `RouteDecision` union, `RequestRouter` ABC).
  Concrete routers live in `routers/`.
- `agents/` = prompt construction and thin methods over `core/agent.AgentClient`.
  All LLM/caching/tool-loop mechanics belong to `AgentClient`, not to individual agents.
- `core/components.py` = the MCP client (session lifecycle, cache, circuit breaker).
  `components/*.py` are intentionally near-empty subclasses that name a service.
- `core/tools.py` = tool protocol, registry, native tool result shape, MCP-tool wrapper.
- `tools/` = native tools only. They implement the `OllamaTool` protocol and return
  `ToolResult`.
- `utils/` = stateless helpers (cache, logging, language, context filtering, URLs).

### Routing and dependency injection

`akorin/core/app.py::create_app(settings, http_client=None)` is the composition root.
It builds settings, the shared `httpx2.AsyncClient`, the `SmartCache`, the component
clients, the `ToolRegistry`, and the `Orchestrator`, stores them on `app.state` through
`akorin/core/context.py`, and manages them in the FastAPI `lifespan`. The injectable
`http_client` parameter exists specifically so tests can pass an `httpx2.MockTransport`.

### Dual LLM backend

`AgentClient` (`akorin/core/agent.py`) selects a backend at construction time:

- If `settings.llm_model` starts with `ollama:`, use the native `ollama.AsyncClient`
  (tool loop implemented manually, max 5 iterations). `ollama_base_url` is mandatory.
- Otherwise use the Pydantic AI `Agent` route (model string passed through to Pydantic AI).

Every agent exposes a specific Pydantic AI configuration via class attributes:
`SYSTEM_PROMPT`, `RESULT_TYPE`, `RESPONSE_FORMAT`, and an overridable
`_get_model_settings()`. All LLM calls funnel through `_run` / `_run_with_tools` and
the `SmartCache`. Do not call `ollama` or Pydantic AI directly from agent subclasses.

## Core Domain Concepts

- **The Oremi services** (named in Yoruba): `isinmi` (schedules/alarms/reminders),
  `ojo` (weather/air quality/pollen/alerts), `rediyo` (radio), `kansa` (podcasts),
  `isakoso` (smart-home/Zigbee). `akorin` itself is the gateway. These are the
  string values of `Service` in `akorin/core/service.py`.
- **Service routing vs. chat**: `Service.CHAT` means the LLM answers directly;
  `Service.TOOL` means a native or MCP tool produced the data; every other value is an
  external Oremi component.
- **MCP components**: external services are reached over the MCP *streamable HTTP*
  endpoint, conventionally `http://host:port/mcp`. Each component exposes some of
  tools, resources, and prompts. Never assume all three are present.
- **Prompt templates**: an MCP component can publish named prompts with typed arguments.
  `SpacyRouter`, `McpPromptRouter`, and `_execute_mcp_service` select/render them; when a
  prompt is rendered it replaces the user message sent to the LLM. `SelectedPrompt`
  arguments are always strings.
- **Context and preferences**: `ProcessRequest.context` is a free-form dict carrying
  device/environment state (timezone, coordinates, temperature unit, device info...).
  Callers may nest device settings under `preferences`. `context_for_service` selects only
  the keys a given service may see — never forward the raw context to a component.
  `context["tools"][<tool_name>]` provides per-tool argument defaults.
- **Volatile context**: keys such as `datetime`, `date`, `time`, `timestamp`, `now`
  (see `VOLATILE_CONTEXT_KEYS`) disable caching, because answers depend on the moment.
- **Device commands**: `ProcessResponse.commands` is an ordered, discriminated union of
  `OremiDeviceCommand` models (speak/announce/play/pause/resume/stop/alarm/reminder/
  cancel_scheduled/set_volume/mute/set_voice). They are derived from service results by
  `select_device_commands`; a plain `speak` with the response message is the universal
  fallback.
- **Language preservation**: the user's detected language is echoed in the response and
  injected into prompts. Prompts instruct the model to answer only in that language.
  Do not hardcode English or French user-facing strings; user messages are generated by
  `ResponseAgent`.

## Development Environment

Toolchain is managed by **Devbox** + **direnv**; dependencies by **uv**. Python **3.12+**
(`requires-python = ">=3.12"`; all tooling targets `py312`).

```sh
direnv allow          # load the devbox environment
make install          # recreate .venv (uv venv --python 3.12 && uv sync)
make shell            # start the tmuxinator dev session (docker stack + logs)
make up / make down   # start / stop the compose stack
make logs / make ps   # compose logs / status
make tests            # uv run pytest tests/ -v
make lint             # devbox run prek run --all-files
make fix              # ruff check . --fix
```

Run the API without Docker (matches `.vscode/launch.json`):

```sh
uv run uvicorn akorin:app --reload --reload-dir akorin --host 0.0.0.0 --port 5020
```

A minimal local run needs `OREMI_AKORIN_OLLAMA_BASE_URL` when the model is
`ollama:...`. Use `.env.example` as the reference environment; `compose.yaml` starts the
Oremi services and Ollama for integration work.

## Python Conventions

- **Indentation: 2 spaces**, LF line endings, final newline, no trailing whitespace
  (`.editorconfig`, `ruff.toml`). Never introduce 4-space indentation.
- **Line length**: `ruff.toml` sets 128 and is the effective config (verified: Ruff reports
  `Settings path: .../ruff.toml`). `pyproject.toml` also has a `[tool.ruff]` block (120)
  that Ruff does **not** use; leave both files consistent if you touch them.
- **Quotes**: double quotes for code and docstrings (`ruff.toml`).
- **Imports**: absolute, one symbol per line, grouped stdlib → third-party → first-party,
  blank line between groups. `reorder-python-imports` enforces this in pre-commit.
  Add `from __future__ import annotations` when a module uses forward references
  (the agent/utility modules do; most others do not).
- **Naming**: `PascalCase` classes and Pydantic models; `snake_case` functions, methods,
  variables, modules; `_leading_underscore` for private helpers; `UPPER_SNAKE_CASE` for
  module constants and class-level `definition`/prompt constants.
- **Type hints are mandatory** on public and private functions/methods, including return
  types. Use modern syntax: `str | None`, `list[str]`, `dict[str, Any]`, `Annotated`,
  `Literal`, `ClassVar`, `TYPE_CHECKING` for import cycles. mypy runs in `--strict`
  (excluding `tests/`), so untyped definitions will fail the hook.
- **Type-ignore comments are exception-based**, not the norm: `# type: ignore[...]` for
  untyped third-party imports and Pydantic constructor edge cases; `# pyright: ignore`
  only around the dynamic Pydantic AI/Ollama calls in `core/agent.py`. Prefer a correct
  annotation over a new ignore.
- **Models and abstractions**:
  - Pydantic v2 `BaseModel` for API/settings/route/response models (with `Field(...)`,
    validators, `ConfigDict`).
  - `@dataclass(frozen=True, slots=True)` for small immutable value objects
    (`ChatResult`, `ToolResult`, `CacheStats`).
  - `abc.ABC` + `@abstractmethod` for `RequestRouter`; `typing.Protocol` for
    `OllamaTool`; `Generic[...]` for `AgentClient`.
  - `enum.StrEnum` for closed sets such as `Service`.
- **Docstrings**: short double-quoted one-liners on public classes and non-obvious methods,
  phrased imperatively (`"""Return cached application settings."""`). Module docstrings are
  not used; the license header is. Ruff does not lint docstring rules (D rules unselected).
- **Logging**: module-level `logger = logging.getLogger(__name__)` in every module that
  logs. Most call sites use f-strings, with request-scoped prefixes
  `f"[{request_id}] ..."`; `core/components.py` and `utils/cache.py` use lazy
  `%s`-style. Match the style of the file you edit.
- **Async**: all I/O is `async`/`await`; no blocking HTTP or sleeps in the request path.
  Use `asyncio.gather` for independent calls, `asyncio.wait_for` plus the request budget
  for timeouts, and `asyncio.Event` for background-loop shutdown.
- **Errors**: raise the project exceptions (`OremiError`, `ComponentUnavailable`,
  `ComponentRequestError`) for expected failures. Component methods translate transport
  errors into `ComponentUnavailable`. Native tools return
  `ToolResult(data={"error": ...})` instead of raising for bad user input.
- **Configuration**: `pydantic-settings` `BaseSettings` with `env_prefix="OREMI_AKORIN_"`,
  `strict=True`, `extra="ignore"`. Add new settings as typed `Field(...)` with bounds and a
  `description`; access the cached singleton via `get_settings()`.
- **Resource management**: the shared `httpx2.AsyncClient` is created once in `create_app`
  and closed in the lifespan; component sessions use `contextlib.AsyncExitStack`. Do not
  create ad-hoc HTTP clients in request handlers.

## Code Organization — Where New Code Belongs

| You are adding... | Put it in |
| --- | --- |
| A new external Oremi service | `akorin/components/<name>.py` (subclass `ComponentClient`), a `Service` member, a `Settings` URL field, a row in `create_app` `configured_components`, and `_SERVICE_CONTEXT_KEYS` |
| A new native tool | `akorin/tools/<name>_tool.py` implementing `OllamaTool`, registered in the `ToolRegistry([...])` in `create_app` |
| A new routing strategy | `akorin/routers/<name>_router.py` subclassing `RequestRouter`, inserted into `Orchestrator.routers` in the correct precedence position |
| A new LLM behavior/agent | `akorin/agents/<name>_agent.py` subclassing `AgentClient`, overriding only prompt/config, plus a field on `Orchestrator` |
| A new HTTP endpoint | `akorin/api/<name>.py` with an `APIRouter` and `API_TAG_METADATA`, included in `create_app` |
| Shared pure helpers | `akorin/utils/` (no FastAPI/LLM imports) |
| New settings | `akorin/core/settings.py` and document in `.env.example` + `DOCUMENTATION.md` |

## Testing

- Framework: **pytest** with **pytest-asyncio**. `pyproject.toml` sets
  `asyncio_mode = "auto"` and `testpaths = ["tests"]`. Tests nevertheless decorate
  coroutines with `@pytest.mark.asyncio` explicitly — follow that.
- Layout: flat files `tests/test_<area>.py`; `tests/` is a package. There is **no
  `conftest.py`** and no shared fixture library; helpers (`isolated_settings`,
  fake MCP types, `ollama_handler`) are defined per module. Cross-test imports are
  allowed (e.g. `from tests.test_smart_cache import SmartCache`).
- Test naming: `test_<behavior>` describing the observable behavior. Parametrize with
  `@pytest.mark.parametrize` for input matrices (see `test_tools.py`).
- Mocking strategy:
  - `unittest.mock.AsyncMock` / `MagicMock` / `patch` for MCP sessions and agents.
  - `httpx2.MockTransport` for outbound HTTP; inject it through
    `create_app(settings, service_client)`.
  - `httpx2.ASGITransport(app=app)` to drive the app in-process.
  - Enter the app lifecycle with `async with app.router.lifespan_context(app):` around requests.
  - Force deterministic LLMs by monkeypatching
    `AgentClient.build_model` to return `pydantic_ai.models.test.TestModel` or
    `FunctionModel`; this is the supported seam, do not bypass it.
  - Build settings with an `isolated_settings(**overrides)` helper that sets
    `llm_model="test"` and all service URLs to `None`.
- Run: `make tests` (`uv run pytest tests/ -v`); for a single file
  `uv run pytest tests/test_tools.py -q`. The suite currently passes cleanly.
- Whenever behavior changes — routing, prompt selection, response shaping, caching,
  context filtering, error handling — add or update a test. New external dependencies
  must never be required to run the unit suite (mock them).
- Coverage: `make coverage` uses `--cov=server`, which does not match this package and
  `pytest-cov` is not declared. Treat coverage targets as **stale**; do not rely on them.

## Quality Checks

Run before declaring work complete:

```sh
make fix                       # ruff check . --fix
uv run pytest tests/ -q        # or: make tests
devbox run prek run --all-files   # full hook suite, incl. mypy --strict
```

`make lint` runs `prek`, the installed replacement for `pre-commit`; it reads
`.pre-commit-config.yaml` and executes: trailing whitespace, AST/JSON/YAML/TOML checks,
debug-statement detection, private-key detection, license-header insertion,
`reorder-python-imports`, `ruff --fix`, `mypy --strict` (tests excluded),
`bandit -c bandit.yaml`, `hadolint` on the Dockerfile, and `make tests`.

- Ruff is configured in `ruff.toml` (`select = ["E","F","W","RUF"]`, `fix = true`);
  `ruff check .` currently passes. `B`/`I` rules are not enabled.
- mypy is not installed in the project venv; it is provisioned by the pre-commit hook.
  Use `prek` rather than expecting a local `mypy` binary.
- `bandit.yaml` deliberately skips `B101, B104, B105, B106, B110`. Do not broaden the
  skip list to silence a new finding.
- GitLab CI runs SAST and a Pages docs deploy only — it does **not** run the test suite or
  lint. Local/pre-commit checks are the real gate.

## Dependencies

Runtime (`[project].dependencies` in `pyproject.toml`): `fastapi[standard]`,
`uvicorn`, `pydantic`, `httpx2`, `pydantic-settings`, `pydantic-ai`, `ollama`,
`mcp`, `mcp-types`, `py3langid`, `spacy`.

- **`httpx2` is the HTTP client used everywhere** (`import httpx2`). It is a distinct
  package from `httpx`; the project migrated to it deliberately. Do not reintroduce
  `httpx` imports in application code. (`httpx` remains a dev dependency.)
- **MCP v2** (`mcp` + `mcp-types`) is the integration mechanism for all Oremi services,
  over streamable HTTP. Component URLs must point at the MCP endpoint.
- **Pydantic AI** defines agent output types and the non-Ollama backend;
  `pydantic_ai.models.test.TestModel`/`FunctionModel` are the test doubles.
- **Ollama** is the default local backend; the native client is used whenever the model
  id starts with `ollama:`. `OREMI_AKORIN_OLLAMA_BASE_URL` is required then.
- **spaCy** uses a blank French pipeline (`spacy.blank("fr")`) — no model download and no
  NER/parser. It is only used for the fast intent matchers.
- **py3langid** provides language detection (`Language = str`, ISO 639-1).
- Dev group: `httpx`, `pytest`, `pytest-asyncio`, `ruff`, `twine` (`make pypi`),
  `sounddevice` (declared but not imported anywhere in `akorin/`). Build backend:
  `hatchling`, wheel package `["akorin"]`.

Do not add a dependency for something the standard library, an existing dependency, or
the existing utilities can do. Any new runtime dependency must be justified in the change
and added to `pyproject.toml` (run `uv lock` so `uv.lock` stays in sync).

## Configuration and Secrets

- Every runtime setting is an environment variable prefixed `OREMI_AKORIN_` and is defined
  in `akorin/core/settings.py`. `.env.example` is the human-readable reference and must be
  kept in sync when settings are added or renamed. `DOCUMENTATION.md` also documents them.
- `SettingsConfigDict` configures only `env_prefix`, `strict=True`, and `extra="ignore"`;
  **no `env_file` is configured**, so the app reads the real process environment. `.env`
  files are loaded by external tooling (Docker `--env-file`, the VS Code `envFile`,
  `make live`), not by the application.
- Startup is fail-fast: invalid settings raise `ValidationError` in
  `akorin/__init__.py` and exit with code 1; missing Ollama URL for an `ollama:` model
  exits with code 2.
- Secrets: the repository stores none. `compose.yaml` contains a fixed local-development
  `OREMI_ISINMI_DATABASE_ENCRYPTION_KEY` for the dev stack — never reuse it in production.
- Redact URLs before logging: use `akorin/utils/url.py::safe_url`, which strips query,
  fragment, username, and password.
- There is **no application-level authentication**; the service trusts proxy headers. Only
  deploy behind a trusted proxy/network boundary, and be extra careful with changes that
  expose device control.

## Error Handling and Logging

- Exception hierarchy: `OremiError` → `ComponentUnavailable` (with `.component`,
  `.reason`) and `ComponentRequestError` (with bilingual `message_en`/`message_fr`).
  Add new expected failure types here rather than raising bare `Exception`.
- Component calls wrap transport/parse failures into `ComponentUnavailable`; a failed call
  disconnects the session so the next call reconnects. The circuit breaker
  (`_raise_if_circuit_open` / `_record_failure`) fails fast after
  `component_circuit_breaker_failures` consecutive failures for the configured cooldown.
- The request pipeline is resilient by design: routing falls through to chat, component
  prompt/tool discovery failures are logged and skipped, and user-facing failures are
  turned into natural-language messages by `ResponseAgent` (events such as
  `component_temporarily_unavailable`, `component_needs_more_information`,
  `service_execution_failed`).
- A catch-all handler in `create_app` returns `500 {"detail": "Internal server error",
  "error": str(exc)}`. Never put secrets or user data into exception messages.
- Logging is configured once by `akorin/utils/logger.py::configure_logging` (console plus
  optional 5 MB × 5 rotating file) and quiets noisy third-party loggers. Debug logs include
  request/response text — warn users before enabling `DEBUG` in production.

## Security Considerations

- No authentication/authorization is implemented. Treat every endpoint as trusted-network
  only; changes that widen device/service control deserve explicit review.
- Input is validated by Pydantic models (`ProcessRequest.message` 1–8000 chars,
  `ProcessResponse` bounds). Keep validation in models, not ad-hoc in handlers.
- The calculator tool evaluates user expressions with `ast` allow-lists, depth/exponent/
  magnitude limits — never replace it with `eval`/`exec`.
- `api/docs.py` serves static files from `htdocs/` and guards path traversal by resolving
  and checking the parent directory. Preserve that check in any refactor.
- Outbound calls go only to configured `OREMI_AKORIN_*_URL` MCP endpoints. Do not accept
  arbitrary URLs from request payloads.
- `DEBUG` logging and `str(exc)` in the 500 body can expose internals; keep error text
  generic in new code.
- bandit runs in pre-commit with a small, intentional skip list (see Quality Checks).

## Git and Change Workflow

- Single long-lived branch is `main` (the repo currently has only `main`/`origin/main`),
  but `CONTRIBUTING.md` instructs contributors to branch from `dev`:
  `git checkout dev -b feature/my-awesome-feature`. Follow that guidance for feature work.
- Merge requests are opened on GitLab (`gitlab.com/demsking/oremi-akorin`).
- Commit messages use **Conventional Commits**: `type(scope): subject` — observed types
  `feat`, `fix`, `refactor`, `chore`; scopes match the module area (`core`,
  `components`, `routers`, `routing`, `cache`, `logging`, `http`, `docs`,
  `config`, `deps`, `types`, `performance`). Release commits are
  `chore(release): bump version to <version>`.
- Versioning is SemVer via `uv version`; `make bump VERSION=x.y.z` commits the bump and
  `uv.lock`; `make alpha|beta|rc|patch|minor|major` bump and `make release` tags.
  `make publish` pushes to PyPI + Docker Hub and pushes `main` and the tag.
- Never edit or commit generated/ignored artifacts: `htdocs/index.html` and
  `htdocs/openapi.json` (produced by `scripts/generate-docs-files.py`), `dist/`,
  `build/`, caches, or `.venv/`.
- `uv.lock` is tracked: run `uv lock` after changing dependencies.
- Do not rewrite history, force-push, or re-tag releases.

## Common Development Tasks

**Add a native tool.** Create `akorin/tools/<name>_tool.py` with a class that has `name`,
a JSON-schema `definition: ClassVar[dict[str, Any]]`, and
`async execute(arguments, context) -> ToolResult`; register it in the
`ToolRegistry([...])` in `create_app`; document it in `DOCUMENTATION.md` "Native tools";
add tests alongside `tests/test_tools.py`.

**Add an external Oremi service.** Add a `Service` member, a `Settings` URL field plus its
`.env.example` entry, an `akorin/components/<name>.py` subclass, a `configured_components`
row in `create_app`, and context keys in `_SERVICE_CONTEXT_KEYS`. If it must be routable
by keywords, extend `SpacyRouter` patterns and the `CommandAgent` system prompt, and add
tests to `tests/test_spacy_router.py` and `tests/test_llm.py`.

**Add a router.** Subclass `RequestRouter`, implement
`async route(context) -> RouteDecision | None` (return `None` to defer), and insert it into
`Orchestrator.routers` — order is precedence, and the fast `SpacyRouter` runs first.

**Add an API endpoint.** Add an `APIRouter` module under `akorin/api/` with
`API_TAG_METADATA`, resolve dependencies via `akorin/core/context.py`, include it in
`create_app` with the correct prefix (business endpoints under `{prefix}/api`), and cover it
with an ASGI-transport test.

**Add or change a setting.** Edit `Settings` with bounds + description, update
`.env.example` and `DOCUMENTATION.md`, and add it to the relevant `log_group(...)` call in
`create_app` so startup logs stay complete.

**Run the dev stack.**
```sh
make shell   # tmuxinator session: make up + logs + git status
make up      # docker compose up -d --remove-orphans
make down
```

**Regenerate API docs (build only).**
`python scripts/generate-docs-files.py` writes `htdocs/index.html` and
`htdocs/openapi.json`; do not commit them.

## Important Files and Modules

- `akorin/core/settings.py` — all configuration and validation.
- `akorin/core/app.py` — composition root, lifespan, component wiring, HTTP mount points.
- `akorin/core/orchestrator.py` — the request pipeline and failure policy.
- `akorin/core/agent.py` — `AgentClient`: backend selection, caching, tool loop; the
  `build_model` seam used by tests.
- `akorin/core/components.py` — MCP client lifecycle, smart cache, circuit breaker.
- `akorin/core/router.py` — route decision models and the `RequestRouter` contract.
- `akorin/core/tools.py` — `OllamaTool`, `ToolResult`, `ToolRegistry`, MCP adapters.
- `akorin/core/request.py` / `akorin/core/response.py` — the public HTTP contract.
- `akorin/core/context.py` — typed accessors for `app.state`.
- `akorin/routers/spacy_router.py` — the fast intent matcher; the largest, most
  pattern-dense module. Edit patterns cautiously and keep the tests green.
- `akorin/utils/cache.py` — `SmartCache` (TTL, stale-while-revalidate, single-flight) and
  volatile-context detection.
- `akorin/utils/service_context.py` — the context allow-list per service.
- `akorin/utils/response_commands.py` — service result → Oremi Device commands.
- `akorin/__init__.py` — importing `akorin` constructs the app and validates settings;
  tests import submodules (`akorin.core.*`) directly to avoid that side effect.

### Generated / do-not-edit casually

`htdocs/index.html`, `htdocs/openapi.json` (generated), `dist/`, `build/`,
`uv.lock` (regenerate, don't hand-edit), and every cache/venv directory.

## Known Inconsistencies and Legacy Areas

These are established findings. Handle them deliberately, do not silently "fix" them as
part of an unrelated change, and do not build new features on top of them.

- `Settings.spellcheck_timeout_seconds` and `Settings.skip_spellcheck_max_chars` are
  declared and logged but **never used** — no spellcheck/normalization stage exists.
  `DOCUMENTATION.md` still describes spellcheck behavior. The docs are ahead of the code.
- `Settings.service_urls` omits `isakoso_url` and is used only for startup logging;
  `configured_services` and `has_services` are effectively dead.
- `Orchestrator._timed` and `ComponentServiceInfo` are unused.
- `Service.OREMI_DEVICE` (`"device"`) appears only as an enum constant / example context; it
  is never a routed service target.
- `akorin/__init__.py` logs "Invalid Oremi Isinmi configuration:" — a copy-paste artifact
  referring to the wrong project.
- `make coverage` passes `--cov=server` and `pytest-cov` is not a dependency: the target is
  stale.
- `tox.ini` (flake8/pycodestyle/pydocstyle) and `.pylintrc` exist but no configured command
  (Makefile, pre-commit, CI) invokes tox/flake8/pylint. Treat them as legacy reference.
- `build/context` is an empty, git-ignored file.
- `sounddevice` is a dev dependency with no imports in the codebase.

## Rules for AI Coding Agents

1. **Read before you write.** Read the module you are changing and its direct callers.
   Use the existing code as the specification.
2. **Search before you create.** Before adding a helper, exception, setting, agent, tool,
   or cache, grep for an existing one (`akorin/utils/`, `core/`) and reuse or extend it.
3. **Make the smallest coherent change.** No drive-by refactors, renames, formatting
   sweeps, or dependency upgrades in an unrelated task.
4. **Do not redesign the architecture.** Preserve the layer boundaries, the router chain
   order, the `AgentClient` funnel, the MCP abstraction, and the `app.state` DI pattern.
5. **Do not introduce dependencies** without a concrete, stated need; if you must, update
   `pyproject.toml` and `uv.lock`.
6. **Do not change public APIs** (`ProcessRequest`/`ProcessResponse`, route decision
   models, HTTP paths, settings names) unless the task explicitly requires it. Preserve
   backward compatibility: message alias `text`, HTTP 200 + `ok` semantics, language echo.
7. **Preserve behavior unrelated to the task.** If you spot a bug outside scope, note it;
   do not fold an unrelated fix into the change.
8. **Never hardcode secrets** or commit local `.env` files; use `OREMI_AKORIN_*` variables and
   `safe_url` for logs.
9. **Keep the LLM integration centralized.** New agents go through `AgentClient`;
   do not bypass caching, model settings, or the tool loop.
10. **Update tests and docs with behavior.** Add/adjust tests; update `.env.example` and
    `DOCUMENTATION.md` when settings or the public contract change.
11. **Never fabricate conventions.** If this document does not cover a case, follow the
    closest existing pattern in the codebase and say so.
12. **Do not modify** generated files, `uv.lock` by hand, vendor caches, or unreleased
    version metadata as a side effect.

## Definition of Done

A task is complete only when all of the following hold:

- [ ] The change is scoped to the request; no unrelated refactoring or reformatting.
- [ ] Existing patterns and layer boundaries are preserved (see Architecture).
- [ ] New behavior is covered by tests, and the full suite passes:
      `uv run pytest tests/ -q` (currently 52 tests, all green at the time of writing).
- [ ] `ruff check .` passes (run `make fix` if needed).
- [ ] `devbox run prek run --all-files` passes, including `mypy --strict`, `bandit`, and
      `hadolint`.
- [ ] No new dependency was added, or it is justified and `uv.lock` is updated.
- [ ] Settings/docs are updated (`.env.example`, `DOCUMENTATION.md`) if configuration or the
      public API changed.
- [ ] Public behavior unrelated to the task is unchanged; the language-preservation and
      `ok`-field response contracts remain intact.
- [ ] No secrets, generated files, or local artifacts are included in the change.
