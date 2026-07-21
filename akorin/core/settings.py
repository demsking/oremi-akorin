# Copyright 2026 Sébastien Demanou. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
from functools import cached_property
from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic import field_validator
from pydantic import HttpUrl
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict

from akorin.core.service import Service


class Settings(BaseSettings):
  """Application configuration settings for Oremi Akọrin.

  All settings can be configured via environment variables.
  Service URLs are optional - if not provided, the service will run in chat-only mode.
  """

  model_config = SettingsConfigDict(
    env_prefix="OREMI_AKORIN_",
    strict=True,
    extra="ignore",
  )

  server_host: str = Field(
    default="127.0.0.1",
    description="Host address to bind the server to. Use '0.0.0.0' to listen on all interfaces.",
  )

  server_port: int = Field(
    default=5020,
    ge=1,
    le=65535,
    description="Port number to bind the server to.",
  )

  api_prefix: str = Field(default="/", description="API prefix for all endpoints.")

  llm_model: str = Field(
    default="ollama:qwen3.5:2b",
    description="Fully qualified Pydantic-AI model identifier.",
  )

  llm_request_timeout: int = Field(
    default=15,
    ge=1,
    le=300,
    description="Request timeout in seconds for LLM calls.",
  )

  llm_temperature: float = Field(
    default=0.3,
    ge=0.0,
    le=2.0,
    description="Sampling temperature used by the configured LLM backend.",
  )

  llm_system_prompt: str = Field(
    default=(
      "You are Oremi, a concise and helpful personal assistant. "
      "Give only the answer intended for the user; "
      "do not include hidden reasoning, prompt commentary, or context commentary. "
      "Use available tools and configured Oremi services whenever they can provide factual, current, or actionable results. "
      "Never invent tool results or service data. If required information is missing, ask one brief clarifying question. "
      "After receiving tool or service results, answer naturally without mentioning implementation details. "
      "Your name, Oremi, comes from the Yoruba phrase 'ore mi', meaning 'my friend'."
    ),
    description="System prompt for the AI agent.",
  )

  ollama_base_url: HttpUrl | None = Field(
    default=None,
    description="Ollama API base URL used when the agent runs on Ollama.",
  )

  isinmi_url: HttpUrl | None = Field(
    default=None,
    description="Base URL for the Oremi Isinmi service.",
  )

  ojo_url: HttpUrl | None = Field(
    default=None,
    description="Base URL for the Oremi Ojọ service.",
  )

  rediyo_url: HttpUrl | None = Field(
    default=None,
    description="Base URL for the Oremi Rediyo service.",
  )

  kansa_url: HttpUrl | None = Field(
    default=None,
    description="Base URL for the Oremi Kansa service.",
  )

  isakoso_url: HttpUrl | None = Field(
    default=None,
    description="Base URL for the Oremi Isakoso service.",
  )

  http_request_timeout: float = Field(
    default=30.0,
    gt=1.0,
    description="Global timeout in seconds for HTTP requests to external services. Default: 30.0.",
  )

  llm_max_response_tokens: int = Field(
    default=500,
    gt=10,
    le=4096,
    description="Maximum number of tokens to generate in LLM responses. Default: 500.",
  )

  llm_cache_enabled: bool = Field(
    default=True,
    description="Enable the bounded internal cache for repeated LLM and idempotent component calls.",
  )

  llm_cache_max_entries: int = Field(
    default=512,
    ge=0,
    le=10000,
    description="Maximum number of internal smart-cache entries kept in memory. Set to 0 to disable caching.",
  )

  llm_cache_ttl_seconds: float = Field(
    default=300.0,
    ge=0.0,
    le=3600.0,
    description="TTL in seconds for cacheable internal LLM calls.",
  )

  request_budget_seconds: float = Field(
    default=20.0,
    ge=1.0,
    le=300.0,
    description="Soft end-to-end latency budget in seconds for processing one user request.",
  )

  spellcheck_timeout_seconds: float = Field(
    default=4.0,
    ge=0.1,
    le=60.0,
    description="Maximum time in seconds to spend normalizing one user request before continuing with the original text.",
  )

  route_timeout_seconds: float = Field(
    default=4.0,
    ge=0.1,
    le=60.0,
    description="Maximum time in seconds to spend on LLM request classification before using heuristic routing.",
  )

  skip_spellcheck_max_chars: int = Field(
    default=24,
    ge=0,
    le=500,
    description="Skip LLM spellcheck for short clean command-like requests up to this length. Set to 0 to disable.",
  )

  component_cache_ttl_seconds: float = Field(
    default=30.0,
    ge=0.0,
    le=600.0,
    description="TTL in seconds for cacheable idempotent component HTTP calls.",
  )

  component_cache_stale_seconds: float = Field(
    default=120.0,
    ge=0.0,
    le=3600.0,
    description="Additional stale window in seconds for idempotent component HTTP calls while refreshing in the background.",
  )

  component_circuit_breaker_enabled: bool = Field(
    default=True,
    description="Temporarily fail fast for external components after repeated request failures.",
  )

  component_circuit_breaker_failures: int = Field(
    default=3,
    ge=1,
    le=100,
    description="Consecutive component request failures needed before opening the circuit breaker.",
  )

  component_circuit_breaker_cooldown_seconds: float = Field(
    default=30.0,
    ge=1.0,
    le=3600.0,
    description="Time in seconds an opened component circuit breaker stays open before allowing a retry.",
  )

  log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(default="INFO", description="Logging level.")
  log_file: str | None = Field(default=None, description="Path to rotating log file.")

  @field_validator("api_prefix")
  @classmethod
  def validate_api_prefix(cls, value: str) -> str:
    if not value.startswith("/"):
      raise ValueError("OREMI_AKORIN_API_PREFIX must start with '/'")

    return value.rstrip("/") or "/"

  @field_validator("ollama_base_url", mode="before")
  @classmethod
  def validate_ollama_base_url(cls, value):
    """Remove trailing slashes from Ollama host URL."""
    if isinstance(value, str):
      value = value.rstrip("/")

    return value

  @property
  def service_urls(self) -> dict[Service, HttpUrl | None]:
    """Get all service URLs as a dictionary."""
    return {
      Service.OREMI_ISINMI: self.isinmi_url,
      Service.OREMI_OJO: self.ojo_url,
      Service.OREMI_REDIYO: self.rediyo_url,
      Service.OREMI_KANSA: self.kansa_url,
    }

  @cached_property
  def configured_services(self) -> list[str]:
    """Get list of configured service names."""
    return [name for name, url in self.service_urls.items() if url]

  @cached_property
  def has_services(self) -> bool:
    """Check if any service URLs are configured."""
    return len(self.configured_services) > 0

  @cached_property
  def should_use_ollama(self) -> bool:
    """Return whether the active agent model uses the Ollama backend."""

    return self.llm_model.startswith("ollama:")

  @cached_property
  def ollama_model_name(self) -> str:
    """Return the Ollama model name without provider prefix."""
    return self.llm_model.removeprefix("ollama:")

  @cached_property
  def ollama_base_url_string(self) -> str:
    """Return the Ollama base URL for Pydantic AI."""
    if self.ollama_base_url is None:
      raise ValueError("OREMI_AKORIN_OLLAMA_BASE_URL is required when using an ollama: model")

    return str(self.ollama_base_url).rstrip("/")


@lru_cache
def get_settings() -> Settings:
  """Return cached application settings."""
  return Settings()
