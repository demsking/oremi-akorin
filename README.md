# Oremi Akọrin

[![Buy me a beer](https://img.shields.io/badge/Buy%20me-a%20beer-1f425f.svg)](https://www.buymeacoffee.com/demsking)

Oremi Akọrin is the bilingual NLP gateway for the Oremi ecosystem. It uses
Ollama and `qwen2.5:3b` to route French and English requests to scheduling,
weather, radio, podcast, Zigbee, web-search, or conversational services.

## Documentation

All project documentation—including architecture details, configuration reference, and the Home Assistant integration guide—can be found at:
https://demsking.gitlab.io/oremi-akorin/

## Development

Oremi Device is built with Python and uses `uv` for dependency management. The
project follows standard Python development practices with type hints, linting,
and automated testing.

For detailed information on setting up your development environment, running
tests, code style guidelines, and the pull request process, please refer to
[CONTRIBUTING.md](CONTRIBUTING.md).

## Versioning

This project adheres to [Semantic Versioning](https://semver.org/) (SemVer).
Version numbers follow the `MAJOR.MINOR.PATCH` format:

- **MAJOR** version increments for incompatible API changes
- **MINOR** version increments for backward-compatible new functionality
- **PATCH** version increments for backward-compatible bug fixes

The current version can be found in `pyproject.toml` or by running:

```bash
oremi-akorin --version
```

Pre-release versions (alpha, beta, release candidates) may be published to PyPI for testing purposes and are clearly marked with version suffixes.

## License

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE).
