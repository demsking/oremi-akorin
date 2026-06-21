# Oremi Akọrin

Oremi Akọrin is the bilingual NLP gateway for the Oremi ecosystem. It uses
Ollama and `qwen2.5:3b` to route French and English requests to scheduling,
weather, radio, podcast, Zigbee, web-search, or conversational services.

## Run locally

Python 3.12 and a running Ollama instance are required.

```bash
uv sync
uv run oremi-akorin start --host 0.0.0.0 --port 5020
```

The OpenAPI UI is at `http://localhost:5020/docs`. On startup, the application
checks Ollama and pulls `qwen2.5:3b` when needed. Set `OLLAMA_PULL_MODEL=false`
to skip that step.

```bash
curl -X POST http://localhost:5020/api/process \
  -H 'content-type: application/json' \
  -d '{"text":"Quel temps fera-t-il demain à Paris ?"}'
curl http://localhost:5020/health
```

## Configuration

| Variable              | Default                 |
| --------------------- | ----------------------- |
| `OLLAMA_HOST`         |                         |
| `OLLAMA_MODEL`        | `qwen2.5:3b`            |
| `ISINMI_URL`          |                         |
| `WEATHER_URL`         |                         |
| `REDIYO_URL`          |                         |
| `KANSA_URL`           |                         |
| `REQUEST_TIMEOUT`     | `4.0`                   |
| `MQTT_BROKER`         | unset (MQTT disabled)   |
| `MQTT_PORT`           | `1883`                  |
| `MQTT_REQUEST_TOPIC`  | `oremi/akorin/request`  |
| `MQTT_RESPONSE_TOPIC` | `oremi/akorin/response` |
| `MQTT_STATE_TOPIC`    | `oremi/akorin/state`    |

MQTT requests accept the same JSON body as `POST /api/process`; a plain JSON
string is also accepted. Zigbee control publishes to
`zigbee2mqtt/<device>/set` and expects `context.device` plus `context.state`.

## Container

```bash
docker build -t oremi-akorin .
docker run --rm -p 5020:5020 \
  -e OLLAMA_HOST=http://host.docker.internal:11434 oremi-akorin
```

The runtime image is based on Python 3.12 Alpine. Override component URLs with
container-network hostnames when running under Compose.

## Development

```bash
uv run pytest
uv run ruff check .
```

Licensed under Apache-2.0. See [LICENSE](LICENSE).
