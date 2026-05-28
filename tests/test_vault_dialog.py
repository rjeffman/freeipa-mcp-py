# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for vault dialog security."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from freeipa_mcp.tools._vault_dialog import (
    display_vault_data,
    save_or_display_vault_data,
)


def test_display_vault_data_passes_data_via_stdin_not_argv():
    """
    Security test: verify vault data is passed via stdin, not command-line args.

    CRITICAL: Command-line arguments are visible in process table via ps/proc.
    Sensitive vault data MUST be passed via stdin to prevent exposure.
    """
    vault_name = "test-vault"
    sensitive_data = b"secret password 123"

    with (
        patch("freeipa_mcp.tools._vault_dialog.has_display", return_value=True),
        patch("subprocess.run") as mock_run,
    ):
        # Mock successful subprocess execution
        mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")

        # Call the function
        display_vault_data(vault_name, sensitive_data)

        # Verify subprocess.run was called
        assert mock_run.called
        call_args = mock_run.call_args

        # Check that command-line arguments do NOT contain the sensitive data
        cmd = call_args[0][0]  # First positional argument is the command list
        # Command should only have: [python, script_path, vault_name]
        # NOT the data!
        assert len(cmd) == 3, (
            f"Expected 3 args (python, script, vault_name), got {len(cmd)}: {cmd}"
        )
        assert vault_name in cmd, "vault_name should be in command args"

        # Verify data is NOT in any command-line argument
        for arg in cmd:
            assert b"secret" not in str(arg).encode()
            assert b"password" not in str(arg).encode()

        # Verify data IS passed via stdin
        kwargs = call_args[1]  # Keyword arguments
        assert "input" in kwargs, "Data should be passed via 'input' parameter (stdin)"
        assert kwargs["input"] == sensitive_data, (
            "stdin should contain the sensitive data"
        )


@pytest.fixture
def temp_home(monkeypatch, tmp_path):
    """Create a temporary home directory for testing."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    return home


def test_save_or_display_vault_data_does_not_leak_metadata(temp_home):
    """
    Security test: verify return message doesn't leak vault metadata to AI agent.

    CRITICAL: AI agent should not receive any metadata about vault contents,
    including data size, which could be used for inference attacks.
    """
    vault_name = "test-vault"
    sensitive_data = b"secret password 123"
    output_file = temp_home / "output.txt"

    # Test file output path
    arguments = {"out": str(output_file)}
    result = save_or_display_vault_data(arguments, vault_name, sensitive_data)

    # Verify file was written correctly
    assert output_file.read_bytes() == sensitive_data

    # Verify result message does NOT contain data size
    assert str(len(sensitive_data)) not in result, (
        f"Data size leaked in result message: {result}"
    )
    assert "bytes" not in result.lower(), (
        f"Byte count leaked in result message: {result}"
    )
    assert "19" not in result, "Specific data size leaked"

    # Verify result is a success message without metadata
    assert "saved" in result.lower() or "success" in result.lower()


def test_display_vault_data_does_not_leak_metadata():
    """
    Security test: verify display function doesn't leak metadata to AI agent.

    CRITICAL: When displaying vault data in dialog, the AI agent should not
    receive any metadata about the vault contents.
    """
    vault_name = "test-vault"
    sensitive_data = b"secret password 123"

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stderr=b"", stdout=b"")

        # Mock has_display to return True
        with patch("freeipa_mcp.tools._vault_dialog.has_display", return_value=True):
            from freeipa_mcp.tools._vault_dialog import save_or_display_vault_data

            result = save_or_display_vault_data({}, vault_name, sensitive_data)

            # Verify result message does NOT contain data size
            assert str(len(sensitive_data)) not in result, (
                f"Data size leaked in result message: {result}"
            )
            assert "bytes" not in result.lower(), (
                f"Byte count leaked in result message: {result}"
            )
            assert "19" not in result, "Specific data size leaked"

            # Verify result is a success message without metadata
            assert "displayed" in result.lower() or "success" in result.lower()
