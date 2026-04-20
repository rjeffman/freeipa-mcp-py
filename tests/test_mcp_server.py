# SPDX-License-Identifier: GPL-3.0-or-later
from unittest.mock import AsyncMock, patch

from mcp.types import Tool


async def test_list_tools_returns_six_static_tools():
    from freeipa_mcp.server import handle_list_tools

    tools = await handle_list_tools()
    names = [t.name for t in tools]
    assert "ping" in names
    assert "help" in names
    assert "create_ipaconf" in names
    assert "login" in names
    assert "healthcheck" in names
    assert "load_tools" in names


async def test_list_tools_includes_dynamic_after_load():
    from freeipa_mcp import server

    fake_tool = Tool(
        name="user-show",
        description="",
        inputSchema={"type": "object", "properties": {}},
    )
    original = server._dynamic_tools[:]
    server._dynamic_tools.append(fake_tool)
    try:
        tools = await server.handle_list_tools()
        assert any(t.name == "user-show" for t in tools)
    finally:
        server._dynamic_tools[:] = original


async def test_dispatch_ping_calls_ping_execute():
    with patch(
        "freeipa_mcp.server.ping.execute",
        new_callable=AsyncMock,
        return_value="---\npong\n---",
    ):
        from freeipa_mcp.server import _dispatch_tool

        result = await _dispatch_tool("ping", {})
    assert "pong" in result


async def test_dispatch_unknown_tool_returns_error():
    from freeipa_mcp.server import _dispatch_tool

    result = await _dispatch_tool("nonexistent_tool_xyz", {})
    assert "Error" in result or "Unknown" in result


async def test_dispatch_dynamic_tool():
    from freeipa_mcp import server

    server._dynamic_cmd_schemas["user-show"] = {
        "name": "user_show",
        "args": [{"name": "uid"}],
        "options": [],
    }
    with patch(
        "freeipa_mcp.server.dynamic.execute_command", return_value='{"uid": ["admin"]}'
    ):
        from freeipa_mcp.server import _dispatch_tool

        result = await _dispatch_tool("user-show", {"uid": "admin"})
    assert "admin" in result
    del server._dynamic_cmd_schemas["user-show"]


async def test_ping_tool_has_read_only_hint():
    from freeipa_mcp.server import PING_TOOL

    assert PING_TOOL.annotations is not None
    assert PING_TOOL.annotations.readOnlyHint is True


async def test_help_tool_has_read_only_hint():
    from freeipa_mcp.server import HELP_TOOL

    assert HELP_TOOL.annotations is not None
    assert HELP_TOOL.annotations.readOnlyHint is True


async def test_healthcheck_tool_has_read_only_hint():
    from freeipa_mcp.server import HEALTHCHECK_TOOL

    assert HEALTHCHECK_TOOL.annotations is not None
    assert HEALTHCHECK_TOOL.annotations.readOnlyHint is True
