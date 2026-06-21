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
    "description": (
      "Process English or French natural-language requests and route them to "
      "Ollama, built-in tools, knowledge sources, or configured Oremi services."
    ),
  }

  api.openapi_tags.append(tag)  # type: ignore

  @api.post(
    path="/api/process",
    summary="Process a natural-language request",
    tags=[tag["name"]],
    response_model=ProcessResponse,
    status_code=status.HTTP_200_OK,
    responses={
      200: {
        "description": (
          "The request was processed. Inspect `ok` to distinguish a successful result "
          "from an expected service or input failure."
        ),
        "content": {
          "application/json": {
            "examples": {
              "weather": {
                "summary": "Weather result",
                "value": {
                  "ok": True,
                  "input": "What's the weather like in Lagos?",
                  "language": "en",
                  "service": "weather",
                  "message": (
                    "It's quite warm in Lagos with temperatures around 26°C. Humidity is at 82%, so it feels a bit sticky."
                    "With winds blowing at about 12 km/h from the northeast, and considering the sunset will be at 6 PM today, "
                    "that might make for some pleasant evenings. Take a hat and maybe an umbrella if rain is in the forecast."
                  ),
                  "data": {
                    "provider": "Open-Météo",
                    "input": "What's the weather like in Lagos?",
                    "services": ["weather"],
                    "message": (
                      "It's quite warm in Lagos with temperatures around 26°C."
                      "Humidity is at 82%, so it feels a bit sticky. With winds blowing at about 12 km/h from the northeast, "
                      "and considering the sunset will be at 6 PM today, that might make for some pleasant evenings. Take a "
                      "hat and maybe an umbrella if rain is in the forecast."
                    ),
                    "data": {
                      "weather": {
                        "temperature": "26.4°C",
                        "humidity": "82%",
                        "wind_speed": "12.3 km/h",
                        "sunrise": "05:33:00",
                        "sunset": "18:03:00",
                      }
                    },
                    "location": {
                      "type": "city",
                      "name": "Lagos",
                      "boundingbox": [6.2950575, 6.6150575, 3.2341795, 3.5541795],
                      "lat": 6.4550575,
                      "lon": 3.3941795,
                      "addresstype": "city",
                      "display_name": "Lagos, Lagos Island, Lagos State, 100242, Nigeria",
                      "address": {
                        "country": "Nigeria",
                        "country_code": "ng",
                        "region": None,
                        "postcode": "100242",
                        "road": None,
                        "town": None,
                        "municipality": None,
                        "county": "Lagos Island",
                        "state": "Lagos State",
                        "city": "Lagos",
                      },
                    },
                  },
                  "confidence": 0.95,
                },
              },
              "tool": {
                "summary": "Built-in tool result",
                "value": {
                  "ok": True,
                  "input": "What is 18 * 4?",
                  "language": "en",
                  "service": "tool",
                  "message": "18 multiplied by 4 is 72.",
                  "data": {"tools": [{"name": "calculate", "expression": "18 * 4", "result": 72}]},
                  "confidence": 1.0,
                },
              },
              "more_information_required": {
                "summary": "Expected input failure",
                "value": {
                  "ok": False,
                  "input": "Set an alarm for tomorrow morning",
                  "language": "en",
                  "service": "isinmi",
                  "message": "Please specify your timezone so I can schedule this at the correct time.",
                  "data": {"error": {"type": "more_information_required"}},
                  "confidence": 0.98,
                },
              },
            }
          }
        },
      },
      422: {
        "description": "The JSON body does not match the request schema.",
        "content": {
          "application/json": {
            "example": {
              "detail": [
                {
                  "type": "string_too_short",
                  "loc": ["body", "text"],
                  "msg": "String should have at least 1 character",
                  "input": "",
                  "ctx": {"min_length": 1},
                }
              ]
            }
          }
        },
      },
      500: {
        "description": "An unexpected processing error occurred.",
        "content": {"application/json": {"example": {"detail": "Internal Server Error"}}},
      },
    },
  )
  async def process_user_input(
    request: Request,
    payload: ProcessRequest = Body(
      ...,
      description=(
        "The user's text plus optional language, service context, and caller-defined tags. "
        "Context requirements depend on the selected service."
      ),
      openapi_examples={
        "weather": {
          "summary": "Weather forecast",
          "description": "Timezone and temperature unit are forwarded to the weather service.",
          "value": {
            "text": "What's the weather like in Lagos?",
            "language": "en",
            "context": {"timezone": "Africa/Lagos", "temperature_unit": "celsius"},
          },
        },
        "reminder": {
          "summary": "Schedule a reminder",
          "description": "Isinmi requires an IANA timezone to resolve relative dates correctly.",
          "value": {
            "text": "Remind me to call Ada tomorrow at 9 AM",
            "language": "en",
            "context": {"timezone": "Europe/Paris"},
            "tags": {"user": "ada"},
          },
        },
        "weather_alert": {
          "summary": "Check local weather alerts",
          "description": "Alerts require a category and geographic coordinates.",
          "value": {
            "text": "Are there weather alerts near me?",
            "context": {
              "alert_service": "weather",
              "lat": 48.8566,
              "lon": 2.3522,
              "timezone": "Europe/Paris",
            },
          },
        },
        "zigbee": {
          "summary": "Control a Zigbee device",
          "description": "Device and state can be inferred from text or supplied explicitly in context.",
          "value": {
            "text": "Turn off the bedroom lamp",
            "language": "en",
            "context": {"device": "bedroom_lamp", "state": "OFF"},
          },
        },
      },
    ),
  ) -> ProcessResponse:
    """Process and route a natural-language request.

    The endpoint normalizes the input, detects its language when `language` is
    omitted, and routes the request to the best available capability:

    - conversational answers and native date/time, calculator, or conversion tools;
    - Wikipedia for stable knowledge and DuckDuckGo for current information;
    - configured scheduling, weather, radio, podcast, or Zigbee services.

    `context` carries structured data needed by a service, such as an IANA
    timezone, coordinates, temperature unit, or device state. `tags` contains
    caller-defined string metadata and is forwarded where supported.

    A valid request normally returns HTTP 200 even when a selected service needs
    more information or is temporarily unavailable. In that case, `ok` is false,
    `message` is safe to show to the user, and `data.error.type` identifies the
    failure. Schema validation failures return HTTP 422.
    """
    context: AppContext = request.app.state.context

    return await context.orchestrator.process(payload)
