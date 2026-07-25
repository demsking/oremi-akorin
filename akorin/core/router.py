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
from abc import ABC
from abc import abstractmethod

from mcp.types import Prompt
from pydantic import BaseModel
from pydantic import Field

from akorin.agents.prompt_selector_agent import SelectedPrompt
from akorin.core.request import ProcessRequest
from akorin.core.service import Service


class RouteSemanticDecision(BaseModel):
  service: Service
  confidence: float = Field(default=0.8, ge=0.0, le=1.0)

  def __str__(self) -> str:
    return f"RouteSemanticDecision(service={self.service.name}, confidence={self.confidence})"


class RoutePromptDecision(RouteSemanticDecision, BaseModel):
  selected_prompt: SelectedPrompt

  def __str__(self) -> str:
    return (
      f"RoutePromptDecision(service={self.service.name}, confidence={self.confidence}, selected_prompt={self.selected_prompt})"
    )


type RouteDecision = RouteSemanticDecision | RoutePromptDecision


class RouteContext(BaseModel):
  request: ProcessRequest
  request_id: str
  language: str
  started_at: float
  all_prompts: list[Prompt] = Field(default_factory=list)
  prompt_to_service: dict[str, Service] = Field(default_factory=dict)


class RequestRouter(ABC):
  """Abstract base class for all request routers."""

  @abstractmethod
  async def route(self, context: RouteContext) -> RouteDecision | None:
    """
    Evaluate the context and return a RouteDecision if this router
    can handle the request, otherwise return None.
    """
