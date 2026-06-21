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
import sys
from typing import Optional

from pydantic import Field
from pydantic import field_validator
from pydantic import HttpUrl
from pydantic import ValidationError
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict

from .constants import Service
from .logger import logger


class Settings(BaseSettings):
  """Application configuration settings for Oremi Akọrin.

  All settings can be configured via environment variables.
  Service URLs are optional - if not provided, the service will run in chat-only mode.
  """

  model_config = SettingsConfigDict(
    env_prefix="",
    env_nested_delimiter="__",
    env_file=".env",
    env_file_encoding="utf-8",
    extra="ignore",
    case_sensitive=False,
    # Enable parsing environment variables from OS
    env_ignore_empty=False,
    # Allow mutable default values
    frozen=False,
  )

  # ── Server Settings ──────────────────────────────────────────────────────────

  server_host: str = Field(
    default="localhost",
    alias="SERVER_HOST",
    description="Host address to bind the server to. Use '0.0.0.0' to listen on all interfaces.",
  )

  server_port: int = Field(
    default=5020,
    alias="SERVER_PORT",
    ge=1,
    le=65535,
    description="Port number to bind the server to. Must be between 1 and 65535.",
  )

  api_root_path: str = Field(
    default="/",
    alias="API_ROOT_PATH",
    description="Root path for the FastAPI application. Used when running behind a proxy.",
  )

  # ── Ollama Settings ──────────────────────────────────────────────────────────

  ollama_host: HttpUrl = Field(alias="OLLAMA_HOST", description="URL of the Ollama service. Must include scheme and port.")

  ollama_model: str = Field(
    default="qwen2.5:3b",
    alias="OLLAMA_MODEL",
    description="Name of the Ollama model to load and use for NLP processing.",
  )

  ollama_pull_model: bool = Field(
    default=True,
    alias="OLLAMA_PULL_MODEL",
    description="Whether to automatically pull the model from Ollama registry if not available locally.",
  )

  ollama_request_timeout: float = Field(
    default=60.0,
    alias="OLLAMA_REQUEST_TIMEOUT",
    gt=1.0,
    description="Timeout in seconds for Ollama requests. Must be greater than 1.0.",
  )

  # ── Service URLs ──────────────────────────────────────────────────────────────
  # All service URLs are optional - no default values

  isinmi_url: Optional[HttpUrl] = Field(
    default=None,
    alias="ISINMI_URL",
    description="Base URL for the Isinmi service.",
  )

  weather_url: Optional[HttpUrl] = Field(
    default=None,
    alias="WEATHER_URL",
    description="Base URL for weather forecasts and alerts.",
  )

  rediyo_url: Optional[HttpUrl] = Field(
    default=None,
    alias="REDIYO_URL",
    description="Base URL for the Rediyo service.",
  )

  kansa_url: Optional[HttpUrl] = Field(
    default=None,
    alias="KANSA_URL",
    description="Base URL for the Kansa service.",
  )

  # ── MQTT Settings ──────────────────────────────────────────────────────────
  # MQTT is optional - all settings can be omitted if not using MQTT

  mqtt_broker: Optional[str] = Field(
    default=None,
    alias="MQTT_BROKER",
    description="MQTT broker hostname or IP address. If not set, MQTT is disabled.",
  )

  mqtt_port: int = Field(
    default=1883,
    alias="MQTT_PORT",
    ge=1,
    le=65535,
    description="MQTT broker port. Must be between 1 and 65535. Default: 1883.",
  )

  mqtt_client_id: Optional[str] = Field(
    default=None,
    alias="MQTT_CLIENT_ID",
    description="MQTT client identifier. If not set, auto-generated from hostname and process ID.",
  )

  mqtt_username: Optional[str] = Field(
    default=None,
    alias="MQTT_USERNAME",
    description="MQTT broker username. Optional - only needed if authentication is required.",
  )

  mqtt_password: Optional[str] = Field(
    default=None,
    alias="MQTT_PASSWORD",
    description="MQTT broker password. Optional - only needed if authentication is required.",
  )

  mqtt_request_topic: str = Field(
    default="oremi/akorin/request",
    alias="MQTT_REQUEST_TOPIC",
    description="MQTT topic to subscribe for NLP processing requests.",
  )

  mqtt_response_topic: str = Field(
    default="oremi/akorin/response",
    alias="MQTT_RESPONSE_TOPIC",
    description="MQTT topic to publish NLP processing responses.",
  )

  mqtt_state_topic: str = Field(
    default="oremi/akorin/state",
    alias="MQTT_STATE_TOPIC",
    description="MQTT topic to publish processing state updates.",
  )

  mqtt_keepalive: int = Field(
    default=60,
    alias="MQTT_KEEPALIVE",
    ge=10,
    description="MQTT keepalive interval in seconds. Must be at least 10. Default: 60.",
  )

  mqtt_tls_enabled: bool = Field(
    default=False,
    alias="MQTT_TLS_ENABLED",
    description="Enable TLS/SSL for MQTT connection. Default: false.",
  )

  mqtt_tls_ca_cert: Optional[str] = Field(
    default=None,
    alias="MQTT_TLS_CA_CERT",
    description="Path to CA certificate file for MQTT TLS verification.",
  )

  # ── Request Settings ──────────────────────────────────────────────────────────

  request_timeout: float = Field(
    default=30.0,
    alias="REQUEST_TIMEOUT",
    gt=1.0,
    description="Global timeout in seconds for HTTP requests to external services. Default: 30.0.",
  )

  max_response_tokens: int = Field(
    default=500,
    alias="MAX_RESPONSE_TOKENS",
    gt=10,
    le=4096,
    description="Maximum number of tokens to generate in LLM responses. Default: 500.",
  )

  temperature: float = Field(
    default=0.7,
    alias="LLM_TEMPERATURE",
    ge=0.0,
    le=1.0,
    description="Temperature for LLM generation - controls randomness (0=deterministic, 1=creative). Default: 0.7.",
  )

  # ── Search Settings ──────────────────────────────────────────────────────────

  search_enabled: bool = Field(
    default=True,
    alias="SEARCH_ENABLED",
    description="Enable DuckDuckGo search fallback for unknown queries. Default: true.",
  )

  search_timeout: float = Field(
    default=10.0,
    alias="SEARCH_TIMEOUT",
    gt=1.0,
    description="Timeout in seconds for search requests. Default: 10.0.",
  )

  # ── Logging Settings ──────────────────────────────────────────────────────────

  log_level: str = Field(
    default="INFO",
    alias="LOG_LEVEL",
    description="Logging level. One of: DEBUG, INFO, WARNING, ERROR, CRITICAL. Default: INFO.",
  )

  log_file: Optional[str] = Field(
    default=None,
    alias="LOG_FILE",
    description="Path to log file. If not set, logs are written to stderr.",
  )

  # ── Validators ──────────────────────────────────────────────────────────────

  @field_validator("ollama_host", mode="before")
  @classmethod
  def validate_ollama_host(cls, value):
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
        raise ValueError("MQTT_BROKER must contain only a hostname or IP address")

    return value

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

  @field_validator("log_level")
  @classmethod
  def validate_log_level(cls, value):
    """Validate log level is valid."""
    valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    if value.upper() not in valid_levels:
      raise ValueError(f"Invalid LOG_LEVEL: {value}. Must be one of {valid_levels}")
    return value.upper()

  # ── Properties ──────────────────────────────────────────────────────────────

  @property
  def is_mqtt_enabled(self) -> bool:
    """Check if MQTT is enabled (broker is configured)."""
    return bool(self.mqtt_broker)

  @property
  def mqtt_credentials(self) -> Optional[tuple[str, str]]:
    """Get MQTT credentials as a tuple if both username and password are set."""
    if self.mqtt_username and self.mqtt_password:
      return (self.mqtt_username, self.mqtt_password)
    return None

  @property
  def service_urls(self) -> dict[Service, Optional[HttpUrl]]:
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


def _format_validation_error(error: ValidationError) -> str:
  """Format validation errors with clear, user-friendly messages."""
  error_messages = []

  for err in error.errors():
    field = ".".join(str(loc) for loc in err["loc"])
    error_type = err["type"]
    msg = err.get("msg", "Invalid value")

    # Customize error messages based on error type
    if error_type == "url_parsing":
      env_var = field.upper().replace(".", "_")
      error_messages.append(f"  - {env_var}: Invalid URL format - {msg}")
    elif error_type == "value_error":
      env_var = field.upper().replace(".", "_")
      error_messages.append(f"  - {env_var}: {msg}")
    elif error_type == "less_than_equal":
      env_var = field.upper().replace(".", "_")
      error_messages.append(f"  - {env_var}: Value must be less than or equal to {err.get('le', '')}")
    elif error_type == "greater_than_equal":
      env_var = field.upper().replace(".", "_")
      error_messages.append(f"  - {env_var}: Value must be greater than or equal to {err.get('ge', '')}")
    elif error_type == "greater_than":
      env_var = field.upper().replace(".", "_")
      error_messages.append(f"  - {env_var}: Value must be greater than {err.get('gt', '')}")
    elif error_type == "less_than":
      env_var = field.upper().replace(".", "_")
      error_messages.append(f"  - {env_var}: Value must be less than {err.get('lt', '')}")
    elif error_type == "type_error":
      env_var = field.upper().replace(".", "_")
      expected_type = err.get("ctx", {}).get("expected", "")
      error_messages.append(f"  - {env_var}: Expected {expected_type} - {msg}")
    else:
      env_var = field.upper().replace(".", "_")
      error_messages.append(f"  - {env_var}: {msg}")

  return "\n".join(error_messages)


# ── Helper Functions ────────────────────────────────────────────────────────────

_settings: Settings


def get_settings(exit_on_error: bool = True, require_mqtt: bool = False) -> Settings:
  """Load and validate settings with detailed error messages.

  Args:
      exit_on_error: If True, exit the process on validation error.
      require_mqtt: If True, require MQTT to be configured.

  Returns:
      Settings: Validated settings instance.

  Raises:
      ValidationError: If validation fails and exit_on_error is False.
      SystemExit: If validation fails and exit_on_error is True.
  """
  if hasattr(get_settings, "_settings"):
    return getattr(get_settings, "_settings")

  try:
    settings = Settings()  # type: ignore

    # Check if MQTT is required but not configured
    if require_mqtt and not settings.is_mqtt_enabled:
      error_msg = (
        "\n"
        "============================================================\n"
        "CONFIGURATION ERROR\n"
        "============================================================\n"
        "MQTT configuration is required but not provided.\n"
        "Please set MQTT_BROKER environment variable.\n"
        "Example: MQTT_BROKER=localhost\n"
        "============================================================"
      )

      logger.error(error_msg)

      if exit_on_error:
        sys.exit(1)

      raise ValueError("MQTT configuration required but not provided")

    setattr(get_settings, "_settings", settings)

    return settings
  except ValidationError as error:
    error_msg = (
      "\n"
      "============================================================\n"
      "CONFIGURATION VALIDATION FAILED\n"
      "============================================================\n"
      "The following environment variables have invalid values:\n"
      "\n"
      f"{_format_validation_error(error)}\n"
      "\n"
      "Please correct these values and try again.\n"
      "For help, refer to the documentation or run with --help.\n"
      "============================================================"
    )

    logger.error(error_msg)

    if exit_on_error:
      sys.exit(1)

    raise

  except ValueError as error:
    error_msg = (
      "\n"
      "============================================================\n"
      "CONFIGURATION ERROR\n"
      "============================================================\n"
      f"{error!s}\n"
      "\n"
      "Please check your configuration and try again.\n"
      "============================================================"
    )

    logger.error(error_msg)

    if exit_on_error:
      sys.exit(1)

    raise

  except Exception as error:
    error_msg = (
      "\n"
      "============================================================\n"
      "UNEXPECTED CONFIGURATION ERROR\n"
      "============================================================\n"
      f"Failed to load configuration: {error!s}\n"
      "\n"
      "Please check your environment and configuration.\n"
      "============================================================"
    )

    logger.error(error_msg)

    if exit_on_error:
      sys.exit(1)

    raise
