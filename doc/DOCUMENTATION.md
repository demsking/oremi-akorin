???

## Requirements

- Python 3.12, or Docker
- An MQTT broker

## Installation

### From PyPI with pip

```bash
pip install oremi-akorin
```

### From PyPI with uv

```bash
uv tool install oremi-akorin
```

## Quick Start

### Using pip-installed package

After installation, you can run the device directly:

```bash
oremi-akorin
```

### Using Docker

The application requires a node ID and the addresses of the Ohunerin,
Andika, and MQTT services:

```bash
docker run --rm -it \
  --network host \
  demsking/oremi-akorin
```

`--network host` is used here so the container can reach services bound to the
host. Use Docker service names instead when all services share a Docker
network. PulseAudio installations may also need the PulseAudio socket and
cookie mounted into the container.

## Command Line

General syntax:

```text
oremi-akorin [-h] [-v] [options]
```

| Option            | Description                   |
| ----------------- | ----------------------------- |
| `-h`, `--help`    | Show help.                    |
| `-v`, `--version` | Show the application version. |

### Command Line Options

## Logging

Logging is configured only through environment variables:

**Environment Variables:**

- `LOG_LEVEL` – Logging severity level. One of `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`. Invalid values fall back to `INFO`. Default: `INFO`
- `LOG_FILE` – File path for log output. Must be writable by the process. Default: Standard error (stderr)

**Example:**

```bash
LOG_LEVEL=DEBUG LOG_FILE=/var/log/oremi-akorin.log oremi-akorin \
  --node-id living-room \
  --ohunerin-host localhost \
  --andika-host localhost \
  --mqtt-broker localhost
```

**Docker example:**

```bash
docker run --rm -it \
  --network host \
  --device /dev/snd:/dev/snd \
  -e LOG_LEVEL=DEBUG \
  -e LOG_FILE=/var/log/oremi-akorin.log \
  -v /var/log:/var/log \
  demsking/oremi-akorin \
  --node-id living-room \
  --ohunerin-host 127.0.0.1 \
  --andika-host 127.0.0.1 \
  --mqtt-broker 127.0.0.1
```

**Notes:**

- Setting `LOG_LEVEL=DEBUG` provides verbose output useful for troubleshooting
- When using Docker, ensure the log directory is mounted with `-v` to persist logs outside the container
- If `LOG_FILE` points to a directory that doesn't exist, the process will fail to start

## Development

Oremi Akọrin is built with Python and uses `uv` for dependency management. The project follows standard Python development practices with type hints, linting, and automated testing.

For detailed information on setting up your development environment, running tests, code style guidelines, and the pull request process, please refer to [CONTRIBUTING.md](https://gitlab.com/demsking/oremi-akorin/-/blob/main/CONTRIBUTING.md).

## Versioning

This project adheres to [Semantic Versioning](https://semver.org/) (SemVer). Version numbers follow the `MAJOR.MINOR.PATCH` format:

- **MAJOR** version increments for incompatible API changes
- **MINOR** version increments for backward-compatible new functionality
- **PATCH** version increments for backward-compatible bug fixes

The current version can be found in `pyproject.toml` or by running:

```bash
oremi-akorin --version
```

Pre-release versions (alpha, beta, release candidates) may be published to PyPI for testing purposes and are clearly marked with version suffixes.

## License

Copyright 2026 Sébastien Demanou. All Rights Reserved.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    https://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
