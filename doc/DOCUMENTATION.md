Oremi Akọrin is the bilingual natural-language gateway for the Oremi
ecosystem. It accepts English and French requests over HTTP or MQTT, uses
Ollama to normalize and classify them, and dispatches them to the appropriate
service.

Supported capabilities include:

- conversational responses through Ollama;
- schedules, reminders, timers, and alarms through Isinmi;
- weather forecasts, air quality, pollen, and alerts;
- radio and podcast discovery through Rediyo and Kansa;
- Zigbee device control through MQTT and Zigbee2MQTT;
- stable knowledge from Wikipedia and current information from DuckDuckGo;
- native date/time, calculator, and unit-conversion tools.

## Requirements

- Python 3.12, or Docker;
- a reachable Ollama server;
- an Ollama model with tool-calling support, by default `qwen2.5:3b`.

The Oremi component services and MQTT are optional. Without them, Akọrin can
still provide chat, Wikipedia, search, and native tools. MQTT is required only
for MQTT requests and Zigbee control.

## Installation

### PyPI with uv

```bash
uv tool install oremi-akorin
```

### PyPI with pip

```bash
python -m pip install oremi-akorin
```

## Quick Start

Start Ollama and make the default model available:

```bash
ollama serve
ollama pull qwen2.5:3b
```

In another terminal, configure the required Ollama URL and start Akọrin:

```bash
export OLLAMA_HOST=http://localhost:11434
oremi-akorin
```

For a repository checkout, use:

```bash
OLLAMA_HOST=http://localhost:11434 uv run oremi-akorin
```

The server listens on `http://localhost:5020` by default. Open
`http://localhost:5020/docs` for the interactive Scalar API reference.

Send a request:

```bash
curl --request POST http://localhost:5020/api/process \
  --header 'content-type: application/json' \
  --data '{"text":"Quelle heure est-il ?","language":"fr","context":{"timezone":"Europe/Paris"}}'
```

Check service health:

```bash
curl http://localhost:5020/health
oremi-akorin status
```

The `status` command queries `/health` on `localhost` using the configured
`SERVER_PORT`.

## Configuration

Configuration is loaded from environment variables and from a `.env` file in
the current working directory. Environment variable names are
case-insensitive. `OLLAMA_HOST` is the only required setting.

Minimal `.env` file:

```dotenv
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=qwen2.5:3b
SERVER_HOST=localhost
SERVER_PORT=5020
```

### Server and Ollama

| Variable                 | Required | Default      | Description                                                      |
| ------------------------ | -------- | ------------ | ---------------------------------------------------------------- |
| `SERVER_HOST`            | No       | `localhost`  | Server bind address. Use `0.0.0.0` to accept remote connections. |
| `SERVER_PORT`            | No       | `5020`       | Server port, from 1 to 65535.                                    |
| `API_ROOT_PATH`          | No       | `/`          | Public root path when Akọrin runs behind a reverse proxy.        |
| `OLLAMA_HOST`            | Yes      | None         | Ollama base URL including scheme and port.                       |
| `OLLAMA_MODEL`           | No       | `qwen2.5:3b` | Model used for normalization, routing, chat, and tools.          |
| `OLLAMA_PULL_MODEL`      | No       | `true`       | Pull the configured model at startup when it is missing.         |
| `OLLAMA_REQUEST_TIMEOUT` | No       | `60.0`       | Ollama request timeout in seconds.                               |

### Oremi components

All component URLs are optional base URLs. They must not contain a path,
query, or fragment.

| Variable      | Service | Purpose                                     |
| ------------- | ------- | ------------------------------------------- |
| `ISINMI_URL`  | Isinmi  | Schedules, reminders, alarms, and timers.   |
| `WEATHER_URL` | Weather | Forecasts, air quality, pollen, and alerts. |
| `REDIYO_URL`  | Rediyo  | Radio station discovery.                    |
| `KANSA_URL`   | Kansa   | Podcast and episode discovery.              |

Example:

```dotenv
ISINMI_URL=http://localhost:37337
WEATHER_URL=http://localhost:31777
REDIYO_URL=http://localhost:39170
KANSA_URL=http://localhost:34940
```

At startup, Akọrin calls `/api/server` on every configured component. A
configured component must return JSON containing non-empty `name` and
`version` fields. Startup fails when a configured component is unreachable or
returns an invalid response.

### Requests, search, and generation

| Variable              | Default | Description                                               |
| --------------------- | ------- | --------------------------------------------------------- |
| `REQUEST_TIMEOUT`     | `30.0`  | HTTP timeout for external services, in seconds.           |
| `MAX_RESPONSE_TOKENS` | `500`   | Maximum configured LLM response size, from 11 to 4096.    |
| `LLM_TEMPERATURE`     | `0.7`   | Configured generation temperature, from 0 to 1.           |
| `SEARCH_ENABLED`      | `true`  | Enable DuckDuckGo search and Wikipedia's search fallback. |
| `SEARCH_TIMEOUT`      | `10.0`  | DuckDuckGo request timeout, in seconds.                   |

### MQTT

MQTT is disabled when `MQTT_BROKER` is unset.

| Variable              | Default                 | Description                                                                |
| --------------------- | ----------------------- | -------------------------------------------------------------------------- |
| `MQTT_BROKER`         | None                    | Broker hostname or IP address. A URL-style scheme is accepted and removed. |
| `MQTT_PORT`           | `1883`                  | Broker port.                                                               |
| `MQTT_CLIENT_ID`      | Generated               | MQTT client identifier.                                                    |
| `MQTT_USERNAME`       | None                    | Optional broker username.                                                  |
| `MQTT_PASSWORD`       | None                    | Optional broker password.                                                  |
| `MQTT_REQUEST_TOPIC`  | `oremi/akorin/request`  | Incoming NLP requests.                                                     |
| `MQTT_RESPONSE_TOPIC` | `oremi/akorin/response` | Processed JSON responses.                                                  |
| `MQTT_STATE_TOPIC`    | `oremi/akorin/state`    | Retained `online`, `processing`, or `offline` state.                       |
| `MQTT_KEEPALIVE`      | `60`                    | Keepalive in seconds; minimum 10.                                          |
| `MQTT_TLS_ENABLED`    | `false`                 | Enable TLS for the broker connection.                                      |
| `MQTT_TLS_CA_CERT`    | System default          | Optional path to a CA certificate file.                                    |

### Logging

| Variable    | Default        | Description                                                            |
| ----------- | -------------- | ---------------------------------------------------------------------- |
| `LOG_LEVEL` | `INFO`         | `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`.                    |
| `LOG_FILE`  | Standard error | Optional output file. Its parent directory must exist and be writable. |

`DEBUG` includes routing decisions, request durations, component calls, and
tool names. Request tag values are not written to routing logs, but input and
output text are logged at this level; use it carefully with private data.

## Command Line

```text
oremi-akorin [-h] [-v] [status]
```

| Command or option | Description                                                  |
| ----------------- | ------------------------------------------------------------ |
| no command        | Start the HTTP server using `SERVER_HOST` and `SERVER_PORT`. |
| `status`          | Query the running server's health endpoint.                  |
| `-h`, `--help`    | Show command help.                                           |
| `-v`, `--version` | Show the installed version.                                  |

Server options are configured through environment variables rather than CLI
flags.

## Routing and Services

Akọrin spell-checks the request, translates French input to English for
routing, selects a service using deterministic rules and Ollama, then
translates the response back to the original language.

| Service value    | Capability                                      | Availability                     |
| ---------------- | ----------------------------------------------- | -------------------------------- |
| `chat`           | General conversation                            | Ollama                           |
| `tool`           | Live date/time, arithmetic, and unit conversion | Built in; invoked through Ollama |
| `wikipedia`      | Stable encyclopedic knowledge                   | Built in                         |
| `search`         | Current facts and explicit web searches         | Built in when search is enabled  |
| `isinmi`         | Scheduling and reminders                        | Requires `ISINMI_URL`            |
| `weather`        | Forecasts, air quality, and pollen              | Requires `WEATHER_URL`           |
| `weather_alerts` | Weather, air-quality, and pollen alerts         | Requires `WEATHER_URL`           |
| `rediyo`         | Radio                                           | Requires `REDIYO_URL`            |
| `kansa`          | Podcasts                                        | Requires `KANSA_URL`             |
| `zigbee`         | Smart-device control                            | Requires MQTT and Zigbee2MQTT    |

Wikipedia results are synthesized into a short grounded answer. When no
Wikipedia article matches, Akọrin falls back to DuckDuckGo if search is
enabled.

### Native tools

The chat model can call these built-in tools:

- `get_current_datetime`: current date and time in an IANA timezone;
- `calculate`: guarded arithmetic with parentheses, `+`, `-`, `*`, `/`, `//`,
  `%`, `**`, `pi`, `e`, and `tau`;
- `convert_units`: common length, mass, temperature, volume, and speed units.

Examples include "What is `(18 * 4) + 7`?", "Convert 5 kilometers to miles",
and "What time is it in Lagos?".

## MQTT API

When MQTT is enabled, publish the same object accepted by `POST /api/process`
to `MQTT_REQUEST_TOPIC`:

```bash
mosquitto_pub -h localhost \
  -t oremi/akorin/request \
  -m '{"text":"Weather in Lagos","language":"en","context":{"timezone":"Africa/Lagos"}}'
```

A JSON string is accepted as shorthand:

```bash
mosquitto_pub -h localhost -t oremi/akorin/request -m '"What time is it?"'
```

Subscribe for results and state changes:

```bash
mosquitto_sub -h localhost -t 'oremi/akorin/response' -t 'oremi/akorin/state'
```

Responses use the same JSON structure as the HTTP endpoint. Invalid MQTT
requests return an object with `ok: false` and a `message` field.

## Zigbee2MQTT

When MQTT connects, Akọrin subscribes to
`zigbee2mqtt/bridge/devices`, discovers non-coordinator devices, and resolves
commands against their friendly names. Commands are published to
`zigbee2mqtt/<friendly-name>/set`.

Natural-language command:

```json
{
  "text": "Turn off the bedroom lamp"
}
```

Explicit command context:

```json
{
  "text": "Set the device state",
  "context": {
    "device": "bedroom_lamp",
    "state": "OFF"
  }
}
```

`state` may also be an object supported by the target Zigbee2MQTT device, for
example `{"state":"ON","brightness":128}`.

## Docker

Build the image:

```bash
docker build --tag oremi-akorin .
```

Run it with Ollama on the host:

```bash
docker run --rm \
  --publish 5020:5020 \
  --env OLLAMA_HOST=http://host.docker.internal:11434 \
  oremi-akorin
```

On Linux, add `--add-host host.docker.internal:host-gateway`, use host
networking, or use an address reachable from the container. When services run
on a shared Docker network, use their container names in `OLLAMA_HOST` and the
component URLs.

Do not use `localhost` in a container URL to refer to a service running in a
different container or on the host.

## Reverse Proxy

Set `API_ROOT_PATH` when a proxy exposes Akọrin below a path prefix:

```dotenv
API_ROOT_PATH=/akorin
```

Forward the usual proxy headers. The server trusts proxy headers, so only
deploy it behind a trusted proxy and network boundary.

Akọrin does not provide application-level authentication. Protect remote
deployments with the proxy, firewall rules, or another authentication layer,
especially when MQTT or smart-device control is enabled.

## Troubleshooting

### Configuration error at startup

Confirm that `OLLAMA_HOST` includes `http://` or `https://`. Component settings
must be base URLs, for example `http://weather:31777`, without `/api` paths.

### A configured component prevents startup

Akọrin intentionally verifies every configured component. Check its
`/api/server` endpoint, or remove the corresponding URL when the integration
is not needed.

### Ollama responds but tools are not called

Confirm that the selected model supports Ollama tool calling. The default
`qwen2.5:3b` is the expected model. Also verify that the model is installed:

```bash
ollama list
```

### MQTT or Zigbee is unavailable

Set `MQTT_BROKER` to a broker hostname rather than an HTTP URL. Check broker
credentials, TLS settings, and the `mqtt` field from `/health`. Zigbee device
discovery additionally requires Zigbee2MQTT to publish its bridge device list.

### More diagnostic output

```bash
LOG_LEVEL=DEBUG oremi-akorin
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
