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
import os
from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic import field_validator
from pydantic import HttpUrl
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict

from .constants import Service


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
    description="Port number to bind the server to. Must be between 1 and 65535.",
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
      "You are Oremi, a concise and helpful bilingual personal assistant. "
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
    description="Base URL for the Isinmi service.",
  )

  weather_url: HttpUrl | None = Field(
    default=None,
    description="Base URL for weather forecasts and alerts.",
  )

  rediyo_url: HttpUrl | None = Field(
    default=None,
    description="Base URL for the Rediyo service.",
  )

  kansa_url: HttpUrl | None = Field(
    default=None,
    description="Base URL for the Kansa service.",
  )

  # MQTT is optional - all settings can be omitted if not using MQTT

  mqtt_broker: str | None = Field(
    default=None,
    description="MQTT broker hostname or IP address. If not set, MQTT is disabled.",
  )

  mqtt_port: int = Field(
    default=1883,
    ge=1,
    le=65535,
    description="MQTT broker port. Must be between 1 and 65535. Default: 1883.",
  )

  mqtt_client_id: str | None = Field(
    default=None,
    description="MQTT client identifier. If not set, auto-generated from hostname and process ID.",
  )

  mqtt_username: str | None = Field(
    default=None,
    description="MQTT broker username. Optional - only needed if authentication is required.",
  )

  mqtt_password: str | None = Field(
    default=None,
    description="MQTT broker password. Optional - only needed if authentication is required.",
  )

  oremi_device_mqtt_topic: str = Field(
    default="oremi/device",
    description="Base topic used by Oremi Device nodes.",
  )

  mqtt_keepalive: int = Field(
    default=60,
    ge=10,
    description="MQTT keepalive interval in seconds. Must be at least 10. Default: 60.",
  )

  mqtt_tls_enabled: bool = Field(
    default=False,
    description="Enable TLS/SSL for MQTT connection. Default: false.",
  )

  mqtt_tls_ca_cert: str | None = Field(
    default=None,
    description="Path to CA certificate file for MQTT TLS verification.",
  )

  request_timeout: float = Field(
    default=30.0,
    gt=1.0,
    description="Global timeout in seconds for HTTP requests to external services. Default: 30.0.",
  )

  max_response_tokens: int = Field(
    default=500,
    gt=10,
    le=4096,
    description="Maximum number of tokens to generate in LLM responses. Default: 500.",
  )

  search_enabled: bool = Field(
    default=True,
    description="Enable DuckDuckGo search fallback for unknown queries. Default: true.",
  )

  search_timeout: float = Field(
    default=10.0,
    gt=1.0,
    description="Timeout in seconds for search requests. Default: 10.0.",
  )

  log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(default="INFO", description="Logging level.")
  log_file: str = Field(default="oremi_isinmi.log", description="Path to rotating log file.")

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

  @field_validator("mqtt_broker", mode="before")
  @classmethod
  def validate_mqtt_broker(cls, value):
    """Normalize the MQTT broker to the hostname expected by Paho."""
    if value and isinstance(value, str):
      value = value.strip().rstrip("/")

      for scheme in ("mqtt://", "tcp://", "ssl://", "ws://", "wss://"):
        if value.startswith(scheme):
          value = value.removeprefix(scheme)
          break

      if not value or any(character in value for character in "/?#@"):
        raise ValueError("OREMI_AKORIN_MQTT_BROKER must contain only a hostname or IP address")

    return value

  @field_validator("oremi_device_mqtt_topic", mode="before")
  @classmethod
  def validate_oremi_device_mqtt_topic(cls, value):  # pylint: disable=invalid-name
    """Normalize the Oremi Device base topic and reject MQTT wildcards."""
    if isinstance(value, str):
      value = value.strip().strip("/")

    if not value or "+" in value or "#" in value:
      raise ValueError("OREMI_AKORIN_OREMI_DEVICE_MQTT_TOPIC must be a non-empty topic without wildcards")

    return value

  @property
  def mqtt_transcription_topic(self) -> str:
    """Topic filter for final transcriptions from every Oremi Device node."""
    return f"{self.oremi_device_mqtt_topic}/nodes/+/transcription/result"

  def mqtt_processing_result_topic(self, node_id: str) -> str:
    """Response topic for a specific Oremi Device node."""
    return f"{self.oremi_device_mqtt_topic}/nodes/{node_id}/processing/result"

  @field_validator("isinmi_url", "weather_url", "rediyo_url", "kansa_url")
  @classmethod
  def validate_component_base_url(cls, value):
    if value is not None and (value.path not in {"", "/"} or value.query or value.fragment):
      raise ValueError("component URL must be a base URL without a path, query, or fragment")

    return value

  @field_validator("mqtt_tls_ca_cert")
  @classmethod
  def validate_tls_cert(cls, value):
    """Validate TLS certificate file exists if provided."""
    if value and not os.path.isfile(value):
      raise ValueError(f"MQTT TLS CA certificate file not found: {value}")

    return value

  @property
  def is_mqtt_enabled(self) -> bool:
    """Check if MQTT is enabled (broker is configured)."""
    return bool(self.mqtt_broker)

  @property
  def mqtt_credentials(self) -> tuple[str, str] | None:
    """Get MQTT credentials as a tuple if both username and password are set."""
    if self.mqtt_username and self.mqtt_password:
      return (self.mqtt_username, self.mqtt_password)

    return None

  @property
  def service_urls(self) -> dict[Service, HttpUrl | None]:
    """Get all service URLs as a dictionary."""
    return {
      Service.ISINMI: self.isinmi_url,
      Service.WEATHER: self.weather_url,
      Service.REDIYO: self.rediyo_url,
      Service.KANSA: self.kansa_url,
    }

  @property
  def configured_services(self) -> list[str]:
    """Get list of configured service names."""
    return [name for name, url in self.service_urls.items() if url]

  @property
  def has_services(self) -> bool:
    """Check if any service URLs are configured."""
    return len(self.configured_services) > 0

  def uses_ollama(self) -> bool:
    """Return whether the active agent model uses the Ollama backend."""

    return self.llm_model.startswith("ollama:")

  def resolve_ollama_model_name(self) -> str:
    """Return the Ollama model name without provider prefix."""
    return self.llm_model.removeprefix("ollama:")  # pylint: disable=no-member

  @property
  def ollama_base_url_string(self) -> str:
    """Return the Ollama base URL for Pydantic AI."""
    if self.ollama_base_url is None:
      raise ValueError("OREMI_AKORIN_OLLAMA_BASE_URL is required when using an ollama: model")

    return str(self.ollama_base_url).rstrip("/")


@lru_cache
def get_settings() -> Settings:
  """Return cached application settings."""
  return Settings()
