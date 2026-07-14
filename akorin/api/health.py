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
from typing import Literal

from fastapi import APIRouter
from fastapi import Request
from pydantic import BaseModel
from pydantic import Field

from ..core.constants import Service
from ..core.context import AppContext
from ..core.package import APP_NAME
from ..core.package import APP_VERSION
from ..core.settings import Settings

API_TAG_METADATA = {
  "name": "Server Endpoints",
  "description": (
    "Operational health and readiness endpoints. Use this tag for lightweight checks that confirm the "
    "API process is alive and report basic runtime metadata such as version and active AI model."
  ),
}

router = APIRouter(prefix="/health", tags=[API_TAG_METADATA["name"]])


class ServerHealth(BaseModel):
  status: Literal["ok", "degraded"] = Field(..., description="Health status of the API, typically 'ok' if healthy.")
  app: str = Field(..., description="Name of the application.")
  version: str = Field(..., description="Version of the application.")
  llm_model: str = Field(..., description="Configured AI model identifier used by the agent.")
  mqtt: str = Field(
    description="Health status of the MQTT broker connection. Indicates 'connected', 'disconnected', or error state."
  )
  components: dict[Service, str] = Field(
    description="Health status of individual external service components. Keys are service names, values are status messages."
  )


def get_app_settings(request: Request) -> Settings:
  return request.app.state.settings


@router.get(
  "/",
  summary="Health check",
  description=(
    "Return a lightweight health response for load balancers, Docker health checks, and monitoring tools. "
    "The response confirms the API is alive and includes the application version, active AI model, backend "
    "type, and whether encrypted storage is enabled."
  ),
  responses={
    200: {
      "content": {
        "application/json": {
          "example": ServerHealth.model_validate(
            {
              "status": "ok",
              "app": APP_NAME,
              "version": APP_VERSION,
              "llm_model": "ollama:qwen3.5:2b",
              "components": {
                Service.OREMI_ISINMI: "available",
                Service.OREMI_OJO: "available",
                Service.OREMI_REDIYO: "available",
                Service.OREMI_KANSA: "available",
              },
              "mqtt": "connected",
            }
          )
        }
      }
    }
  },
)
async def health(request: Request) -> ServerHealth:
  settings = get_app_settings(request)
  context: AppContext = request.app.state.context

  components = {
    service: "available" if context.component_statuses.get(service, False) else "unavailable" for service in context.components
  }

  healthy = all(context.component_statuses.get(service, False) for service in context.components)

  return ServerHealth(
    status="ok" if healthy else "degraded",
    app=APP_NAME,
    version=APP_VERSION,
    llm_model=settings.llm_model,
    components=components,
    mqtt="connected" if context.mqtt.connected else "disconnected",
  )
