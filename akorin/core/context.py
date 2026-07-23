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
from typing import cast

from fastapi import FastAPI
from fastapi import Request

from akorin.core.components import ComponentsRegistry
from akorin.core.components import ComponentsStatuses
from akorin.core.orchestrator import Orchestrator
from akorin.core.settings import Settings


def set_app_context_settings(app: FastAPI, value: Settings) -> None:
  app.state.settings = value


def get_app_context_settings(request: Request) -> Settings:
  return cast(Settings, request.app.state.settings)


def set_app_context_components_registry(app: FastAPI, value: ComponentsRegistry) -> None:
  app.state.components = value


def get_app_context_components_registry(request: Request) -> ComponentsRegistry:
  return cast(ComponentsRegistry, request.app.state.components)


def set_app_context_components_statuses(app: FastAPI, value: ComponentsStatuses) -> None:
  app.state.component_statuses = value


def get_app_context_components_statuses(request: Request) -> ComponentsStatuses:
  return cast(ComponentsStatuses, request.app.state.component_statuses)


def set_app_context_orchestrator(app: FastAPI, value: Orchestrator) -> None:
  app.state.orchestrator = value


def get_app_context_orchestrator(request: Request) -> Orchestrator:
  return cast(Orchestrator, request.app.state.orchestrator)
