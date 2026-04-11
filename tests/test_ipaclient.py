"""Tests for IPA client exceptions and initialization."""

from unittest.mock import patch
import pytest
import responses
import json
from ipaclient import (
    IPAClient,
    IPAError,
    IPAConnectionError,
    IPAAuthenticationError,
    IPAServerError,
    IPASchemaError,
    IPAValidationError,
)


def test_ipa_error_basic():
    """Test IPAError with message only."""
    error = IPAError("Something went wrong")
    assert str(error) == "Something went wrong"
    assert error.message == "Something went wrong"
    assert error.code == "IPAError"
    assert error.data == {}


def test_ipa_error_with_code():
    """Test IPAError with custom code."""
    error = IPAError("Not found", code="NotFound")
    assert error.code == "NotFound"


def test_ipa_error_with_data():
    """Test IPAError with additional data."""
    error = IPAError("Validation failed", data={"field": "username"})
    assert error.data == {"field": "username"}


def test_ipa_error_to_dict():
    """Test IPAError.to_dict() method."""
    error = IPAError("Test error", code="TestCode", data={"key": "value"})
    result = error.to_dict()
    assert result == {
        "error": {
            "code": "TestCode",
            "message": "Test error",
            "data": {"key": "value"},
        }
    }


def test_ipa_error_subclasses():
    """Test exception subclass hierarchy."""
    connection_error = IPAConnectionError("Connection failed")
    assert isinstance(connection_error, IPAError)
    assert connection_error.code == "IPAConnectionError"

    auth_error = IPAAuthenticationError("Auth failed")
    assert isinstance(auth_error, IPAError)
    assert auth_error.code == "IPAAuthenticationError"

    server_error = IPAServerError("Server error")
    assert isinstance(server_error, IPAError)
    assert server_error.code == "IPAServerError"

    schema_error = IPASchemaError("Schema error")
    assert isinstance(schema_error, IPAError)
    assert schema_error.code == "IPASchemaError"

    validation_error = IPAValidationError("Validation error")
    assert isinstance(validation_error, IPAError)
    assert validation_error.code == "IPAValidationError"


# ============================================================================
# Client Initialization Tests
# ============================================================================


def test_client_init_basic(mock_server):
    """Test basic client initialization."""
    client = IPAClient(mock_server)
    assert client._server == mock_server
    assert client._base_url == f"https://{mock_server}"
    assert client._json_url == f"https://{mock_server}/ipa/json"
    assert client._verify_ssl is True
    assert client._schema is None


def test_client_init_no_ssl_verify(mock_server):
    """Test client initialization with SSL verification disabled."""
    client = IPAClient(mock_server, verify_ssl=False)
    assert client._verify_ssl is False


def test_client_init_url_construction():
    """Test URL construction for various server formats."""
    # Just hostname
    client = IPAClient("ipa.example.com")
    assert client._base_url == "https://ipa.example.com"

    # Hostname with domain
    client = IPAClient("ipa.corp.example.com")
    assert client._base_url == "https://ipa.corp.example.com"

    # IP address
    client = IPAClient("192.168.1.100")
    assert client._base_url == "https://192.168.1.100"


# ============================================================================
# JSON-RPC Request Tests
# ============================================================================


@responses.activate
@patch("ipaclient.HTTPSPNEGOAuth")
def test_make_request_basic(mock_auth, mock_server):
    """Test basic JSON-RPC request."""
    responses.add(
        responses.POST,
        f"https://{mock_server}/ipa/json",
        json={
            "result": {"summary": "OK"},
            "error": None,
        },
        status=200,
    )

    client = IPAClient(mock_server)
    result = client._make_request("ping")

    assert result == {"summary": "OK"}
    assert len(responses.calls) == 1

    # Verify request payload
    request_body = json.loads(responses.calls[0].request.body)
    assert request_body["method"] == "ping"
    assert request_body["params"] == [[], {"version": "2.251"}]
    assert request_body["id"] == 0


@responses.activate
@patch("ipaclient.HTTPSPNEGOAuth")
def test_make_request_with_args(mock_auth, mock_server):
    """Test JSON-RPC request with positional arguments."""
    responses.add(
        responses.POST,
        f"https://{mock_server}/ipa/json",
        json={"result": {"uid": "admin"}, "error": None},
        status=200,
    )

    client = IPAClient(mock_server)
    result = client._make_request("user_show", args=["admin"])

    request_body = json.loads(responses.calls[0].request.body)
    assert request_body["params"][0] == ["admin"]


@responses.activate
@patch("ipaclient.HTTPSPNEGOAuth")
def test_make_request_with_options(mock_auth, mock_server):
    """Test JSON-RPC request with options."""
    responses.add(
        responses.POST,
        f"https://{mock_server}/ipa/json",
        json={"result": {"data": "test"}, "error": None},
        status=200,
    )

    client = IPAClient(mock_server)
    result = client._make_request("test", options={"all": True, "raw": False})

    request_body = json.loads(responses.calls[0].request.body)
    assert request_body["params"][1]["all"] is True
    assert request_body["params"][1]["raw"] is False
    assert request_body["params"][1]["version"] == "2.251"


@responses.activate
@patch("ipaclient.HTTPSPNEGOAuth")
def test_make_request_version_override(mock_auth, mock_server):
    """Test that explicit version is not overridden."""
    responses.add(
        responses.POST,
        f"https://{mock_server}/ipa/json",
        json={"result": {}, "error": None},
        status=200,
    )

    client = IPAClient(mock_server)
    client._make_request("test", options={"version": "2.250"})

    request_body = json.loads(responses.calls[0].request.body)
    assert request_body["params"][1]["version"] == "2.250"


@responses.activate
@patch("ipaclient.HTTPSPNEGOAuth")
def test_make_request_http_error(mock_auth, mock_server):
    """Test handling of HTTP errors."""
    responses.add(
        responses.POST,
        f"https://{mock_server}/ipa/json",
        json={"error": "Not found"},
        status=404,
    )

    client = IPAClient(mock_server)
    with pytest.raises(IPAServerError) as exc_info:
        client._make_request("test")

    assert "HTTP 404" in str(exc_info.value)


@responses.activate
@patch("ipaclient.HTTPSPNEGOAuth")
def test_make_request_ipa_error(mock_auth, mock_server):
    """Test handling of IPA server errors."""
    responses.add(
        responses.POST,
        f"https://{mock_server}/ipa/json",
        json={
            "result": None,
            "error": {
                "code": 4001,
                "message": "User not found",
                "name": "NotFound",
            },
        },
        status=200,
    )

    client = IPAClient(mock_server)
    with pytest.raises(IPAServerError) as exc_info:
        client._make_request("user_show", args=["nonexistent"])

    assert "User not found" in str(exc_info.value)


@responses.activate
@patch("ipaclient.HTTPSPNEGOAuth")
def test_make_request_connection_error(mock_auth, mock_server):
    """Test handling of connection errors."""
    client = IPAClient(mock_server)

    with pytest.raises(IPAConnectionError) as exc_info:
        client._make_request("ping")

    assert "Connection" in str(exc_info.value) or "refused" in str(exc_info.value).lower()


# ============================================================================
# Ping Command Tests
# ============================================================================


@responses.activate
@patch("ipaclient.HTTPSPNEGOAuth")
def test_ping_success(mock_auth, mock_server, mock_ping_response):
    """Test successful ping."""
    responses.add(
        responses.POST,
        f"https://{mock_server}/ipa/json",
        json=mock_ping_response,
        status=200,
    )

    client = IPAClient(mock_server)
    result = client.ping()

    assert "summary" in result
    assert "IPA server version" in result["summary"]
    assert "API version" in result["summary"]


@responses.activate
@patch("ipaclient.HTTPSPNEGOAuth")
def test_ping_connection_error(mock_auth, mock_server):
    """Test ping with connection error."""
    client = IPAClient(mock_server)

    with pytest.raises(IPAConnectionError):
        client.ping()


# ============================================================================
# Command Execution Tests
# ============================================================================


@responses.activate
@patch("ipaclient.HTTPSPNEGOAuth")
def test_command_no_args(mock_auth, mock_server):
    """Test command execution with no arguments."""
    responses.add(
        responses.POST,
        f"https://{mock_server}/ipa/json",
        json={"result": {"data": "test"}, "error": None},
        status=200,
    )

    client = IPAClient(mock_server)
    result = client.command("config_show")

    assert result == {"data": "test"}


@responses.activate
@patch("ipaclient.HTTPSPNEGOAuth")
def test_command_with_args(mock_auth, mock_server):
    """Test command execution with positional arguments."""
    responses.add(
        responses.POST,
        f"https://{mock_server}/ipa/json",
        json={
            "result": {"uid": ["admin"], "cn": ["Administrator"]},
            "error": None,
        },
        status=200,
    )

    client = IPAClient(mock_server)
    result = client.command("user_show", "admin")

    request_body = json.loads(responses.calls[0].request.body)
    assert request_body["method"] == "user_show"
    assert request_body["params"][0] == ["admin"]


@responses.activate
@patch("ipaclient.HTTPSPNEGOAuth")
def test_command_with_kwargs(mock_auth, mock_server):
    """Test command execution with keyword arguments."""
    responses.add(
        responses.POST,
        f"https://{mock_server}/ipa/json",
        json={
            "result": [{"uid": ["user1"]}, {"uid": ["user2"]}],
            "count": 2,
            "error": None,
        },
        status=200,
    )

    client = IPAClient(mock_server)
    result = client.command("user_find", uid="test", sizelimit=10)

    request_body = json.loads(responses.calls[0].request.body)
    assert request_body["params"][1]["uid"] == "test"
    assert request_body["params"][1]["sizelimit"] == 10
    assert request_body["params"][1]["version"] == "2.251"


@responses.activate
@patch("ipaclient.HTTPSPNEGOAuth")
def test_command_with_args_and_kwargs(mock_auth, mock_server):
    """Test command execution with both args and kwargs."""
    responses.add(
        responses.POST,
        f"https://{mock_server}/ipa/json",
        json={"result": {"cn": ["testgroup"]}, "error": None},
        status=200,
    )

    client = IPAClient(mock_server)
    result = client.command("group_show", "testgroup", all=True, raw=False)

    request_body = json.loads(responses.calls[0].request.body)
    assert request_body["params"][0] == ["testgroup"]
    assert request_body["params"][1]["all"] is True
    assert request_body["params"][1]["raw"] is False


# ============================================================================
# Schema Retrieval and Caching Tests
# ============================================================================


@responses.activate
@patch("ipaclient.HTTPSPNEGOAuth")
def test_get_schema_initial_fetch(mock_auth, mock_server, mock_schema):
    """Test initial schema fetch."""
    responses.add(
        responses.POST,
        f"https://{mock_server}/ipa/json",
        json={"result": mock_schema, "error": None},
        status=200,
    )

    client = IPAClient(mock_server)
    schema = client._get_schema()

    assert schema == mock_schema
    assert client._schema == mock_schema
    assert len(responses.calls) == 1


@responses.activate
@patch("ipaclient.HTTPSPNEGOAuth")
def test_get_schema_cached(mock_auth, mock_server, mock_schema):
    """Test schema caching."""
    responses.add(
        responses.POST,
        f"https://{mock_server}/ipa/json",
        json={"result": mock_schema, "error": None},
        status=200,
    )

    client = IPAClient(mock_server)

    # First call - fetches from server
    schema1 = client._get_schema()
    assert len(responses.calls) == 1

    # Second call - uses cache
    schema2 = client._get_schema()
    assert len(responses.calls) == 1  # No additional call
    assert schema1 is schema2


@responses.activate
@patch("ipaclient.HTTPSPNEGOAuth")
def test_get_schema_error(mock_auth, mock_server):
    """Test schema fetch error handling."""
    responses.add(
        responses.POST,
        f"https://{mock_server}/ipa/json",
        json={
            "result": None,
            "error": {"message": "Schema not available", "code": 500},
        },
        status=200,
    )

    client = IPAClient(mock_server)

    with pytest.raises(IPASchemaError) as exc_info:
        client._get_schema()

    assert "Schema fetch failed" in str(exc_info.value)


# ============================================================================
# Help - Topic Listing Tests
# ============================================================================


@responses.activate
@patch("ipaclient.HTTPSPNEGOAuth")
def test_help_no_args_lists_topics(mock_auth, mock_server, mock_schema):
    """Test help() with no arguments lists all topics."""
    responses.add(
        responses.POST,
        f"https://{mock_server}/ipa/json",
        json={"result": mock_schema, "error": None},
        status=200,
    )

    client = IPAClient(mock_server)
    result = client.help()

    assert "topics" in result
    assert len(result["topics"]) == 2

    # Check topics are sorted and have correct structure
    topics = {t["name"]: t for t in result["topics"]}

    assert "user" in topics
    assert topics["user"]["summary"] == "Users"

    assert "group" in topics
    assert topics["group"]["summary"] == "Groups"


@responses.activate
@patch("ipaclient.HTTPSPNEGOAuth")
def test_help_topics_arg(mock_auth, mock_server, mock_schema):
    """Test help('topics') explicitly."""
    responses.add(
        responses.POST,
        f"https://{mock_server}/ipa/json",
        json={"result": mock_schema, "error": None},
        status=200,
    )

    client = IPAClient(mock_server)
    result = client.help("topics")

    assert "topics" in result
    assert len(result["topics"]) == 2


# ============================================================================
# Help - Commands Listing Tests
# ============================================================================


@responses.activate
@patch("ipaclient.HTTPSPNEGOAuth")
def test_help_commands(mock_auth, mock_server, mock_schema):
    """Test help('commands') lists all commands."""
    responses.add(
        responses.POST,
        f"https://{mock_server}/ipa/json",
        json={"result": mock_schema, "error": None},
        status=200,
    )

    client = IPAClient(mock_server)
    result = client.help("commands")

    assert "commands" in result
    assert len(result["commands"]) == 3

    # Check commands are sorted and have correct structure
    commands = {c["name"]: c for c in result["commands"]}

    assert "user_show" in commands
    assert commands["user_show"]["summary"] == "Display information about a user"

    assert "user_find" in commands
    assert commands["user_find"]["summary"] == "Search for users"

    assert "group_show" in commands
    assert commands["group_show"]["summary"] == "Display information about a group"


# ============================================================================
# Help - Topic Details Tests
# ============================================================================


@responses.activate
@patch("ipaclient.HTTPSPNEGOAuth")
def test_help_topic_details(mock_auth, mock_server, mock_schema):
    """Test help('<topic>') returns topic info with command list."""
    responses.add(
        responses.POST,
        f"https://{mock_server}/ipa/json",
        json={"result": mock_schema, "error": None},
        status=200,
    )

    client = IPAClient(mock_server)
    result = client.help("user")

    assert result["name"] == "user"
    assert result["doc"] == "Users\n\nManage user accounts."

    # Should contain user commands, sorted by name
    assert "commands" in result
    cmd_names = [c["name"] for c in result["commands"]]
    assert cmd_names == ["user_find", "user_show"]

    # Each command should have name and summary
    cmds = {c["name"]: c for c in result["commands"]}
    assert cmds["user_show"]["summary"] == "Display information about a user"
    assert cmds["user_find"]["summary"] == "Search for users"


@responses.activate
@patch("ipaclient.HTTPSPNEGOAuth")
def test_help_unknown_topic(mock_auth, mock_server, mock_schema):
    """Test help() with unknown topic raises IPAValidationError."""
    responses.add(
        responses.POST,
        f"https://{mock_server}/ipa/json",
        json={"result": mock_schema, "error": None},
        status=200,
    )

    client = IPAClient(mock_server)

    with pytest.raises(IPAValidationError) as exc_info:
        client.help("nonexistent")

    assert exc_info.value.code == "NotFound"
    assert "nonexistent" in str(exc_info.value)
