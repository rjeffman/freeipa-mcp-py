# SPDX-License-Identifier: GPL-3.0-or-later
"""
GTK4 dialogs for secure vault password input and data display.

Ensures vault passwords and sensitive data are never exposed to AI agents.
"""

import base64
import subprocess
import sys
from pathlib import Path
from typing import Optional

_DISPLAY_DIALOG_SCRIPT = Path(__file__).parent / "_vault_display_dialog.py"
_PASSWORD_DIALOG_SCRIPT = Path(__file__).parent / "_vault_password_dialog.py"


def has_display() -> bool:
    """Check if a display is available for GTK dialogs."""
    import os

    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def get_vault_password(vault_name: str) -> Optional[str]:
    """
    Prompt for vault password using GTK4 dialog.

    Runs the GTK dialog in a subprocess to avoid conflicts with the
    MCP server's asyncio event loop.

    Args:
        vault_name: Name of the vault (shown in dialog)

    Returns:
        Password string if user provided one, None if cancelled

    Raises:
        ImportError: If PyGObject not available
        RuntimeError: If no display available
    """
    if not has_display():
        raise RuntimeError("No display available for password dialog")

    # Run GTK password dialog in subprocess
    result = subprocess.run(
        [sys.executable, str(_PASSWORD_DIALOG_SCRIPT), vault_name],
        capture_output=True,
        text=True,
    )

    if result.returncode == 3:
        detail = result.stderr.strip()
        msg = "GTK4 unavailable. Install python3-gobject."
        raise ImportError(f"{msg}\nDetail: {detail}" if detail else msg)

    if result.returncode == 2:
        # User cancelled
        return None

    if result.returncode != 0:
        detail = result.stderr.strip()
        raise RuntimeError(
            f"Password dialog failed: {detail}" if detail else "Dialog failed"
        )

    # Password is on stdout
    return result.stdout.strip()


def display_vault_data(vault_name: str, data: bytes) -> None:
    """
    Display vault data in GTK4 dialog with copy button.

    Runs the GTK dialog in a subprocess to avoid conflicts with the
    MCP server's asyncio event loop.

    Args:
        vault_name: Name of the vault
        data: Decrypted vault data bytes

    Raises:
        ImportError: If PyGObject not available
        RuntimeError: If no display available or dialog failed
    """
    if not has_display():
        raise RuntimeError("No display available for data dialog")

    # Encode data as base64 for safe subprocess transmission
    data_b64 = base64.b64encode(data).decode("ascii")

    # Run GTK dialog in subprocess
    result = subprocess.run(
        [sys.executable, str(_DISPLAY_DIALOG_SCRIPT), vault_name, data_b64],
        capture_output=True,
        text=True,
    )

    if result.returncode == 3:
        detail = result.stderr.strip()
        msg = "GTK4 unavailable. Install python3-gobject."
        raise ImportError(f"{msg}\nDetail: {detail}" if detail else msg)

    if result.returncode != 0:
        detail = result.stderr.strip()
        raise RuntimeError(
            f"Vault display dialog failed: {detail}" if detail else "Dialog failed"
        )


def get_password_from_file_or_dialog(
    arguments: dict, vault_name: str, operation: str = "vault"
) -> str:
    """
    Get password from file or GTK dialog - never from AI agent.

    Args:
        arguments: Command arguments (may contain 'password_file')
        vault_name: Vault name for dialog display
        operation: Operation description (e.g., "archive", "retrieve")

    Returns:
        Password string

    Raises:
        ValueError: If password_file not found and no display available
        RuntimeError: If user cancelled dialog
    """
    # First check for password file (secure method)
    if "password_file" in arguments:
        password_file = Path(arguments["password_file"])
        if not password_file.exists():
            raise FileNotFoundError(f"Password file not found: {password_file}")
        return password_file.read_text().rstrip("\n\r")

    # Try GTK dialog if display available
    if has_display():
        try:
            password = get_vault_password(vault_name)
            if password is None:
                raise RuntimeError(f"Vault {operation} cancelled by user")
            if not password:
                raise ValueError("Empty password provided")
            return password
        except ImportError:
            # GTK not available - fall through to error
            pass

    # No secure method available
    raise ValueError(
        "Password required: provide 'password_file' parameter "
        "or run with display for GUI prompt"
    )


def save_or_display_vault_data(arguments: dict, vault_name: str, data: bytes) -> str:
    """
    Save vault data to file or display in GTK dialog - never return to AI agent.

    Args:
        arguments: Command arguments (may contain 'out')
        vault_name: Vault name
        data: Decrypted vault data

    Returns:
        Success message (does NOT include actual data)

    Raises:
        ValueError: If no output method available
    """
    # First check for output file (secure method)
    if "out" in arguments:
        out_file = Path(arguments["out"])
        out_file.write_bytes(data)
        return f"Vault data saved to {out_file} ({len(data)} bytes)"

    # Try GTK dialog if display available
    if has_display():
        try:
            display_vault_data(vault_name, data)
            return f"Vault data displayed in dialog ({len(data)} bytes)"
        except (ImportError, RuntimeError) as e:
            # GTK not available or dialog failed - fall through to error
            # Include original error in final message for debugging
            raise ValueError(
                f"Output required: provide 'out' parameter for file "
                f"or run with display for GUI. Dialog failed: {e}"
            ) from e

    # No secure method available
    raise ValueError(
        "Output required: provide 'out' parameter for file "
        "or run with display for GUI. "
        "No display detected (DISPLAY or WAYLAND_DISPLAY not set)."
    )
