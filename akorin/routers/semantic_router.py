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
import asyncio
import json
import logging
from time import perf_counter
from typing import Callable

import httpx

from akorin.agents.command_agent import CommandAgent
from akorin.core.router import RequestRouter
from akorin.core.router import RouteContext
from akorin.core.router import RouteDecision
from akorin.core.service import Service

logger = logging.getLogger(__name__)


class SemanticRouter(RequestRouter):
  def __init__(self, agent: CommandAgent, timeout_calculator: Callable[[float], float]):
    self.agent = agent
    self.timeout_calculator = timeout_calculator

  async def route(self, context: RouteContext) -> RouteDecision:
    logger.debug(f"[{context.request_id}] Evaluating SemanticRouter")
    routing_started = perf_counter()
    try:
      timeout = self.timeout_calculator(context.started_at)
      logger.debug(f"[{context.request_id}] SemanticRouter: Allowed timeout is {timeout:.2f}s")

      decision = await asyncio.wait_for(self.agent.classify(context.request.message), timeout=timeout)

      logger.info(
        f"[{context.request_id}] SemanticRouter decision: service={decision.service.value} "
        f"confidence={decision.confidence:.2f} "
        f"duration_ms={(perf_counter() - routing_started) * 1000:.1f}"
      )
      return RouteDecision(service=decision.service, confidence=decision.confidence, source="semantic")

    except (asyncio.TimeoutError, httpx.HTTPError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exception:
      logger.warning(f"[{context.request_id}] SemanticRouter failed, using fallback: {exception}")
      return RouteDecision(service=Service.UNKNOWN, confidence=0.0, source="fallback")
