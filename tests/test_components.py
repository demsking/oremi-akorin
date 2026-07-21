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
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import httpx
import pytest
from pydantic import BaseModel

from akorin.components.isinmi import IsinmiClient
from akorin.components.kansa import KansaClient
from akorin.components.ojo import OjoClient
from akorin.components.rediyo import RediyoClient
from akorin.core.components import monitor_unavailable_components
from akorin.core.oremi import OremiServerHealth
from akorin.core.service import Service


class FakeTool:
  def __init__(self, name, description, inputSchema):
    self.name = name
    self.description = description
    self.inputSchema = inputSchema


class FakeToolsList:
  def __init__(self, tools):
    self.tools = tools


class FakeServerInfo:
  def __init__(self, name, version):
    self.name = name
    self.version = version


@pytest.mark.asyncio
@pytest.mark.parametrize(
  ("component_type", "name", "url"),
  [
    (IsinmiClient, Service.OREMI_ISINMI, "http://isinmi.test"),
    (OjoClient, Service.OREMI_OJO, "http://weather.test"),
    (RediyoClient, Service.OREMI_REDIYO, "http://rediyo.test"),
    (KansaClient, Service.OREMI_KANSA, "http://kansa.test"),
  ],
)
async def test_component_mcp_client_workflow(component_type, name, url, caplog):
  mock_read = MagicMock()
  mock_write = MagicMock()

  mock_session = AsyncMock()
  mock_init_result = type("FakeInitResult", (), {"serverInfo": FakeServerInfo(name.value, "1.4.0")})()
  mock_session.initialize = AsyncMock(return_value=mock_init_result)
  mock_session.list_tools = AsyncMock(return_value=FakeToolsList([FakeTool("do_action", "Do some action", {"type": "object"})]))
  mock_session.call_tool = AsyncMock(return_value="tool_call_result")

  class AsyncContextManagerMock:
    def __init__(self, return_value):
      self.return_value = return_value

    async def __aenter__(self):
      return self.return_value

    async def __aexit__(self, exc_type, exc_val, exc_tb):
      pass

  with (
    patch("akorin.core.components.streamable_http_client", return_value=AsyncContextManagerMock((mock_read, mock_write, None))),
    patch("akorin.core.components.ClientSession", return_value=AsyncContextManagerMock(mock_session)),
  ):
    component = component_type(name, url, httpx.AsyncClient(), None)

    # 1. Test connect
    import logging

    with caplog.at_level(logging.INFO):
      await component.connect()
    assert component._session == mock_session
    assert any(
      f"Connected to MCP server {name.value}" in record.message and "do_action" in record.message for record in caplog.records
    )

    # 2. Test get_tools
    tools = await component.get_tools()
    assert len(tools) == 1
    assert tools[0].name == "do_action"

    # 3. Test call_tool
    res = await component.call_tool("do_action", {"text": "hello"})
    assert res == "tool_call_result"
    mock_session.call_tool.assert_called_with("do_action", {"text": "hello"})

    # 4. Test get_service_info
    info = await component.get_service_info()
    assert isinstance(info, OremiServerHealth)
    assert info.status == "healthy"
    assert info.app == name.value
    assert info.version == "1.4.0"

    # 5. Test disconnect
    await component.disconnect()
    assert component._session is None


@pytest.mark.asyncio
async def test_background_monitor_recovers_component_availability():
  class FlakyAvailabilityComponent:
    def __init__(self):
      self.calls = 0

    async def get_service_info(self):
      self.calls += 1
      if self.calls == 1:
        raise RuntimeError("offline")

      class Info(BaseModel):
        name: str
        version: str

      return Info(name="weather", version="1.0")

  component = FlakyAvailabilityComponent()
  statuses = {Service.OREMI_OJO: False}
  stop_event = asyncio.Event()

  task = asyncio.create_task(
    monitor_unavailable_components(
      {Service.OREMI_OJO: component},  # type: ignore[arg-type]
      statuses,
      stop_event=stop_event,
      interval_seconds=0.01,
    )
  )

  await asyncio.sleep(0.05)
  stop_event.set()
  await task

  assert statuses[Service.OREMI_OJO] is True


@pytest.mark.asyncio
async def test_component_reconnects_on_ping_failure():
  mock_read = MagicMock()
  mock_write = MagicMock()

  mock_session = AsyncMock()
  mock_init_result = type("FakeInitResult", (), {"serverInfo": FakeServerInfo("test_service", "1.4.0")})()
  mock_session.initialize = AsyncMock(return_value=mock_init_result)

  # Initial tools
  mock_session.list_tools = AsyncMock(return_value=FakeToolsList([FakeTool("do_action", "Do some action", {"type": "object"})]))
  mock_session.send_ping = AsyncMock()

  class AsyncContextManagerMock:
    def __init__(self, return_value):
      self.return_value = return_value

    async def __aenter__(self):
      return self.return_value

    async def __aexit__(self, exc_type, exc_val, exc_tb):
      pass

  with (
    patch("akorin.core.components.streamable_http_client", return_value=AsyncContextManagerMock((mock_read, mock_write, None))),
    patch("akorin.core.components.ClientSession", return_value=AsyncContextManagerMock(mock_session)),
  ):
    component = OjoClient(Service.OREMI_OJO, "http://weather.test", httpx.AsyncClient(), None)

    # 1. Connect first time
    await component.connect()
    assert component._session == mock_session
    assert len(component._tools) == 1
    assert component._tools[0].name == "do_action"

    # 2. Mock send_ping raising an exception to simulate server restart / connection loss
    mock_session.send_ping.side_effect = RuntimeError("connection lost")

    # 3. Mock list_tools to return updated tools for the next connection (reconnection)
    mock_session.list_tools = AsyncMock(
      return_value=FakeToolsList(
        [
          FakeTool("do_action", "Do some action", {"type": "object"}),
          FakeTool("new_action", "Updated action", {"type": "object"}),
        ]
      )
    )

    # 4. Calling get_service_info should detect ping failure, call disconnect(), and then reconnect() (which reloads tools)
    info = await component.get_service_info()

    assert info.status == "healthy"
    # Tools should have been reloaded
    assert len(component._tools) == 2
    assert component._tools[1].name == "new_action"


@pytest.mark.asyncio
async def test_component_disconnects_on_call_tool_failure():
  mock_read = MagicMock()
  mock_write = MagicMock()

  mock_session = AsyncMock()
  mock_init_result = type("FakeInitResult", (), {"serverInfo": FakeServerInfo("test_service", "1.4.0")})()
  mock_session.initialize = AsyncMock(return_value=mock_init_result)
  mock_session.list_tools = AsyncMock(return_value=FakeToolsList([]))
  mock_session.call_tool = AsyncMock(side_effect=RuntimeError("connection error"))

  class AsyncContextManagerMock:
    def __init__(self, return_value):
      self.return_value = return_value

    async def __aenter__(self):
      return self.return_value

    async def __aexit__(self, exc_type, exc_val, exc_tb):
      pass

  with (
    patch("akorin.core.components.streamable_http_client", return_value=AsyncContextManagerMock((mock_read, mock_write, None))),
    patch("akorin.core.components.ClientSession", return_value=AsyncContextManagerMock(mock_session)),
  ):
    component = OjoClient(Service.OREMI_OJO, "http://weather.test", httpx.AsyncClient(), None)

    # 1. Connect
    await component.connect()
    assert component._session == mock_session

    # 2. Call tool (which raises RuntimeError)
    from akorin.core.exceptions import ComponentUnavailable

    with pytest.raises(ComponentUnavailable):
      await component.call_tool("some_tool", {})

    # 3. Session should have been disconnected/reset
    assert component._session is None


@pytest.mark.asyncio
async def test_component_connect_cancellation_cleanup():
  mock_read = MagicMock()
  mock_write = MagicMock()

  mock_session = AsyncMock()
  mock_session.initialize = AsyncMock(side_effect=asyncio.CancelledError())

  streamable_client_aexit_called = False
  session_aexit_called = False

  class AsyncContextManagerMock:
    def __init__(self, return_value, on_exit):
      self.return_value = return_value
      self.on_exit = on_exit

    async def __aenter__(self):
      return self.return_value

    async def __aexit__(self, exc_type, exc_val, exc_tb):
      self.on_exit()

  def streamable_exit():
    nonlocal streamable_client_aexit_called
    streamable_client_aexit_called = True

  def session_exit():
    nonlocal session_aexit_called
    session_aexit_called = True

  with (
    patch(
      "akorin.core.components.streamable_http_client",
      return_value=AsyncContextManagerMock((mock_read, mock_write, None), streamable_exit)
    ),
    patch(
      "akorin.core.components.ClientSession",
      return_value=AsyncContextManagerMock(mock_session, session_exit)
    ),
  ):
    component = OjoClient(Service.OREMI_OJO, "http://weather.test", httpx.AsyncClient(), None)

    with pytest.raises(asyncio.CancelledError):
      await component.connect()

    # The contexts must be exited immediately during the cancellation propagation
    assert streamable_client_aexit_called is True
    assert session_aexit_called is True
    assert component._session is None
    assert component._exit_stack is None


@pytest.mark.asyncio
async def test_component_disconnect_base_exception_handling():
  component = OjoClient(Service.OREMI_OJO, "http://weather.test", httpx.AsyncClient(), None)

  # Set up exit stack to fail during aclose with a BaseExceptionGroup
  mock_exit_stack = AsyncMock()
  mock_exit_stack.aclose = AsyncMock(
    side_effect=BaseExceptionGroup("unhandled in task group", [RuntimeError("sub-exception")])
  )
  component._exit_stack = mock_exit_stack
  component._session = MagicMock()
  component._available = True

  # Call disconnect. It should catch BaseExceptionGroup and reset variables without propagating
  await component.disconnect()

  assert component._exit_stack is None
  assert component._session is None
  assert component._available is False
