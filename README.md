# Oremi Akọrin

[![Buy me a beer](https://img.shields.io/badge/Buy%20me-a%20beer-1f425f.svg)](https://www.buymeacoffee.com/demsking)

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

![Oremi Akọrin Logo](https://gitlab.com/demsking/oremi-akorin/-/raw/main/htdocs/logo.png)

## Documentation

All project documentation—including architecture details, configuration reference, and the Home Assistant integration guide—can be found at:
https://demsking.gitlab.io/oremi-akorin/

## Development

Oremi Device is built with Python and uses `uv` for dependency management. The
project follows standard Python development practices with type hints, linting,
and automated testing.

For detailed information on setting up your development environment, running
tests, code style guidelines, and the pull request process, please refer to
[CONTRIBUTING.md](https://gitlab.com/demsking/oremi-akorin/-/blob/main/CONTRIBUTING.md).

## Versioning

This project adheres to [Semantic Versioning](https://semver.org/) (SemVer).
Version numbers follow the `MAJOR.MINOR.PATCH` format:

- **MAJOR** version increments for incompatible API changes
- **MINOR** version increments for backward-compatible new functionality
- **PATCH** version increments for backward-compatible bug fixes

## License

Copyright 2026 Sébastien Demanou. All Rights Reserved.

Licensed under the Apache License, Version 2.0. See the
[LICENSE](https://gitlab.com/demsking/oremi-akorin/-/blob/main/LICENSE) for the
complete license text.
