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
import asyncio

from fastapi import FastAPI
from fastapi import Request
from fastapi import status

from ..core.constants import Service
from ..core.context import AppContext
from ..core.models import HealthResponse


def create_server_endpoints(api: FastAPI) -> None:
  tag = {
    "name": "Server Health",
    "description": "Endpoints for monitoring server health, service availability, "
    "and system status. These endpoints are used for health checks, "
    "load balancer probes, and system monitoring.",
  }

  api.openapi_tags.append(tag)  # type: ignore

  @api.get(
    path="/health",
    tags=[tag["name"]],
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    responses={
      200: {
        "description": "Health check completed successfully",
        "content": {
          "application/json": {
            "example": HealthResponse(
              status="healthy",
              ollama="connected",
              components={
                Service.ISINMI: "available",
                Service.WEATHER: "available",
                Service.WEATHER_ALERTS: "available",
                Service.REDIYO: "available",
                Service.KANSA: "available",
              },
              mqtt="connected",
            ).model_dump(mode="json")
          }
        },
      },
      503: {
        "description": "Service unavailable - one or more components are down",
        "content": {
          "application/json": {
            "example": HealthResponse(
              status="degraded",
              ollama="disconnected",
              components={
                Service.ISINMI: "unavailable",
                Service.WEATHER: "available",
                Service.WEATHER_ALERTS: "available",
                Service.REDIYO: "available",
                Service.KANSA: "available",
              },
              mqtt="connected",
            ).model_dump(mode="json")
          }
        },
      },
    },
  )
  async def get_service_health(request: Request) -> HealthResponse:
    """
    Check the health status of the application and its dependencies.

    This endpoint performs health checks on all integrated services:
    - Ollama service (required for NLP processing)
    - External service components (weather, radio, podcasts, etc.)
    - MQTT broker (for message queue communication)
    """
    context: AppContext = request.app.state.context

    component_items = list(context.components.items())
    results = await asyncio.gather(
      context.ollama.available(),
      *(component.available() for _, component in component_items),
    )

    ollama_ok, *component_statuses = results
    components = {
      service: "available" if available else "unavailable"
      for (service, _), available in zip(component_items, component_statuses, strict=True)
    }

    healthy = ollama_ok and all(component_statuses)

    return HealthResponse(
      status="healthy" if healthy else "degraded",
      ollama="connected" if ollama_ok else "disconnected",
      components=components,
      mqtt="connected" if context.mqtt.connected else "disconnected",
    )
