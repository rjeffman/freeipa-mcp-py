"""Integration tests for help_markdown functionality.

These tests require:
1. A live IPA server (e.g., ipa.demo1.freeipa.org)
2. Valid Kerberos credentials (kinit) - optional for demo server

Run with: pytest tests/test_help_markdown.py -v

Skip if no server available: pytest -m "not integration"
"""

import pytest
from ipaclient import IPAClient, IPAError


# Mark all tests in this file as integration tests
pytestmark = pytest.mark.integration


@pytest.fixture
def live_server():
    """Live IPA server for integration testing."""
    return "ipa.demo1.freeipa.org"


@pytest.fixture
def live_client(live_server):
    """Client connected to live server (no SSL verification for demo)."""
    return IPAClient(live_server, verify_ssl=False)


def test_topics_markdown(live_client):
    """Test markdown conversion for topics listing."""
    markdown = live_client.help_markdown()

    # Verify structure
    assert "# IPA Help Topics" in markdown
    assert "| Topic | Description |" in markdown
    assert "|-------|-------------|" in markdown

    # Verify content
    lines = markdown.split("\n")
    topic_lines = [line for line in lines if line.startswith("|") and "Topic" not in line and "---" not in line]
    assert len(topic_lines) > 10, f"Expected >10 topics, got {len(topic_lines)}"


def test_topics_alias(live_client):
    """Test that help_markdown('topics') works."""
    markdown = live_client.help_markdown("topics")

    assert "# IPA Help Topics" in markdown
    assert "| Topic | Description |" in markdown


def test_commands_markdown(live_client):
    """Test markdown conversion for commands listing."""
    markdown = live_client.help_markdown("commands")

    # Verify structure
    assert "# IPA Commands" in markdown
    assert "| Command | Description |" in markdown
    assert "|---------|-------------|" in markdown

    # Verify content
    lines = markdown.split("\n")
    cmd_lines = [line for line in lines if line.startswith("|") and "Command" not in line and "---" not in line]
    assert len(cmd_lines) > 100, f"Expected >100 commands, got {len(cmd_lines)}"


def test_topic_details_markdown(live_client):
    """Test markdown conversion for topic details."""
    markdown = live_client.help_markdown("user")

    # Verify structure
    assert "# user" in markdown
    assert "## Commands" in markdown
    assert "| Command | Description |" in markdown

    # Verify content
    assert "user_add" in markdown or "user_show" in markdown


def test_command_details_markdown(live_client):
    """Test markdown conversion for command details."""
    markdown = live_client.help_markdown("user_show")

    # Verify structure
    assert "# user_show" in markdown
    assert "## Options" in markdown
    assert "| Option | Type | Description |" in markdown

    # Verify specific options exist
    assert "uid" in markdown
    assert "all" in markdown
    assert "raw" in markdown


def test_pipe_escaping(live_client):
    """Test that pipe characters in descriptions are escaped."""
    # Get commands markdown (summaries may contain pipes)
    markdown = live_client.help_markdown("commands")

    # Check that table structure is not broken
    lines = markdown.split("\n")
    for line in lines:
        if line.startswith("|") and "---" not in line and "Command" not in line:
            # Count pipes - should be exactly 3 for a 2-column table
            # (starting |, middle |, ending |)
            pipe_count = line.count("|")
            assert pipe_count == 3, f"Table row has {pipe_count} pipes: {line[:50]}"


def test_invalid_topic(live_client):
    """Test error handling for invalid topic."""
    with pytest.raises(IPAError) as exc_info:
        live_client.help_markdown("nonexistent_topic_12345")

    assert "Unknown command or topic" in str(exc_info.value) or "NotFound" in str(exc_info.value)
