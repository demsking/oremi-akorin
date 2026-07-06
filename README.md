# Oremi Akọrin

[![Buy me a beer](https://img.shields.io/badge/Buy%20me-a%20beer-1f425f.svg)](https://www.buymeacoffee.com/demsking)

Oremi Akọrin is the natural-language gateway for the Oremi ecosystem.
It accepts requests over HTTP or MQTT, uses LLM to normalize and classify them,
and dispatches each request to the appropriate service in the user's original
language.

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

,## Versioning

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
