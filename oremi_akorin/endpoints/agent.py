# Copyright 2024-2026 Sébastien Demanou. All Rights Reserved.
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
from fastapi import Body
from fastapi import FastAPI
from fastapi import Request
from fastapi import status

from ..core.context import AppContext
from ..core.models import ProcessRequest
from ..core.models import ProcessResponse


def create_agent_endpoints(api: FastAPI) -> None:
  tag = {
    "name": "Agent Processing",
    "description": "Endpoints for natural language processing and agent-based interactions. "
    "These endpoints handle text analysis, language detection, "
    "and orchestration of various services (Ollama, weather, radio, etc.).",
  }

  api.openapi_tags.append(tag)  # type: ignore

  @api.post(
    path="/api/process",
    tags=[tag["name"]],
    status_code=status.HTTP_200_OK,
    responses={
      200: {
        "description": "Successfully processed the request",
        "content": {
          "application/json": {
            "example": ProcessResponse.model_validate(
              {
                "ok": True,
                "input": "What's the weather like in Lagos?",
                "language": "en",
                "service": "weather",
                "message": "The weather in Lagos is currently 28°C with scattered clouds.",
                "data": {"temperature": 28, "conditions": "scattered clouds", "humidity": 72, "city": "Lagos"},
                "confidence": 0.95,
              }
            )
          }
        },
      },
      400: {
        "description": "Bad request - invalid payload",
        "content": {"application/json": {"example": {"detail": "Text must be between 1 and 8000 characters"}}},
      },
      500: {
        "description": "Internal server error - processing failed",
        "content": {"application/json": {"example": {"detail": "Failed to process request: Ollama service unavailable"}}},
      },
    },
  )
  async def process_user_input(
    request: Request,
    payload: ProcessRequest = Body(
      ...,
      description=(
        "Natural language processing request payload. Contains the text to process "
        "along with optional language, context, and tags."
      ),
      examples=[
        {
          "summary": "Weather query",
          "description": "Request for weather information",
          "value": {
            "text": "What's the weather like in Lagos?",
            "language": "en",
          },
        },
        {
          "summary": "Radio recommendation",
          "description": "Request for radio station recommendations",
          "value": {
            "text": "Play me some Afrobeat music",
            "language": "en",
            "tags": {"category": "music", "genre": "afrobeat"},
          },
        },
        {
          "summary": "General knowledge query",
          "description": "Request for general information",
          "value": {
            "text": "Who is the president of Nigeria?",
            "language": "en",
            "context": {"topic": "politics"},
          },
        },
        {
          "summary": "Conversational chat",
          "description": "Simple conversational input",
          "value": {
            "text": "Hello, how are you?",
            "language": "en",
          },
        },
      ],
    ),
  ) -> ProcessResponse:
    """
    Process natural language input through the agent orchestrator.

    This endpoint accepts text input and routes it through the appropriate
    service based on intent detection. Supports:
    - Weather queries (via Isinmi or Weather services)
    - Radio station recommendations
    - Podcast recommendations
    - General knowledge queries (via Ollama/LLM)
    - Search fallback (DuckDuckGo)
    """
    context: AppContext = request.app.state.context

    return await context.orchestrator.process(payload)
