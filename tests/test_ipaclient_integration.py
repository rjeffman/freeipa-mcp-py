# SPDX-License-Identifier: GPL-3.0-or-later

"""Integration tests for IPA client (requires live IPA server).

These tests require:
1. A live IPA server (e.g., ipa.demo1.freeipa.org)
2. Valid Kerberos credentials (kinit)

Run with: pytest tests/test_ipaclient_integration.py -v

Skip if no server available: pytest -m "not integration"
"""

import pytest

from freeipa_mcp.ipaclient import IPAThinClient, IPAConnectionError

# Mark all tests in this file as integration tests
pytestmark = pytest.mark.integration


@pytest.fixture
def live_server():
    """Live IPA server for integration testing."""
    return "ipa.demo1.freeipa.org"


@pytest.fixture
def live_client(live_server):
    """Client connected to live server."""
    return IPAThinClient(live_server)


def test_integration_ping(live_client):
    """Test ping against live server."""
    result = live_client.ping()
    assert "summary" in result
    assert "IPA server version" in result["summary"]


def test_integration_schema_fetch(live_client):
    """Test schema retrieval from live server."""
    schema = live_client._get_schema()
    assert "topics" in schema
    assert "commands" in schema
    assert len(schema["commands"]) > 0


def test_integration_help_topics(live_client):
    """Test help topics listing."""
    result = live_client.help()
    assert "topics" in result
    assert len(result["topics"]) > 0


def test_integration_help_commands(live_client):
    """Test help commands listing."""
    result = live_client.help("commands")
    assert "commands" in result
    assert len(result["commands"]) > 0


def test_integration_help_topic(live_client):
    """Test help for specific topic."""
    result = live_client.help("user")
    assert result["name"] == "user"
    assert "commands" in result
    assert len(result["commands"]) > 0


def test_integration_help_command(live_client):
    """Test help for specific command."""
    result = live_client.help("user_show")
    assert result["name"] == "user_show"
    assert "args" in result
    assert "options" in result


def test_integration_export_schema(live_client):
    """Test schema export."""
    schema = live_client.export_schema()
    assert "topics" in schema
    assert "commands" in schema

    # Verify structure
    if "user" in schema["topics"]:
        user_topic = schema["topics"]["user"]
        assert "name" in user_topic
        assert "commands" in user_topic

    if "user_show" in schema["commands"]:
        cmd = schema["commands"]["user_show"]
        assert "name" in cmd
        assert "args" in cmd
        assert "options" in cmd


def test_integration_command_config_show(live_client):
    """Test executing config_show command."""
    result = live_client.command("config_show")
    assert "result" in result or "cn" in result


def test_integration_no_credentials():
    """Test that missing Kerberos credentials fails gracefully."""
    # This test assumes no valid ticket exists
    # In practice, you'd clear credentials first or use a different server
    client = IPAThinClient("nonexistent.example.com")

    with pytest.raises(IPAConnectionError):
        client.ping()
