#
## Stage 1: Build environment
FROM python:3.12-alpine AS install-dependencies-stage

# Copy the uv binary
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy and install Python dependencies
WORKDIR /src
COPY uv.lock pyproject.toml ./
RUN uv pip install --system --no-cache -r pyproject.toml


#
## Stage 2: Runtime environment
FROM python:3.12-alpine

# Copy built Python dependencies from the install-dependencies-stage stage
COPY --from=install-dependencies-stage /usr/local/lib/python3.12/site-packages/ /usr/local/lib/python3.12/site-packages/
COPY --from=install-dependencies-stage /usr/local/bin/ /usr/local/bin/

# Binaries
COPY bin/* /opt/oremi/bin/
RUN chmod +x /opt/oremi/bin/*

# Copy application files
COPY pyproject.toml LICENSE /opt/oremi/
COPY oremi_akorin/ /opt/oremi/oremi_akorin

# Set environment variables
ENV PATH="/opt/oremi/bin:$PATH"
ENV PYTHONPATH="/opt/oremi"
ENV PYTHONUNBUFFERED="1"

ENV LOG_LEVEL="INFO"
ENV SERVER_HOST="0.0.0.0"

EXPOSE 5020

WORKDIR /opt/oremi
ENTRYPOINT ["/opt/oremi/bin/entrypoint.sh"]
