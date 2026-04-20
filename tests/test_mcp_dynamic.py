# SPDX-License-Identifier: GPL-3.0-or-later
import json
from unittest.mock import MagicMock, patch

MOCK_CMD_SHOW = {
    "name": "user_show",
    "summary": "Display information about a user.",
    "doc": "Display information about a user.\n\nReturns user attributes.",
    "args": [
        {
            "name": "uid",
            "cli_name": "login",
            "type": "str",
            "required": True,
            "doc": "User login",
        },
    ],
    "options": [
        {
            "name": "all",
            "cli_name": "all",
            "type": "bool",
            "required": False,
            "doc": "Retrieve all attributes",
            "default": False,
        },
        {
            "name": "sizelimit",
            "cli_name": "sizelimit",
            "type": "int",
            "required": False,
            "doc": "",
        },
    ],
}

MOCK_CMD_FIND = {
    "name": "user_find",
    "summary": "Search for users.",
    "doc": "Search for users.",
    "args": [],
    "options": [
        {
            "name": "criteria",
            "cli_name": "criteria",
            "type": "str",
            "required": False,
            "doc": "Search criteria",
        },
        {
            "name": "sizelimit",
            "cli_name": "sizelimit",
            "type": "int",
            "required": False,
            "doc": "",
        },
    ],
}

MOCK_CMD_ADD = {
    "name": "user_add",
    "summary": "Add a new user.",
    "doc": "Add a new user.",
    "args": [
        {
            "name": "uid",
            "cli_name": "login",
            "type": "str",
            "required": True,
            "doc": "User login",
        },
    ],
    "options": [
        {
            "name": "givenname",
            "cli_name": "first",
            "type": "str",
            "required": True,
            "doc": "First name",
        },
    ],
}


def test_is_read_only_find():
    from freeipa_mcp.tools.dynamic import is_read_only

    assert is_read_only("user_find") is True


def test_is_read_only_show():
    from freeipa_mcp.tools.dynamic import is_read_only

    assert is_read_only("group_show") is True


def test_is_read_only_add_is_false():
    from freeipa_mcp.tools.dynamic import is_read_only

    assert is_read_only("user_add") is False


def test_build_command_input_schema_args_are_required():
    from freeipa_mcp.tools.dynamic import build_command_input_schema

    schema = build_command_input_schema(MOCK_CMD_SHOW)
    assert schema["type"] == "object"
    assert "uid" in schema["properties"]
    assert schema["properties"]["uid"]["type"] == "string"
    assert "uid" in schema["required"]


def test_build_command_input_schema_options_not_required():
    from freeipa_mcp.tools.dynamic import build_command_input_schema

    schema = build_command_input_schema(MOCK_CMD_SHOW)
    assert "all" in schema["properties"]
    assert schema["properties"]["all"]["type"] == "boolean"
    assert "all" not in schema.get("required", [])


def test_build_command_input_schema_required_option_is_required():
    from freeipa_mcp.tools.dynamic import build_command_input_schema

    schema = build_command_input_schema(MOCK_CMD_ADD)
    assert "givenname" in schema["required"]


def test_build_tool_show_is_read_only():
    from freeipa_mcp.tools.dynamic import build_tool

    tool = build_tool(MOCK_CMD_SHOW)
    assert tool.name == "user-show"
    assert tool.annotations is not None
    assert tool.annotations.readOnlyHint is True
    assert tool.annotations.destructiveHint is False


def test_build_tool_add_is_destructive():
    from freeipa_mcp.tools.dynamic import build_tool

    tool = build_tool(MOCK_CMD_ADD)
    assert tool.name == "user-add"
    assert tool.annotations is not None
    assert tool.annotations.readOnlyHint is False
    assert tool.annotations.destructiveHint is True


def test_execute_command_separates_positional_and_keyword():
    mock_client = MagicMock()
    mock_client.command.return_value = {"result": {"uid": ["admin"]}, "count": 1}
    with patch("freeipa_mcp.tools.dynamic.get_client", return_value=mock_client):
        from freeipa_mcp.tools.dynamic import execute_command

        result = execute_command(
            "user-show", {"uid": "admin", "all": True}, MOCK_CMD_SHOW
        )
    mock_client.command.assert_called_once_with("user_show", "admin", all=True)
    assert json.loads(result)["count"] == 1


def test_execute_command_no_positional_args():
    mock_client = MagicMock()
    mock_client.command.return_value = {"result": [], "count": 0}
    with patch("freeipa_mcp.tools.dynamic.get_client", return_value=mock_client):
        from freeipa_mcp.tools.dynamic import execute_command

        execute_command(
            "user-find", {"criteria": "john", "sizelimit": 50}, MOCK_CMD_FIND
        )
    mock_client.command.assert_called_once_with(
        "user_find", criteria="john", sizelimit=50
    )


def test_build_all_tools_skips_ping():
    mock_client = MagicMock()
    mock_client.export_schema.return_value = {
        "commands": {
            "ping": {
                "name": "ping",
                "summary": "",
                "doc": "",
                "args": [],
                "options": [],
            },
            "user_show": MOCK_CMD_SHOW,
        }
    }
    with patch("freeipa_mcp.tools.dynamic.get_client", return_value=mock_client):
        from freeipa_mcp.tools.dynamic import build_all_tools

        tools, _ = build_all_tools()
    tool_names = [t.name for t in tools]
    assert "ping" not in tool_names
    assert "user-show" in tool_names
