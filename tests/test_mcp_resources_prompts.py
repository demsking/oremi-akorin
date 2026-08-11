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
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import httpx2
import mcp_types as t
import pytest

from akorin.components.ojo import OjoClient
from akorin.core.service import Service
from akorin.core.tools import GetPromptTool
from akorin.core.tools import ListPromptsTool
from akorin.core.tools import ListResourcesTool
from akorin.core.tools import ReadResourceTool


class FakeServerInfo:
  def __init__(self, name, version):
    self.name = name
    self.version = version


class FakeToolsList:
  def __init__(self, tools):
    self.tools = tools


class AsyncContextManagerMock:
  def __init__(self, return_value):
    self.return_value = return_value

  async def __aenter__(self):
    return self.return_value

  async def __aexit__(self, exc_type, exc_val, exc_tb):
    pass


@pytest.mark.asyncio
async def test_component_client_discovers_resources_and_prompts():
  mock_read = MagicMock()
  mock_write = MagicMock()

  mock_session = AsyncMock()

  # Set up capabilities
  capabilities = t.ServerCapabilities(
    resources=t.ResourcesCapability(subscribe=True, list_changed=True),
    prompts=t.PromptsCapability(list_changed=True),
  )
  mock_init_result = type(
    "FakeInitResult",
    (),
    {
      "server_info": FakeServerInfo("weather", "1.4.0"),
      "capabilities": capabilities,
    },
  )()
  mock_session.initialize = AsyncMock(return_value=mock_init_result)

  # Tools
  mock_session.list_tools = AsyncMock(return_value=FakeToolsList([]))

  # Resources
  mock_resource = t.Resource(
    uri="device://list",
    name="Device List",
    description="All smart devices",
    mime_type="application/json",
  )
  mock_session.list_resources = AsyncMock(return_value=t.ListResourcesResult(resources=[mock_resource]))

  # Prompts
  mock_arg = t.PromptArgument(name="limit", description="max count", required=False)
  mock_prompt = t.Prompt(
    name="summarize",
    title="Summarize status",
    description="Summarize device status",
    arguments=[mock_arg],
  )
  mock_session.list_prompts = AsyncMock(return_value=t.ListPromptsResult(prompts=[mock_prompt]))

  with (
    patch("akorin.core.components.streamable_http_client", return_value=AsyncContextManagerMock((mock_read, mock_write, None))),
    patch("akorin.core.components.ClientSession", return_value=AsyncContextManagerMock(mock_session)),
  ):
    component = OjoClient(Service.OREMI_OJO, "http://weather.test", httpx2.AsyncClient(), None)

    # Connect
    await component.connect()
    assert component._session == mock_session
    assert len(component._resources) == 1
    assert component._resources[0].name == "Device List"
    assert len(component._prompts) == 1
    assert component._prompts[0].name == "summarize"

    # Getters
    res = await component.get_resources()
    assert len(res) == 1

    prompts = await component.get_prompts()
    assert len(prompts) == 1

    # Read Resource
    text_content = t.TextResourceContents(uri="device://list", text='{"ok": true}')
    mock_session.read_resource = AsyncMock(return_value=t.ReadResourceResult(contents=[text_content]))
    read_res = await component.read_resource("device://list")
    assert read_res.contents[0].text == '{"ok": true}'
    mock_session.read_resource.assert_called_with("device://list")

    # Get Prompt
    msg = t.PromptMessage(role="user", content=t.TextContent(type="text", text="summarize standard"))
    mock_session.get_prompt = AsyncMock(return_value=t.GetPromptResult(description="desc", messages=[msg]))
    prompt_res = await component.get_prompt("summarize", {"limit": "5"})
    assert prompt_res.messages[0].content.text == "summarize standard"
    mock_session.get_prompt.assert_called_with("summarize", {"limit": "5"})

    # Disconnect clears
    await component.disconnect()
    assert component._session is None
    assert len(component._resources) == 0
    assert len(component._prompts) == 0


@pytest.mark.asyncio
async def test_resource_and_prompt_tools_execution():
  # Setup fake component handlers
  class MockHandler:
    def __init__(self):
      self.resources = [
        t.Resource(
          uri="device://list",
          name="Device List",
          description="All smart devices",
          mime_type="application/json",
        )
      ]
      self.prompts = [
        t.Prompt(
          name="summarize",
          title="Summarize status",
          description="Summarize device status",
          arguments=[t.PromptArgument(name="limit", description="max count", required=False)],
        )
      ]

    async def get_resources(self):
      return self.resources

    async def read_resource(self, uri):
      if uri == "device://list":
        return t.ReadResourceResult(contents=[t.TextResourceContents(uri=uri, text='{"ok": true}')])
      raise ValueError("not found")

    async def get_prompts(self):
      return self.prompts

    async def get_prompt(self, name, arguments=None):
      if name == "summarize":
        msg = t.PromptMessage(role="user", content=t.TextContent(type="text", text=f"summarize limit {arguments.get('limit')}"))
        return t.GetPromptResult(description="desc", messages=[msg])
      raise ValueError("not found")

  handlers = {Service.OREMI_OJO: MockHandler()}

  # 1. Test ListResourcesTool
  list_res_tool = ListResourcesTool(handlers)
  res_list = await list_res_tool.execute({}, {})
  assert res_list.name == "list_resources"
  assert len(res_list.data["resources"]) == 1
  assert res_list.data["resources"][0]["uri"] == "device://list"
  assert res_list.data["resources"][0]["service"] == "ojo"

  # 2. Test ReadResourceTool
  read_res_tool = ReadResourceTool(handlers)
  res_content = await read_res_tool.execute({"uri": "device://list"}, {})
  assert res_content.name == "read_resource"
  assert res_content.data["uri"] == "device://list"
  assert res_content.data["contents"] == [{"ok": True}]

  # 3. Test ListPromptsTool
  list_prompts_tool = ListPromptsTool(handlers)
  prompts_list = await list_prompts_tool.execute({}, {})
  assert prompts_list.name == "list_prompts"
  assert len(prompts_list.data["prompts"]) == 1
  assert prompts_list.data["prompts"][0]["name"] == "summarize"
  assert prompts_list.data["prompts"][0]["arguments"][0]["name"] == "limit"

  # 4. Test GetPromptTool
  get_prompt_tool = GetPromptTool(handlers)
  prompt_val = await get_prompt_tool.execute({"name": "summarize", "arguments": {"limit": 10}}, {})
  assert prompt_val.name == "summarize"
  assert prompt_val.data["messages"][0]["role"] == "user"
  assert prompt_val.data["messages"][0]["content"] == "summarize limit 10"
