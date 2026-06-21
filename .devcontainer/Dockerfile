FROM python:3.12-slim

# Copy the uv binary
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set the shell to /bin/bash and enable pipefail
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

# Install dependencies
RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    git \
    curl \
    make \
  && rm -rf /var/lib/apt/lists/*

# Create a non-root user without a password
RUN useradd --create-home --shell /bin/bash devuser \
  && chown -R devuser:devuser /home/devuser

# Switch to the devuser
USER devuser
WORKDIR /workspaces
RUN uv --generate-shell-completion bash >> ~/.bash_completion

CMD ["bash"]
