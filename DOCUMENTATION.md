## Oremi Akọrin

Oremi Akọrin is the natural-language gateway for the Oremi ecosystem.
It accepts user requests over HTTP, uses a large language model (LLM)
to understand, normalize, and classify them, then intelligently routes each
request to the appropriate Oremi service. Whether the request concerns weather,
reminders, podcasts, radio, smart-home devices, or general conversation,
Akọrin preserves the user's original language and returns a natural response
while coordinating the underlying services on their behalf.

The name **Akọrin** comes from the Yoruba language and means **"singer"** or
**"one who sings."** In the Oremi ecosystem, the name symbolizes a component that
gives voice to user intent. Rather than performing every task itself, Akọrin
listens, interprets, and orchestrates communication between specialized services,
acting as the expressive voice and natural-language entry point of the platform.

Project repository: https://gitlab.com/demsking/oremi-akorin

![Oremi Akọrin Logo](./static/logo.png)

## Core Capabilities

- conversational responses through the configured LLM model;
- schedules, reminders, timers, and alarms through Isinmi;
- weather forecasts, air quality, pollen, and alerts through the weather service;
- radio and podcast discovery through Rediyo and Kansa;
- Zigbee device control through Isakoso;
- native date/time, calculator, and unit-conversion tools.

## Deployment

Oremi Akọrin is distributed as a multi-platform Docker image for
`linux/amd64` and `linux/arm64`. It can be deployed as a standalone service or
integrated into the Oremi ecosystem alongside services such as Oremi Isinmi,
Oremi Ojọ, Oremi Rediyo, and Oremi Kansa.

The following sections describe the available Docker image, persistent storage
requirements, and example deployments using both Docker and Docker Compose.

### Command Line

Before installing Oremi Akọrin from PyPI, ensure the following requirements are
met:

- Python 3.12 or later.
- `uv` (recommended) or `pip` for package installation.

Oremi Akọrin can be installed either as a standalone command-line application
or as a Python package.

#### Install with uv

```sh
uv tool install oremi-akorin
```

#### Install with pip

```sh
python -m pip install oremi-akorin
```

#### Usage

```text
oremi-akorin [-h] [-v]
```

When started without arguments, Oremi Akọrin launches the HTTP server using the
configured environment variables.

#### Options

- `-h`, `--help`: Display the command-line help and exit.
- `-v`, `--version`: Display the installed version and exit.

All server configuration, including the listening address, port, LLM backend,
and service endpoints, is provided through environment variables rather than
command-line options.

### Docker Image

The [`demsking/oremi-akorin`](https://hub.docker.com/r/demsking/oremi-akorin)
Docker image is officially available on Docker Hub, supporting both
`linux/amd64` and `linux/arm64` platforms. The image exposes port `5020`, which
serves the REST API and the interactive documentation.

The interactive documentation can be accessed at `http://localhost:5020/docs`
and allows testing available endpoints directly from the browser.

### Volumes

Oremi Akọrin is largely stateless and does not require persistent storage for
normal operation.

The Docker image does not define any persistent volumes. If you configure file
logging by setting `OREMI_AKORIN_LOG_FILE` to a location inside the container,
mount a host directory to preserve log files across container recreation.

### Deploy with Docker

Use the official Docker image
[`demsking/oremi-akorin`](https://hub.docker.com/r/demsking/oremi-akorin)
to run Oremi Akọrin:

```sh
docker run -d \
  --name oremi-akorin \
  --env-file <path_to_env_file> \
  -p 5020:5020 \
  demsking/oremi-akorin
```

Replace `<path_to_env_file>` with the path to your
[environment variables](#environment-variables) file containing the desired
configuration.

### Deploy with Docker Compose

Create a `compose.yaml` file:

```yaml
services:
  akorin:
    image: demsking/oremi-akorin
    restart: unless-stopped
    depends_on:
      - ollama
      - isakoso
      - isinmi
      - ojo
      - rediyo
      - kansa
    ports:
      - 5020:5020
    environment:
      OREMI_AKORIN_OLLAMA_BASE_URL: http://ollama:11434
      OREMI_AKORIN_ISAKOSO_URL: http://isakoso:5089/mcp/
      OREMI_AKORIN_ISINMI_URL: http://isinmi:5073/mcp/
      OREMI_AKORIN_OJO_URL: http://ojo:5040/mcp/
      OREMI_AKORIN_REDIYO_URL: http://rediyo:5076/mcp/
      OREMI_AKORIN_KANSA_URL: http://kansa:5046/mcp/

  isakoso:
    image: demsking/oremi-isakoso
    restart: unless-stopped
    depends_on:
      - mosquitto
    environment:
      OREMI_ISAKOSO_MQTT_BROKER: mosquitto

  isinmi:
    image: demsking/oremi-isinmi
    restart: unless-stopped
    environment:
      OREMI_ISINMI_DATABASE_ENCRYPTION_KEY: ${OREMI_ISINMI_DATABASE_ENCRYPTION_KEY?Missing required environment variable}
    volumes:
      - oremi-isinmi-data:/oremi/data

  ojo:
    image: demsking/oremi-ojo
    restart: unless-stopped

  rediyo:
    image: demsking/oremi-rediyo
    restart: unless-stopped

  kansa:
    image: demsking/oremi-kansa
    restart: unless-stopped
    volumes:
      - oremi-kansa-data:/oremi/data

  mosquitto:
    image: eclipse-mosquitto:2.0.18
    restart: unless-stopped
    volumes:
      - ./config/mosquitto.conf:/mosquitto/config/mosquitto.conf

  ollama:
    image: ollama/ollama
    restart: unless-stopped
    runtime: nvidia
    volumes:
      - ollama-data:/root/.ollama
    environment:
      CUDA_VISIBLE_DEVICES: 0

volumes:
  oremi-isinmi-data:
  oremi-kansa-data:
  ollama-data:
```

Start the services with:

```sh
docker compose up -d
```

Once started, open the interactive documentation at:

```txt
http://localhost:35020/docs
```

## Configuration

When configuring **Oremi Akọrin**, several environment variables are used to
control its behavior and connect with external services. Below is a breakdown
of these variables, grouped by their purpose.

All runtime settings use the `OREMI_AKORIN_` prefix and can be provided through
the environment or a `.env` file in the working directory.

### Application and Server Settings

- `OREMI_AKORIN_SERVER_HOST`: Optional. Defaults to `0.0.0.0`. Host interface
  used by the Oremi Akọrin server.
- `OREMI_AKORIN_SERVER_PORT`: Optional. Defaults to `5020`. Port used by the
  Oremi Akọrin server. Valid range: `1` to `65535`.
- `OREMI_AKORIN_API_PREFIX`: Optional. Defaults to `/`. Prefix for all API
  routes.

### LLM Settings

- `OREMI_AKORIN_LLM_MODEL`: Optional. Defaults to `ollama:qwen3.5:2b`.
  Fully qualified Pydantic-AI model identifier. Use provider-prefixed values
  such as `ollama:qwen3.5:2b`, `openai:gpt-4.1-mini`, or
  `anthropic:claude-sonnet-4-0`.
- `OREMI_AKORIN_LLM_REQUEST_TIMEOUT`: Optional. Defaults to `15`. Timeout in
  seconds for LLM requests. Valid range: `1` to `300`.
- `OREMI_AKORIN_LLM_TEMPERATURE`: Optional. Defaults to `0.3`. Sampling
  temperature used by the configured LLM backend. Valid range: `0.0` to `2.0`.
- `OREMI_AKORIN_OLLAMA_BASE_URL`: Optional. Ollama API base URL used when
  `OREMI_AKORIN_LLM_MODEL` starts with `ollama:`. The default is `None`, and
  it must be explicitly provided for Ollama-backed runs.

**Examples for `OREMI_AKORIN_LLM_MODEL`:**

- Ollama:
  - `ollama:qwen3.5:2b`
  - Recommended for local or self-hosted deployments.
- ChatGPT / OpenAI:
  - `openai:gpt-4.1-mini`
  - Requires an OpenAI API key.
- Claude / Anthropic:
  - `anthropic:claude-sonnet-4-0`
  - Requires an Anthropic API key.

### LLM Behavior Settings

- `OREMI_AKORIN_LLM_SYSTEM_PROMPT`: Optional. Defaults to the built-in Oremi
  Akọrin system prompt, which asks the assistant to answer concisely, use
  available tools and services when helpful, avoid hidden reasoning, and stay
  in the user's language. Controls the assistant's overall behavior and
  personality.
- `OREMI_AKORIN_LLM_MAX_RESPONSE_TOKENS`: Optional. Defaults to `500`. Maximum
  number of tokens generated by the LLM. Valid range: `11` to `4096`.

### LLM Cache Settings

The LLM cache is an internal, bounded, in-memory cache. It reduces repeated
work for identical request-normalization, classification, response-generation,
and Zigbee command-selection calls. It is not persisted across restarts and
does not cache tool-backed chat responses or volatile context such as
`datetime`.

- `OREMI_AKORIN_LLM_CACHE_ENABLED`: Optional. Defaults to `true`. Enables the
  internal LLM cache.
- `OREMI_AKORIN_LLM_CACHE_MAX_ENTRIES`: Optional. Defaults to `512`. Maximum
  number of entries kept in memory. Set to `0` to disable caching.
- `OREMI_AKORIN_LLM_CACHE_TTL_SECONDS`: Optional. Defaults to `300.0`.
  Time-to-live for cacheable internal LLM calls. Valid range: `0.0` to
  `3600.0`.

### Performance Settings

- `OREMI_AKORIN_REQUEST_BUDGET_SECONDS`: Optional. Defaults to `20.0`. Soft
  end-to-end latency budget for processing one user request.
- `OREMI_AKORIN_SPELLCHECK_TIMEOUT_SECONDS`: Optional. Defaults to `4.0`.
  Maximum time spent normalizing one request before continuing with the
  original text.
- `OREMI_AKORIN_ROUTE_TIMEOUT_SECONDS`: Optional. Defaults to `4.0`. Maximum
  time spent on LLM classification before using heuristic routing.
- `OREMI_AKORIN_SKIP_SPELLCHECK_MAX_CHARS`: Optional. Defaults to `24`. Skips
  LLM spellcheck for short one-token clean commands up to this length. Set to
  `0` to disable.

### Component Resilience Settings

- `OREMI_AKORIN_COMPONENT_CACHE_TTL_SECONDS`: Optional. Defaults to `30.0`.
  Time-to-live for idempotent component GET calls. Valid range: `0.0` to
  `600.0`.
- `OREMI_AKORIN_COMPONENT_CACHE_STALE_SECONDS`: Optional. Defaults to `120.0`.
  Additional stale window for idempotent component GET calls. During this
  window Akọrin can return the previous response immediately and refresh the
  value in the background. Valid range: `0.0` to `3600.0`.
- `OREMI_AKORIN_COMPONENT_CIRCUIT_BREAKER_ENABLED`: Optional. Defaults to
  `true`. Enables fast failures for external components after repeated request
  failures.
- `OREMI_AKORIN_COMPONENT_CIRCUIT_BREAKER_FAILURES`: Optional. Defaults to `3`.
  Consecutive component request failures needed before opening the circuit
  breaker.
- `OREMI_AKORIN_COMPONENT_CIRCUIT_BREAKER_COOLDOWN_SECONDS`: Optional. Defaults
  to `30.0`. Time an opened component circuit breaker stays open before a
  retry is allowed.

### Oremi Service Settings

These services are optional. If omitted, the corresponding capability is
disabled.

- `OREMI_AKORIN_ISINMI_URL`: Base URL of the Oremi Isinmi scheduling service.
- `OREMI_AKORIN_OJO_URL`: Base URL of the weather service used for
  forecasts, air quality, pollen, and alert requests.
- `OREMI_AKORIN_REDIYO_URL`: Base URL of the Oremi Rediyo radio service.
- `OREMI_AKORIN_KANSA_URL`: Base URL of the Oremi Kansa podcast service.
- `OREMI_AKORIN_ISAKOSO_URL`: Base URL of the Oremi Isakoso smart-device control service.

### HTTP Client Settings

- `OREMI_AKORIN_HTTP_REQUEST_TIMEOUT`: Optional. Defaults to `30.0`. Global
  timeout in seconds for HTTP requests sent to external services.

### Logging Settings

- `OREMI_AKORIN_LOG_LEVEL`: Optional. Defaults to `INFO`. Logging level:
  `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`.
- `OREMI_AKORIN_LOG_FILE`: Optional. Defaults to `None`. Path to
  the rotating application log file. If omitted, logs are written to stdout.

## Oremi Service Dependencies

Oremi Akọrin can operate as a standalone conversational assistant, but its
capabilities expand significantly when connected to other Oremi services.

- **Oremi Isinmi** – Alarm, timer, reminder, and calendar management.
  Handles scheduling requests and other time-based personal assistant tasks.

  Documentation: https://demsking.gitlab.io/oremi-isinmi-agent

- **Oremi Ojọ** – Weather forecasts, current conditions, air quality,
  pollen information, geocoding, and weather alerts.

  Documentation: https://demsking.gitlab.io/oremi-ojo

- **Oremi Rediyo** – Search and access to internet radio stations,
  allowing users to search for and play radio streams.

  Documentation: https://demsking.gitlab.io/oremi-rediyo

- **Oremi Kànsà** – Search and discovery of podcasts,
  including podcast metadata and episode information.

  Documentation: https://demsking.gitlab.io/oremi-kansa

- **Oremi Isakoso** – Smart-home device integration and Zigbee network control,
  enabling managing lights, switches, and sensors.

  Documentation: https://demsking.gitlab.io/oremi-isakoso

### Native tools

The chat model can call these built-in tools:

- `get_current_datetime`: current date and time in an IANA timezone;
- `calculate`: guarded arithmetic with parentheses, `+`, `-`, `*`, `/`, `//`,
  `%`, `**`, `pi`, `e`, and `tau`;
- `convert_units`: common length, mass, temperature, volume, and speed units;
- `list_resources`: lists all available resources (such as device lists or statuses) exposed by the connected MCP servers;
- `read_resource`: reads the content of a specific resource using its URI;
- `list_prompts`: lists all available prompt templates/predefined messages from connected MCP servers;
- `get_prompt`: renders a specific prompt template by name, optionally taking input arguments.

Examples include "What is `(18 * 4) + 7`?", "Convert 5 kilometers to miles",
"What time is it in Lagos?", "List all available resources", or "Get the summarize prompt".

## Docker

Build the image:

```bash
docker build --tag oremi-akorin .
```

Run it with Ollama on the host:

```bash
docker run --rm \
  --publish 5020:5020 \
  --env OREMI_AKORIN_OLLAMA_BASE_URL=http://host.docker.internal:11434 \
  oremi-akorin
```

On Linux, add `--add-host host.docker.internal:host-gateway`, use host
networking, or use an address reachable from the container. When services run
on a shared Docker network, use their container names in
`OREMI_AKORIN_OLLAMA_BASE_URL` and the component URLs.

Do not use `localhost` in a container URL to refer to a service running in a
different container or on the host.

## Reverse Proxy

Set `OREMI_AKORIN_API_PREFIX` when a proxy exposes Akọrin below a path prefix:

```dotenv
OREMI_AKORIN_API_PREFIX=/akorin
```

Forward the usual proxy headers. The server trusts proxy headers, so only
deploy it behind a trusted proxy and network boundary.

Akọrin does not provide application-level authentication. Protect remote
deployments with the proxy, firewall rules, or another authentication layer,
especially when smart-device control is enabled.

## Troubleshooting

### Configuration error at startup

When using an `ollama:` model, confirm that `OREMI_AKORIN_OLLAMA_BASE_URL`
is set and includes `http://` or `https://`. Component settings must target the
MCP streamable HTTP endpoint, for example `http://ojo:5040/mcp`.

### A configured component prevents startup

Akọrin intentionally verifies every configured component. Check its
`/api/server` endpoint, or remove the corresponding URL when the integration
is not needed.

### Ollama responds but tools are not called

Confirm that the selected Ollama model supports tool calling. The default
`qwen3.5:2b` is the expected model. Akọrin no longer pulls models internally,
so verify that the model is installed:

```bash
ollama list
```

### More diagnostic output

```bash
OREMI_AKORIN_LOG_LEVEL=DEBUG oremi-akorin
```

Debug logs can contain request and response text. Avoid enabling them in
production unless log access and retention are appropriately controlled.

## Development

See the [contribution guide](https://gitlab.com/demsking/oremi-akorin/-/blob/main/CONTRIBUTING.md)
for development environment and contribution guidance.

## Versioning

Oremi Akọrin follows [Semantic Versioning](https://semver.org/). Display the
installed version with:

```bash
oremi-akorin --version
```

## License

Copyright 2026 Sébastien Demanou. All Rights Reserved.

Licensed under the Apache License, Version 2.0. See the
[LICENSE](https://gitlab.com/demsking/oremi-akorin/-/blob/main/LICENSE) for the
complete license text.
