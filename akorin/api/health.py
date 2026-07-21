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

from akorin.core.context import get_app_context_components_registry
from akorin.core.context import get_app_context_components_statuses
from akorin.core.context import get_app_context_settings
from akorin.core.package import APP_NAME
from akorin.core.package import APP_VERSION
from akorin.core.service import Service

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

  components: dict[Service, str] = Field(
    description="Health status of individual external service components. Keys are service names, values are status messages."
  )


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
            }
          )
        }
      }
    }
  },
)
async def health(request: Request) -> ServerHealth:
  settings = get_app_context_settings(request)
  components_registry = get_app_context_components_registry(request)
  components_statuses = get_app_context_components_statuses(request)

  components = {
    service: "available" if components_statuses.get(service, False) else "unavailable" for service in components_registry
  }

  healthy = all(components_statuses.get(service, False) for service in components_registry)

  return ServerHealth(
    status="ok" if healthy else "degraded",
    app=APP_NAME,
    version=APP_VERSION,
    llm_model=settings.llm_model,
    components=components,
  )
