## Oremi Akọrin

Oremi Akọrin is the natural-language gateway for the Oremi ecosystem.
It accepts user requests over HTTP or MQTT, uses a large language model (LLM)
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
- Zigbee device control through MQTT and Zigbee2MQTT;
- stable knowledge from Wikipedia and current information from DuckDuckGo;
- native date/time, calculator, and unit-conversion tools.

## Deployment

Oremi Akọrin is distributed as a multi-platform Docker image for
`linux/amd64` and `linux/arm64`. It can be deployed as a standalone service or
integrated into the Oremi ecosystem alongside services such as Oremi Isinmi,
Weather, Rediyo, and Kansa.

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
    restart: always
    depends_on:
      - mosquitto
      - ollama
      - isinmi
      - weather
      - rediyo
      - kansa
    ports:
      - 5020:5020
    environment:
      OREMI_AKORIN_SERVER_HOST: 0.0.0.0
      OREMI_AKORIN_OLLAMA_BASE_URL: http://ollama:11434
      OREMI_AKORIN_ISINMI_URL: http://isinmi:7337
      OREMI_AKORIN_WEATHER_URL: http://weather:1777
      OREMI_AKORIN_REDIYO_URL: http://rediyo:9170
      OREMI_AKORIN_KANSA_URL: http://kansa:4940
      OREMI_AKORIN_MQTT_BROKER: mosquitto
    env_file:
      - .env
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:5020/health/"]
      interval: 30s
      timeout: 10s
      retries: 3

  mosquitto:
    image: eclipse-mosquitto:2.0.18
    restart: always
    volumes:
      - ./config/mosquitto.conf:/mosquitto/config/mosquitto.conf

  ollama:
    image: ollama/ollama
    restart: always
    runtime: nvidia
    volumes:
      - ~/.ollama:/root/.ollama
    environment:
      CUDA_VISIBLE_DEVICES: 0

  isinmi:
    image: demsking/oremi-isinmi-agent
    restart: always
    depends_on:
      - ollama
    volumes:
      - ~/.config/oremi-isinmi-agent:/oremi/data
    environment:
      OREMI_ISINMI_OLLAMA_BASE_URL: http://ollama:11434
      OREMI_ISINMI_DATABASE_ENCRYPTION_KEY: ${OREMI_ISINMI_DATABASE_ENCRYPTION_KEY?Missing required environment variable}
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:7337/health/"]
      interval: 30s
      timeout: 10s
      retries: 3

  weather:
    image: demsking/oremi-weather-agent
    restart: always
    depends_on:
      - ollama
    environment:
      OLLAMA_BASEURL: http://ollama:11434

  rediyo:
    image: demsking/oremi-rediyo-agent
    restart: always
    depends_on:
      - ollama
    volumes:
      - ~/.config/oremi-rediyo-agent:/var/cache/oremi-rediyo-agent
    environment:
      OLLAMA_BASEURL: http://ollama:11434

  kansa:
    image: demsking/oremi-kansa-agent
    restart: always
    depends_on:
      - ollama
    volumes:
      - ~/.config/oremi-kansa-agent:/var/cache/oremi-kansa-agent
    environment:
      OLLAMA_BASEURL: http://ollama:11434
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

- `OREMI_AKORIN_SERVER_HOST`: Optional. Defaults to `127.0.0.1`. Host interface
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
- `OREMI_AKORIN_MAX_RESPONSE_TOKENS`: Optional. Defaults to `500`. Maximum
  number of tokens generated by the LLM. Valid range: `11` to `4096`.

### Oremi Service Settings

These services are optional. If omitted, the corresponding capability is
disabled.

- `OREMI_AKORIN_ISINMI_URL`: Base URL of the Oremi Isinmi scheduling service.
- `OREMI_AKORIN_WEATHER_URL`: Base URL of the weather service used for
  forecasts, air quality, pollen, and alert requests.
- `OREMI_AKORIN_REDIYO_URL`: Base URL of the Oremi Rediyo radio service.
- `OREMI_AKORIN_KANSA_URL`: Base URL of the Oremi Kansa podcast service.

### HTTP Client Settings

- `OREMI_AKORIN_REQUEST_TIMEOUT`: Optional. Defaults to `30.0`. Global timeout
  in seconds for HTTP requests sent to external services.

### Search Settings

- `OREMI_AKORIN_SEARCH_ENABLED`: Optional. Defaults to `true`. Enables
  DuckDuckGo search as a fallback for queries requiring current information.
- `OREMI_AKORIN_SEARCH_TIMEOUT`: Optional. Defaults to `10.0`. Timeout in
  seconds for search requests.

### MQTT Settings

MQTT integration is optional. If `OREMI_AKORIN_MQTT_BROKER` is not configured,
MQTT support is disabled.

- `OREMI_AKORIN_MQTT_BROKER`: Hostname or IP address of the MQTT broker.
- `OREMI_AKORIN_MQTT_PORT`: Optional. Defaults to `1883`. MQTT broker port.
  Valid range: `1` to `65535`.
- `OREMI_AKORIN_MQTT_CLIENT_ID`: Optional. MQTT client identifier. When omitted,
  one is generated automatically.
- `OREMI_AKORIN_MQTT_USERNAME`: Optional. Username for MQTT authentication.
- `OREMI_AKORIN_MQTT_PASSWORD`: Optional. Password for MQTT authentication.
- `OREMI_AKORIN_MQTT_KEEPALIVE`: Optional. Defaults to `60`. MQTT keepalive
  interval in seconds. Minimum value: `10`.
- `OREMI_AKORIN_MQTT_TLS_ENABLED`: Optional. Defaults to `false`. Enables TLS
  for the MQTT connection.
- `OREMI_AKORIN_MQTT_TLS_CA_CERT`: Optional. Path to the CA certificate used to
  verify the MQTT broker when TLS is enabled.
- `OREMI_AKORIN_OREMI_DEVICE_MQTT_TOPIC`: Optional. Defaults to
  `oremi/device`. Base MQTT topic used by Oremi Device nodes.

### Logging Settings

- `OREMI_AKORIN_LOG_LEVEL`: Optional. Defaults to `INFO`. Logging level:
  `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`.
- `OREMI_AKORIN_LOG_FILE`: Optional. Defaults to `oremi_akorin.log`. Path to
  the rotating application log file.

### Example

```env
OREMI_AKORIN_SERVER_HOST=127.0.0.1
OREMI_AKORIN_SERVER_PORT=5020
OREMI_AKORIN_API_PREFIX=/
OREMI_AKORIN_LLM_MODEL=ollama:qwen3.5:2b
OREMI_AKORIN_OLLAMA_BASE_URL=http://ollama:11434
OREMI_AKORIN_ISINMI_URL=http://oremi-isinmi:7337
OREMI_AKORIN_WEATHER_URL=http://oremi-weather:5010
OREMI_AKORIN_REDIYO_URL=http://oremi-rediyo:5030
OREMI_AKORIN_KANSA_URL=http://oremi-kansa:5040
OREMI_AKORIN_MQTT_BROKER=test.mosquitto.org
OREMI_AKORIN_LOG_LEVEL=INFO
```

## Oremi Service Dependencies

Oremi Akọrin can operate as a standalone conversational assistant, but its
capabilities expand significantly when connected to other Oremi services.

- **Oremi Akọrin** – Alarm, timer, reminder, and calendar management.
  Handles scheduling requests and other time-based personal assistant tasks.
  Documentation: https://demsking.gitlab.io/oremi-isinmi-agent

- **Oremi Weather Agent** – Weather forecasts, current conditions, air quality,
  pollen information, geocoding, and weather alerts.
  Documentation: https://demsking.gitlab.io/oremi-weather-agent

- **Oremi Rediyo Agent** – Natural-language access to internet radio stations,
  allowing users to search for and play radio streams.
  Documentation: https://demsking.gitlab.io/oremi-rediyo-agent

- **Oremi Kansa Agent** – Natural-language search and discovery of podcasts,
  including podcast metadata and episode information.
  Documentation: https://demsking.gitlab.io/oremi-kansa-agent

- **MQTT Broker** – Optional. Enables communication with Oremi Device nodes,
  allowing Akọrin to publish commands and receive events from microphones,
  speakers, and other MQTT-enabled devices.

## Routing and Services

Akọrin spell-checks the request in its original language, selects a service
using deterministic rules and the configured Pydantic AI model, then dispatches
the original-language request directly. It does not translate French input to
English before processing.

| Service value | Capability                                      | Availability                          |
| ------------- | ----------------------------------------------- | ------------------------------------- |
| `chat`        | General conversation                            | Configured Pydantic AI model          |
| `tool`        | Live date/time, arithmetic, and unit conversion | Built in; invoked through Pydantic AI |
| `wikipedia`   | Stable encyclopedic knowledge                   | Built in                              |
| `search`      | Current facts and explicit web searches         | Built in when search is enabled       |
| `isinmi`      | Scheduling and reminders                        | Requires `OREMI_AKORIN_ISINMI_URL`    |
| `weather`     | Forecasts, air quality, pollen, and alerts      | Requires `OREMI_AKORIN_WEATHER_URL`   |
| `rediyo`      | Radio                                           | Requires `OREMI_AKORIN_REDIYO_URL`    |
| `kansa`       | Podcasts                                        | Requires `OREMI_AKORIN_KANSA_URL`     |
| `zigbee`      | Smart-device control                            | Requires MQTT and Zigbee2MQTT         |

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

When MQTT is enabled, Akọrin subscribes to final transcriptions from every
Oremi Device node:

```bash
mosquitto_pub -h localhost \
  -t oremi/device/nodes/living-room/transcription/result \
  -m '{"text":"Weather in Lagos"}'
```

Subscribe for that node's processing results:

```bash
mosquitto_sub -h localhost -t 'oremi/device/nodes/living-room/processing/result'
```

The response is a non-retained QoS 1 object with a `message` field, ready for
Oremi Device to speak. Akọrin selects and validates ordered device commands from
media and scheduling service results. Direct playback, volume, mute, and voice
requests are also resolved locally without conversational processing. The node
ID is preserved from the transcription topic.

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
especially when MQTT or smart-device control is enabled.

## Troubleshooting

### Configuration error at startup

When using an `ollama:` model, confirm that `OREMI_AKORIN_OLLAMA_BASE_URL`
is set and includes `http://` or `https://`. Component settings must be base
URLs, for example `http://weather:31777`, without `/api` paths.

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

### MQTT or Zigbee is unavailable

Set `OREMI_AKORIN_MQTT_BROKER` to a broker hostname rather than an HTTP URL.
Check broker credentials, TLS settings, and the `mqtt` field from `/health`.
Zigbee device discovery additionally requires Zigbee2MQTT to publish its bridge
device list.

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
