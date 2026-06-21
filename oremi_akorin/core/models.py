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
from typing import Any

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from .constants import Language
from .constants import Service


class ProcessRequest(BaseModel):
  """Request model for NLP processing."""

  model_config = ConfigDict(str_strip_whitespace=True)

  text: str = Field(
    min_length=1,
    max_length=8000,
    description="Input text to be processed by the NLP system. Must be between 1 and 8000 characters.",
    examples=[
      "What's the weather like in Lagos?",
      "Play me some Afrobeat music",
      "Who is the president of Nigeria?",
      "Hello, how are you?",
    ],
  )

  language: Language | None = Field(
    default=None, description="Optional language code for the input text. If not provided, will be auto-detected."
  )
  context: dict[str, Any] = Field(
    default_factory=dict,
    description="Optional contextual information for the request. Used to maintain conversation state or provide additional processing context.",
  )
  tags: dict[str, str] = Field(
    default_factory=dict, description="Optional key-value tags for request categorization and filtering."
  )


class ProcessResponse(BaseModel):
  """Response model for NLP processing results."""

  ok: bool = Field(default=True, description="Indicates whether the processing was successful.")  # pylint: disable=invalid-name
  input: str = Field(description="Original input text that was processed.")
  language: Language = Field(description="Detected or specified language of the input text.")
  service: Service = Field(description="Service that handled the request (e.g., 'ollama', 'search', or external service).")
  message: str = Field(description="Human-readable response message containing the processing result or error details.")
  data: Any = Field(
    default_factory=dict,
    description="Additional structured data from the processing. Content varies based on the service and request type.",
  )
  confidence: float = Field(
    ge=0, le=1, description="Confidence score for the response, ranging from 0.0 (lowest) to 1.0 (highest)."
  )


class HealthResponse(BaseModel):
  """Response model for health check endpoints."""

  status: str = Field(description="Overall system health status. Typically 'healthy', 'degraded', or 'unhealthy'.")
  ollama: str = Field(
    description="Health status of the Ollama service connection. Indicates 'connected', 'disconnected', or error state."
  )
  components: dict[Service, str] = Field(
    description="Health status of individual external service components. Keys are service names, values are status messages."
  )
  mqtt: str = Field(
    description="Health status of the MQTT broker connection. Indicates 'connected', 'disconnected', or error state."
  )
