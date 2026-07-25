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
import logging
from time import perf_counter
from typing import Any
from typing import Awaitable
from typing import TYPE_CHECKING
from uuid import uuid4

import httpx

from akorin.agents.chat_agent import ChatAgent
from akorin.agents.chat_tools_agent import ChatToolsAgent
from akorin.agents.command_agent import CommandAgent
from akorin.agents.prompt_selector_agent import PromptSelectorAgent
from akorin.agents.response_agent import ResponseAgent
from akorin.core.exceptions import ComponentRequestError
from akorin.core.exceptions import ComponentUnavailable
from akorin.core.request import ProcessRequest
from akorin.core.request import ProcessRequestContext
from akorin.core.response import ProcessResponse
from akorin.core.router import RequestRouter
from akorin.core.router import RouteContext
from akorin.core.router import RouteDecision
from akorin.core.router import RoutePromptDecision
from akorin.core.router import RouteSemanticDecision
from akorin.core.service import Service
from akorin.core.settings import Settings
from akorin.core.tools import GetPromptTool
from akorin.core.tools import ListPromptsTool
from akorin.core.tools import ListResourcesTool
from akorin.core.tools import MCPTool
from akorin.core.tools import OllamaTool
from akorin.core.tools import ReadResourceTool
from akorin.core.tools import ToolRegistry
from akorin.routers.mcp_router import McpPromptRouter
from akorin.routers.semantic_router import SemanticRouter
from akorin.utils.cache import has_volatile_context
from akorin.utils.cache import SmartCache
from akorin.utils.language import detect_language
from akorin.utils.response_commands import select_device_commands
from akorin.utils.service_context import context_for_service

if TYPE_CHECKING:
  from akorin.core.components import ComponentClient


logger = logging.getLogger(__name__)
ServiceHandlers = dict[Service, "ComponentClient"]


class Orchestrator:
  def __init__(
    self,
    settings: Settings,
    client: httpx.AsyncClient,
    handlers: ServiceHandlers,
    tools: ToolRegistry,
    cache: SmartCache,
  ):
    self.settings = settings
    self.handlers = handlers
    self.registry = tools
    self.cache = cache

    self.chat_agent = ChatAgent(settings, client, cache)
    self.chat_tools_agent_agent = ChatToolsAgent(settings, client, cache)
    self.command_agent = CommandAgent(settings, client, cache)
    self.response_agent = ResponseAgent(settings, client, cache)
    self.prompt_selector_agent_agent = PromptSelectorAgent(settings, client, cache)

    # Initialize Routing Chain
    self.routers: list[RequestRouter] = [
      McpPromptRouter(self.prompt_selector_agent_agent),
      SemanticRouter(self.command_agent, lambda started: self._timeout_for(started, self.settings.route_timeout_seconds)),
    ]

  # --- Retained Helper Methods ---

  def _timeout_for(self, started: float, step_timeout: float) -> float:
    elapsed = perf_counter() - started
    remaining = self.settings.request_budget_seconds - elapsed
    return max(0.1, min(step_timeout, remaining))

  async def _timed(self, timeout_seconds: float, operation: Awaitable[Any]) -> Any:
    return await asyncio.wait_for(operation, timeout=timeout_seconds)

  async def get_effective_tools(self) -> ToolRegistry:
    all_tools = list(self.registry.tools.values())
    all_tools.extend(
      [
        ListResourcesTool(self.handlers),
        ReadResourceTool(self.handlers),
        ListPromptsTool(self.handlers),
        GetPromptTool(self.handlers),
      ]
    )

    for service, handler in self.handlers.items():
      try:
        service_tools = await handler.get_tools()

        all_tools.extend(service_tools)
      except asyncio.exceptions.CancelledError:
        logger.warning(f"Could not retrieve tools for service {service}: component is not ready")
      except Exception as exception:
        logger.warning(f"Could not retrieve tools for service {service}: {exception}")

    return ToolRegistry(all_tools)

  async def _chat_with_tools(
    self, message: str, request: ProcessRequest, language: str, tools: ToolRegistry | None = None
  ) -> Any:
    return await self.chat_tools_agent_agent.chat(message, language, request.context, tools or self.registry)

  def _context_for_service(self, service: Service, context: ProcessRequestContext) -> dict[str, Any]:
    if has_volatile_context(context):
      return context_for_service(service, context)

    cache_key = self.cache.make_key("context", {"service": service.value, "context": context})
    cached = self.cache.get(cache_key)

    if isinstance(cached, dict):
      return cached

    selected = context_for_service(service, context)
    self.cache.set(cache_key, selected, self.settings.llm_cache_ttl_seconds)

    return selected

  async def _fetch_all_prompts(self, request_id: str) -> tuple[list[Any], dict[str, Service]]:
    """Concurrently fetch prompts from all configured handlers."""
    logger.info(f"[{request_id}] Fetching prompts from {len(self.handlers)} handlers concurrently")

    all_prompts = []
    prompt_to_service = {}

    async def fetch_for_service(service: Service, handler: "ComponentClient") -> tuple[Service, list[Any]]:
      try:
        prompts = await handler.get_prompts()
        logger.info(f"[{request_id}] Fetched {len(prompts)} prompts from {service.value}")

        return service, prompts
      except asyncio.exceptions.CancelledError:
        logger.warning(f"[{request_id}] Skipping prompt discovery for {service.value}: component is not ready")
        return service, []
      except Exception as exception:
        logger.warning(f"[{request_id}] Failed to retrieve prompts for service {service}: {exception}")
        return service, []

    results = await asyncio.gather(*(fetch_for_service(service, handler) for service, handler in self.handlers.items()))

    for service, prompts in results:
      for prompt in prompts:
        all_prompts.append(prompt)
        prompt_to_service[prompt.name] = service

    logger.info(f"[{request_id}] Total prompts fetched: {len(all_prompts)}")

    return all_prompts, prompt_to_service

  # --- Core Processing Pipeline ---

  async def process(self, request: ProcessRequest) -> ProcessResponse:
    request_id = uuid4().hex[:8]
    processing_started = perf_counter()
    language = detect_language(request.message)

    logger.info(
      f"[{request_id}] Processing started: input_chars={len(request.message)} "
      f"detected_language={language} context_keys={sorted(request.context)} "
      f"input_text={request.message!r}"
    )

    all_prompts, prompt_to_service = await self._fetch_all_prompts(request_id)

    route_context = RouteContext(
      request=request,
      request_id=request_id,
      language=language,
      started_at=processing_started,
      all_prompts=all_prompts,
      prompt_to_service=prompt_to_service,
    )

    # 1. Pipeline Routing Execution
    logger.debug(f"[{request_id}] Initiating routing pipeline")
    decision: RouteDecision | None = None

    for router in self.routers:
      decision = await router.route(route_context)

      if decision:
        logger.info(f"[{request_id}] Route resolved by {router.__class__.__name__}: service={decision.service.value}")
        break

    if not decision:
      logger.info(f"[{request_id}] No route found in pipeline, defaulting to UNKNOWN")
      decision = RouteSemanticDecision(service=Service.CHAT, confidence=0.0)

    # 2. Service Dispatching
    logger.debug(f"[{request_id}] Proceeding to execute service logic for {decision.service.value}")

    try:
      if decision.service == Service.CHAT:
        response_payload = await self._execute_chat_service(request, language, request_id)
      else:
        response_payload = await self._execute_mcp_service(request, language, decision, request_id, prompt_to_service)
    except Exception as exception:
      logger.error(f"[{request_id}] Unhandled exception during service execution: {exception}", exc_info=True)
      response_payload = await self._handle_execution_failure(exception, request, language, decision, request_id)

    # 3. Finalize Response
    response_message = response_payload.get("message", "")
    response_data = response_payload.get("data", None)
    payload_ok = response_payload.get("ok")
    is_ok = bool(payload_ok) if payload_ok is not None else bool(response_message)

    if not is_ok and not response_message:
      response_message = await self.response_agent.generate(
        "service_execution_failed",
        language,
        {"service": decision.service.value, "request": request.message},
      )

    response = ProcessResponse(
      ok=is_ok,
      input=request.message,
      language=language,
      service=response_payload.get("service", decision.service),
      message=response_message,
      data=response_data,
      confidence=response_payload.get("confidence", decision.confidence),
    )

    response.commands = select_device_commands(response)

    logger.info(
      f"[{request_id}] Processing completed in {(perf_counter() - processing_started) * 1000:.1f}ms: {decision} {response}"
    )

    return response

  async def _execute_chat_service(self, request: ProcessRequest, language: str, request_id: str) -> dict[str, Any]:
    dispatch_started = perf_counter()
    logger.debug(f"[{request_id}] Fetching effective tools for CHAT service")
    effective_tools = await self.get_effective_tools()

    logger.debug(f"[{request_id}] Dispatching to agent chat with {len(effective_tools.definitions)} tools")

    request.context = self._context_for_service(Service.CHAT, request.context)
    chat_result = await self._chat_with_tools(request.message, request, language, tools=effective_tools)

    service = Service.CHAT
    confidence = 1.0
    data = {}

    if chat_result.tools:
      logger.debug(f"[{request_id}] Tools executed during chat: {[t.name for t in chat_result.tools]}")
      cmd_services = {Service.OREMI_REDIYO, Service.OREMI_KANSA, Service.OREMI_ISINMI}
      executed_tool = next((t for t in chat_result.tools if t.service in cmd_services), chat_result.tools[0])

      if executed_tool.service in cmd_services:
        logger.debug(f"[{request_id}] Tool maps to command service: {executed_tool.service.value}")
        service = executed_tool.service
        data = executed_tool.data
      else:
        logger.debug(f"[{request_id}] Tool maps to generic tool execution")
        service = Service.TOOL
        data = {"tools": [r.data | {"name": r.name} for r in chat_result.tools]}

    logger.info(
      f"[{request_id}] Agent chat completed: service={service.value} "
      f"duration_ms={(perf_counter() - dispatch_started) * 1000:.1f}"
    )

    return {"service": service, "confidence": confidence, "message": chat_result.message, "data": data}

  async def _execute_mcp_service(
    self,
    request: ProcessRequest,
    language: str,
    decision: RouteDecision,
    request_id: str,
    prompt_to_service: dict[str, Service],
  ) -> dict[str, Any]:
    handler = self.handlers.get(decision.service)

    if not handler:
      logger.error(f"[{request_id}] Configuration error: No handler found for {decision.service.value}")
      raise ComponentUnavailable(decision.service, "component is not configured")

    dispatch_started = perf_counter()
    request.context = self._context_for_service(decision.service, request.context)
    tools_list = await handler.get_tools()

    if not tools_list:
      logger.error(f"[{request_id}] Tools error: No tools available for {decision.service.value}")
      raise ComponentUnavailable(decision.service, "no tools available on component")

    logger.debug(f"[{request_id}] Retrieved {len(tools_list)} native tools for {decision.service.value}")
    component_tools_list: list[MCPTool | OllamaTool] = list(tools_list)
    component_tools_list.extend(
      [
        ListResourcesTool(self.handlers),
        ReadResourceTool(self.handlers),
        ListPromptsTool(self.handlers),
        GetPromptTool(self.handlers),
      ]
    )

    component_tools = ToolRegistry(component_tools_list)
    message_to_send = request.message

    try:
      if isinstance(decision, RoutePromptDecision) and decision.selected_prompt.name:
        logger.debug(f"[{request_id}] Rendering prompt: {decision.selected_prompt.name}")

        rendered = await handler.get_prompt(decision.selected_prompt.name, decision.selected_prompt.arguments)
        prompt_messages = []

        for msg in rendered.messages:
          prompt_messages.append(msg.content.text)

        if prompt_messages:
          message_to_send = "\n\n".join(prompt_messages)

          logger.debug(f"[{request_id}] Overrode input message with rendered prompt text ({len(message_to_send)} chars)")
    except Exception as exception:
      logger.warning(f"[{request_id}] Prompt rendering failed, falling back to original message: {exception}")

    logger.debug(f"[{request_id}] Initiating chat_with_tools for {decision.service.value}.\nMessage: {message_to_send}")

    chat_result = await self._chat_with_tools(message_to_send, request, language, tools=component_tools)
    data = {}

    if chat_result.tools:
      logger.debug(f"[{request_id}] Executed tools: {[t.name for t in chat_result.tools]}")
      primary_tool = next(
        (t for t in reversed(chat_result.tools) if t.name not in {"search_locations", "reverse_geocode"}), chat_result.tools[-1]
      )
      data = primary_tool.data

    ok = not (isinstance(data, dict) and data.get("ok") is False)

    logger.debug(
      f"[{request_id}] MCP Service {decision.service.value} completed ok={ok} in {(perf_counter() - dispatch_started) * 1000:.1f}ms"
    )

    return {"message": chat_result.message, "data": data, "ok": ok}

  async def _handle_execution_failure(
    self, exception: Exception, request: ProcessRequest, language: str, decision: RouteDecision, request_id: str
  ) -> dict[str, Any]:
    logger.warning(f"[{request_id}] Execution failed for {decision.service.value}: {exception}")

    if isinstance(exception, ComponentRequestError):
      logger.debug(f"[{request_id}] Failure type: ComponentRequestError. Requesting more info.")

      message = await self.response_agent.generate(
        "component_needs_more_information", language, {"service": decision.service.value, "request": request.message}
      )

      return {"ok": False, "message": message, "data": {"error": {"type": "more_information_required"}}}

    if isinstance(exception, ComponentUnavailable):
      logger.debug(f"[{request_id}] Failure type: ComponentUnavailable. Warning user.")

      message = await self.response_agent.generate(
        "component_temporarily_unavailable",
        language,
        {"service": exception.component.value if isinstance(exception.component, Service) else str(exception.component)},
      )

      return {"ok": False, "message": message, "data": {"error": {"type": "service_temporarily_unavailable"}}}

    # Fallback to chat
    logger.info(f"[{request_id}] Triggering fallback chat flow due to {type(exception).__name__}")

    try:
      request.context = self._context_for_service(Service.CHAT, request.context)
      chat_result = await self._chat_with_tools(request.message, request, language)

      data: dict[str, Any] = {"fallback_reason": str(exception)}

      if chat_result.tools:
        logger.debug(f"[{request_id}] Fallback execution fired tools: {[t.name for t in chat_result.tools]}")
        data["tools"] = [r.data | {"name": r.name} for r in chat_result.tools]

      return {
        "ok": True,
        "service": Service.TOOL if chat_result.tools else Service.CHAT,
        "confidence": min(decision.confidence, 0.5),
        "message": chat_result.message,
        "data": data,
      }
    except httpx.HTTPError as nested_exception:
      logger.error(f"[{request_id}] Fallback chat flow also failed: {nested_exception}")

      message = await self.response_agent.generate(
        "component_temporarily_unavailable", language, {"service": decision.service.value}
      )

      return {
        "ok": False,
        "message": message,
        "data": {"fallback_reason": str(exception), "nested_error": str(nested_exception)},
      }
