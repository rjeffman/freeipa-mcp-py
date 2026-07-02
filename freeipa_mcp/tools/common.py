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
    # Create config directory and file with secure permissions (mode 0700/0600)
    old_umask = os.umask(0o077)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(hostname)
    finally:
        os.umask(old_umask)


def load_server_config() -> str | None:
    path = get_server_config_path()
    if path.exists():
        return path.read_text().strip() or None
    return None


def get_client(ccache_path: str | None = None) -> IPAThinClient:
    hostname = load_server_config()
    if not hostname:
        raise RuntimeError(
            "No FreeIPA server configured. Use the create_ipaconf tool first."
        )
    return IPAThinClient(hostname, ccache_path=ccache_path)


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


def validate_file_path(path: str | Path, allow_write: bool = False) -> Path:
    """
    Validate file path is safe and within user's home directory.

    Security checks:
    - Path must resolve to a location under user's home directory
    - Symlinks are not allowed (prevents symlink attacks)
    - For read operations: file must exist
    - For write operations: parent directory must exist

    Args:
        path: File path to validate (string or Path object)
        allow_write: If True, validate for write access (file need not exist)

    Returns:
        Resolved absolute Path object

    Raises:
        ValueError: If path is unsafe (outside home, symlink, etc.)
        FileNotFoundError: If path doesn't exist (read mode only)
    """
    path_obj = Path(path)
    home = Path.home()

    # Resolve to absolute path (follows symlinks)
    try:
        resolved = path_obj.resolve(strict=False)
    except (OSError, RuntimeError) as e:
        raise ValueError(f"Invalid path: {path}") from e

    # Check if resolved path is under home directory
    try:
        resolved.relative_to(home)
    except ValueError:
        raise ValueError(
            f"Path must be under home directory ({home}): {path}"
        ) from None

    # Prevent symlink attacks - check if any component is a symlink
    # that points outside home directory
    current = path_obj.absolute()
    while current != current.parent:
        if current.is_symlink():
            target = current.readlink()
            if target.is_absolute():
                try:
                    target.relative_to(home)
                except ValueError:
                    raise ValueError(
                        f"Symlink points outside home directory: {current} -> {target}"
                    ) from None
        current = current.parent

    # For read operations, file must exist
    if not allow_write and not resolved.exists():
        raise FileNotFoundError(f"File not found: {path}")

    # For write operations, parent directory must exist
    if allow_write and not resolved.parent.exists():
        raise ValueError(f"Parent directory does not exist: {resolved.parent}")

    return resolved
