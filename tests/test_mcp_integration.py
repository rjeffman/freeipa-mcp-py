# SPDX-License-Identifier: GPL-3.0-or-later
"""Integration smoke tests for the MCP server tools.

Requires:
- A live FreeIPA server at FREEIPA_TEST_SERVER env var (default: ipa.demo1.freeipa.org)
- A valid Kerberos ticket: kinit admin@DEMO1.FREEIPA.ORG
"""

import os

import pytest

TEST_SERVER = os.environ.get("FREEIPA_TEST_SERVER", "ipa.demo1.freeipa.org")


@pytest.mark.integration
async def test_create_ipaconf_and_ping():
    from freeipa_mcp.tools.create_ipaconf import execute as create_execute
    from freeipa_mcp.tools.ping import execute as ping_execute

    result = await create_execute(server_hostname=TEST_SERVER)
    assert "configured" in result.lower()
    assert "CA certificate" in result

    ping_result = await ping_execute()
    assert "IPA server version" in ping_result


@pytest.mark.integration
async def test_load_dynamic_tools():
    from freeipa_mcp.tools.common import save_server_config
    from freeipa_mcp.tools.dynamic import build_all_tools

    save_server_config(TEST_SERVER)
    tools, _ = build_all_tools()
    assert len(tools) > 50
    tool_names = [t.name for t in tools]
    assert "user-find" in tool_names
    assert "user-show" in tool_names
    assert "ping" not in tool_names


@pytest.mark.integration
async def test_dynamic_find_tool_is_read_only():
    from freeipa_mcp.tools.common import save_server_config
    from freeipa_mcp.tools.dynamic import build_all_tools

    save_server_config(TEST_SERVER)
    tools, _ = build_all_tools()
    find_tools = [t for t in tools if t.name.endswith("-find")]
    show_tools = [t for t in tools if t.name.endswith("-show")]
    assert find_tools, "No *-find tools found"
    assert show_tools, "No *-show tools found"
    for t in find_tools + show_tools:
        assert t.annotations is not None, f"{t.name} has no annotations"
        assert t.annotations.readOnlyHint is True, f"{t.name} should be read-only"
        assert t.annotations.destructiveHint is False, (
            f"{t.name} should not be destructive"
        )


@pytest.mark.integration
async def test_help_topics():
    from freeipa_mcp.tools.common import save_server_config
    from freeipa_mcp.tools.help import execute

    save_server_config(TEST_SERVER)
    result = await execute(subject="topics")
    assert "user" in result.lower()


@pytest.mark.integration
async def test_execute_user_find():
    import json

    from freeipa_mcp.tools.common import save_server_config
    from freeipa_mcp.tools.dynamic import build_all_tools, execute_command

    save_server_config(TEST_SERVER)
    _, schemas = build_all_tools()
    result = execute_command("user-find", {}, schemas["user-find"])
    data = json.loads(result)
    assert "count" in data
