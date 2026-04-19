# SPDX-License-Identifier: GPL-3.0-or-later

"""Pytest configuration and shared fixtures."""

import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def mock_server():
    """Mock IPA server hostname."""
    return "ipa.example.com"


@pytest.fixture
def mock_schema():
    """Mock IPA schema data."""
    return {
        "topics": {
            "user": {
                "name": "user",
                "doc": "Users\n\nManage user accounts.",
            },
            "group": {
                "name": "group",
                "doc": "Groups\n\nManage user groups.",
            },
        },
        "commands": {
            "user_show": {
                "name": "user_show",
                "topic": "user",
                "full_name": "user_show",
                "doc": (
                    "Display information about a user.\n\n"
                    "Shows detailed user attributes."
                ),
                "summary": "Display information about a user",
                "params": [
                    {
                        "name": "uid",
                        "cli_name": "login",
                        "type": "Str",
                        "required": True,
                        "label": "User login",
                        "doc": "User login",
                    },
                    {
                        "name": "all",
                        "cli_name": "all",
                        "type": "Flag",
                        "required": False,
                        "label": "Retrieve all attributes",
                        "doc": "Retrieve and print all attributes",
                        "default": False,
                    },
                    {
                        "name": "version",
                        "type": "Str",
                        "required": False,
                        "exclude": "webui",
                    },
                ],
            },
            "user_find": {
                "name": "user_find",
                "topic": "user",
                "full_name": "user_find",
                "doc": "Search for users.",
                "summary": "Search for users",
                "params": [
                    {
                        "name": "criteria",
                        "cli_name": "criteria",
                        "type": "Str",
                        "required": False,
                        "label": "Search criteria",
                        "doc": "Search criteria",
                    },
                    {
                        "name": "sizelimit",
                        "type": "Int",
                        "required": False,
                        "default": 100,
                    },
                    {
                        "name": "version",
                        "type": "Str",
                        "required": False,
                        "exclude": "webui",
                    },
                ],
            },
            "group_show": {
                "name": "group_show",
                "topic": "group",
                "full_name": "group_show",
                "doc": "Display information about a group.",
                "summary": "Display information about a group",
                "params": [
                    {
                        "name": "cn",
                        "cli_name": "group-name",
                        "type": "Str",
                        "required": True,
                        "label": "Group name",
                        "doc": "Group name",
                    },
                    {
                        "name": "version",
                        "type": "Str",
                        "required": False,
                        "exclude": "webui",
                    },
                ],
            },
        },
    }


@pytest.fixture
def mock_ping_response():
    """Mock ping command response."""
    return {
        "result": {
            "summary": "IPA server version 4.9.8. API version 2.251",
        },
        "error": None,
    }


@pytest.fixture
def mock_ca_cert():
    """Mock CA certificate file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".crt", delete=False) as f:
        f.write("-----BEGIN CERTIFICATE-----\n")
        f.write("MOCK CERTIFICATE DATA\n")
        f.write("-----END CERTIFICATE-----\n")
        cert_path = f.name

    yield cert_path

    # Cleanup
    Path(cert_path).unlink(missing_ok=True)


@pytest.fixture(autouse=True)
def mock_get_ca_cert(mock_ca_cert, monkeypatch):
    """Automatically mock CA cert downloads for all tests.

    This prevents tests from making real HTTP requests to download
    CA certificates during client initialization.
    """

    def _mock_get_ca_cert(self):
        return mock_ca_cert

    monkeypatch.setattr("freeipa_mcp.ipaclient.IPAThinClient._get_ca_cert", _mock_get_ca_cert)
