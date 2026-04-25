# SPDX-License-Identifier: GPL-3.0-or-later
import json
from typing import Callable, Dict, Optional

from mcp.types import Tool, ToolAnnotations

from .common import get_client, ipa_type_to_json_schema, to_api_name, to_cli_name

_SKIP_COMMANDS = {"ping"}

# Registry for custom command executors
_custom_executors: Dict[str, Callable[[dict], str]] = {}


def is_read_only(api_name: str) -> bool:
    return "_find" in api_name or "_show" in api_name


def register_custom_executor(cli_name: str, executor: Callable[[dict], str]) -> None:
    """
    Register a custom executor function for a command.

    Args:
        cli_name: CLI command name (e.g., "vault-archive")
        executor: Function that takes arguments dict and returns string result
    """
    _custom_executors[cli_name] = executor


def get_custom_executor(cli_name: str) -> Optional[Callable[[dict], str]]:
    """
    Get custom executor for a command if registered.

    Args:
        cli_name: CLI command name

    Returns:
        Custom executor function, or None if not registered
    """
    return _custom_executors.get(cli_name)


def build_command_input_schema(cmd: dict) -> dict:
    properties: dict = {}
    required: list[str] = []

    for param in cmd["args"]:
        schema = {
            **ipa_type_to_json_schema(param["type"]),
            "description": param.get("doc", ""),
        }
        properties[param["name"]] = schema
        if param.get("required", True):
            required.append(param["name"])

    for param in cmd["options"]:
        schema = {
            **ipa_type_to_json_schema(param["type"]),
            "description": param.get("doc", ""),
        }
        if "default" in param:
            schema["default"] = param["default"]
        properties[param["name"]] = schema
        if param.get("required", False):
            required.append(param["name"])

    result: dict = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        result["required"] = required
    return result


def build_tool(cmd: dict) -> Tool:
    api_name = cmd["name"]
    read_only = is_read_only(api_name)
    return Tool(
        name=to_cli_name(api_name),
        description=cmd.get("doc", cmd.get("summary", "")),
        inputSchema=build_command_input_schema(cmd),
        annotations=ToolAnnotations(
            readOnlyHint=read_only,
            destructiveHint=not read_only,
            idempotentHint=read_only,
        ),
    )


def _build_vault_tools() -> list[Tool]:
    """Build client-side vault tools with custom executors."""
    return [
        Tool(
            name="vaultconfig-show",
            description=(
                "Display KRA configuration (transport cert and wrapping algorithm)"
            ),
            inputSchema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            annotations=ToolAnnotations(
                readOnlyHint=True, destructiveHint=False, idempotentHint=True
            ),
        ),
        Tool(
            name="vault-add",
            description="Create a new vault with client-side encryption support",
            inputSchema={
                "type": "object",
                "properties": {
                    "cn": {
                        "type": "string",
                        "description": "Vault name",
                    },
                    "ipavaulttype": {
                        "type": "string",
                        "enum": ["standard", "symmetric", "asymmetric"],
                        "description": "Vault type (default: standard)",
                    },
                    "ipavaultpublickey": {
                        "type": "string",
                        "description": "Public key (PEM) for asymmetric vaults",
                    },
                    "description": {
                        "type": "string",
                        "description": "Vault description",
                    },
                    "user": {"type": "string", "description": "User vault owner"},
                    "shared": {"type": "boolean", "description": "Shared vault"},
                    "service": {"type": "string", "description": "Service vault"},
                },
                "required": ["cn"],
                "additionalProperties": False,
            },
            annotations=ToolAnnotations(
                readOnlyHint=False, destructiveHint=False, idempotentHint=False
            ),
        ),
        Tool(
            name="vault-mod",
            description="Modify vault metadata",
            inputSchema={
                "type": "object",
                "properties": {
                    "cn": {"type": "string", "description": "Vault name"},
                    "description": {
                        "type": "string",
                        "description": "New description",
                    },
                    "user": {"type": "string", "description": "User vault owner"},
                    "shared": {"type": "boolean", "description": "Shared vault"},
                    "service": {"type": "string", "description": "Service vault"},
                },
                "required": ["cn"],
                "additionalProperties": False,
            },
            annotations=ToolAnnotations(
                readOnlyHint=False, destructiveHint=False, idempotentHint=False
            ),
        ),
        Tool(
            name="vault-archive",
            description=(
                "Archive data into vault with client-side encryption. "
                "Password must be provided via password_file (never directly). "
                "GTK dialog prompts if no password_file and display available."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "cn": {"type": "string", "description": "Vault name"},
                    "in": {
                        "type": "string",
                        "description": "Input file path (max 1 MiB)",
                    },
                    "password_file": {
                        "type": "string",
                        "description": "File containing vault password",
                    },
                    "user": {"type": "string", "description": "User vault owner"},
                    "shared": {"type": "boolean", "description": "Shared vault"},
                    "service": {"type": "string", "description": "Service vault"},
                },
                "required": ["cn", "in"],
                "additionalProperties": False,
            },
            annotations=ToolAnnotations(
                readOnlyHint=False, destructiveHint=False, idempotentHint=False
            ),
        ),
        Tool(
            name="vault-retrieve",
            description=(
                "Retrieve and decrypt vault data. Password via password_file only. "
                "Data saved to 'out' file or displayed in GTK dialog. "
                "NEVER returns sensitive data to AI agent."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "cn": {"type": "string", "description": "Vault name"},
                    "out": {
                        "type": "string",
                        "description": (
                            "Output file path (optional, uses GUI if omitted)"
                        ),
                    },
                    "password_file": {
                        "type": "string",
                        "description": "File containing vault password",
                    },
                    "private_key_file": {
                        "type": "string",
                        "description": "Private key file for asymmetric vaults",
                    },
                    "user": {"type": "string", "description": "User vault owner"},
                    "shared": {"type": "boolean", "description": "Shared vault"},
                    "service": {"type": "string", "description": "Service vault"},
                },
                "required": ["cn"],
                "additionalProperties": False,
            },
            annotations=ToolAnnotations(
                readOnlyHint=True, destructiveHint=False, idempotentHint=True
            ),
        ),
    ]


def build_all_tools() -> tuple[list[Tool], dict[str, dict]]:
    """Return (Tool list, {cli_name: cmd_dict}) from the live server schema."""
    client = get_client()
    schema = client.export_schema()
    tools: list[Tool] = []
    cmd_schemas: dict[str, dict] = {}
    for api_name, cmd in schema.get("commands", {}).items():
        cli_name = to_cli_name(api_name)
        if cli_name in _SKIP_COMMANDS:
            continue
        tools.append(build_tool(cmd))
        cmd_schemas[cli_name] = cmd

    # Add client-side vault tools
    vault_tools = _build_vault_tools()
    tools.extend(vault_tools)
    # Add dummy schemas so vault commands are recognized in execute_command
    for tool in vault_tools:
        cmd_schemas[tool.name] = {"name": tool.name, "args": [], "options": []}

    return tools, cmd_schemas


def execute_command(cli_name: str, arguments: dict, cmd_schema: dict) -> str:
    """Execute a dynamic IPA command and return pretty-printed JSON."""
    # Check for custom executor first
    custom_executor = get_custom_executor(cli_name)
    if custom_executor:
        return custom_executor(arguments)

    # Default execution path
    api_name = to_api_name(cli_name)
    arg_names = {a["name"] for a in cmd_schema["args"]}
    positional = [
        arguments[a["name"]] for a in cmd_schema["args"] if a["name"] in arguments
    ]
    options = {k: v for k, v in arguments.items() if k not in arg_names}
    client = get_client()
    result = client.command(api_name, *positional, **options)
    return json.dumps(result, indent=2, default=str)
