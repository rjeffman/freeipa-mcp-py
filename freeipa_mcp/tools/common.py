# SPDX-License-Identifier: GPL-3.0-or-later
import os
from pathlib import Path

from freeipa_mcp.ipaclient import IPAThinClient


def get_cache_dir() -> Path:
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".cache"
    return base / "freeipa-mcp-py"


def get_server_config_path() -> Path:
    return get_cache_dir() / "config" / "server"


def save_server_config(hostname: str) -> None:
    path = get_server_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(hostname)


def load_server_config() -> str | None:
    path = get_server_config_path()
    if path.exists():
        return path.read_text().strip() or None
    return None


def get_client() -> IPAThinClient:
    hostname = load_server_config()
    if not hostname:
        raise RuntimeError(
            "No FreeIPA server configured. Use the create_ipaconf tool first."
        )
    return IPAThinClient(hostname)


def to_cli_name(api_name: str) -> str:
    return api_name.replace("_", "-")


def to_api_name(cli_name: str) -> str:
    return cli_name.replace("-", "_")


def ipa_type_to_json_schema(ipa_type: str) -> dict:
    return {
        "int": {"type": "integer"},
        "bool": {"type": "boolean"},
        "list": {"type": "array", "items": {"type": "string"}},
        "dict": {"type": "object"},
    }.get(ipa_type, {"type": "string"})
