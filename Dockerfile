#
## Stage 1: Builder
FROM python:3.12-alpine3.21 AS builder

ENV UV_LINK_MODE=copy

# Set the shell to /bin/ash and enable pipefail
SHELL ["/bin/ash", "-eo", "pipefail", "-c"]

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Change the working directory
WORKDIR /app

# Install dependencies
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --no-dev --locked --no-install-project --compile-bytecode

#
## Stage 2: Final
FROM python:3.12-alpine3.21

# Set the shell to /bin/ash and enable pipefail
SHELL ["/bin/ash", "-eo", "pipefail", "-c"]

RUN apk add --no-cache curl
RUN adduser -D -h /oremi oremi && mkdir -p /oremi/data

WORKDIR /oremi

COPY --from=builder /app/.venv /oremi/.venv
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages

COPY --chown=oremi:oremi DOCUMENTATION.md pyproject.toml LICENSE ./
COPY --chown=oremi:oremi htdocs/ ./htdocs/
COPY --chown=oremi:oremi akorin/ ./akorin/

ENV PATH="/oremi/.venv/bin:$PATH"
ENV PYTHONPATH="/oremi:/oremi/.venv/lib/python3.12/site-packages"
ENV PYTHONUNBUFFERED="1"

ENV OREMI_AKORIN_LOG_LEVEL="INFO"
ENV OREMI_AKORIN_SERVER_HOST="0.0.0.0"

VOLUME /oremi/data

EXPOSE 5020

HEALTHCHECK --interval=30s --timeout=10s --retries=3 CMD curl -f http://localhost:5020/health/ || exit 1

CMD ["python", "/oremi/akorin"]
