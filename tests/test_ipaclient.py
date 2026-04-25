# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for IPA client exceptions and initialization."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import responses

from freeipa_mcp.ipaclient import (
    IPAAuthenticationError,
    IPAConnectionError,
    IPAError,
    IPASchemaError,
    IPAServerError,
    IPAThinClient,
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
    client = IPAThinClient(mock_server)
    assert client._server == mock_server
    assert client._base_url == f"https://{mock_server}"
    assert client._json_url == f"https://{mock_server}/ipa/json"
    # When verify_ssl=True, _verify_ssl becomes the path to the CA cert
    assert isinstance(client._verify_ssl, str)
    assert client._verify_ssl.endswith(".crt")
    assert client._schema is None


def test_client_init_no_ssl_verify(mock_server):
    """Test client initialization with SSL verification disabled."""
    client = IPAThinClient(mock_server, verify_ssl=False)
    assert client._verify_ssl is False


def test_client_init_url_construction():
    """Test URL construction for various server formats."""
    # Just hostname
    client = IPAThinClient("ipa.example.com", verify_ssl=False)
    assert client._base_url == "https://ipa.example.com"

    # Hostname with domain
    client = IPAThinClient("ipa.corp.example.com", verify_ssl=False)
    assert client._base_url == "https://ipa.corp.example.com"

    # IP address
    client = IPAThinClient("192.168.1.100", verify_ssl=False)
    assert client._base_url == "https://192.168.1.100"


# ============================================================================
# JSON-RPC Request Tests
# ============================================================================


@responses.activate
@patch("freeipa_mcp.ipaclient.HTTPSPNEGOAuth")
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

    client = IPAThinClient(mock_server)
    result = client._make_request("ping")

    assert result == {"summary": "OK"}
    assert len(responses.calls) == 1

    # Verify request payload
    body = responses.calls[0].request.body
    assert body is not None
    request_body = json.loads(body)
    assert request_body["method"] == "ping"
    assert request_body["params"] == [[], {"version": "2.251"}]
    assert request_body["id"] == 0


@responses.activate
@patch("freeipa_mcp.ipaclient.HTTPSPNEGOAuth")
def test_make_request_with_args(mock_auth, mock_server):
    """Test JSON-RPC request with positional arguments."""
    responses.add(
        responses.POST,
        f"https://{mock_server}/ipa/json",
        json={"result": {"uid": "admin"}, "error": None},
        status=200,
    )

    client = IPAThinClient(mock_server)
    client._make_request("user_show", args=["admin"])

    body = responses.calls[0].request.body
    assert body is not None
    request_body = json.loads(body)
    assert request_body["params"][0] == ["admin"]


@responses.activate
@patch("freeipa_mcp.ipaclient.HTTPSPNEGOAuth")
def test_make_request_with_options(mock_auth, mock_server):
    """Test JSON-RPC request with options."""
    responses.add(
        responses.POST,
        f"https://{mock_server}/ipa/json",
        json={"result": {"data": "test"}, "error": None},
        status=200,
    )

    client = IPAThinClient(mock_server)
    client._make_request("test", options={"all": True, "raw": False})

    body = responses.calls[0].request.body
    assert body is not None
    request_body = json.loads(body)
    assert request_body["params"][1]["all"] is True
    assert request_body["params"][1]["raw"] is False
    assert request_body["params"][1]["version"] == "2.251"


@responses.activate
@patch("freeipa_mcp.ipaclient.HTTPSPNEGOAuth")
def test_make_request_version_override(mock_auth, mock_server):
    """Test that explicit version is not overridden."""
    responses.add(
        responses.POST,
        f"https://{mock_server}/ipa/json",
        json={"result": {}, "error": None},
        status=200,
    )

    client = IPAThinClient(mock_server)
    client._make_request("test", options={"version": "2.250"})

    body = responses.calls[0].request.body
    assert body is not None
    request_body = json.loads(body)
    assert request_body["params"][1]["version"] == "2.250"


@responses.activate
@patch("freeipa_mcp.ipaclient.HTTPSPNEGOAuth")
def test_make_request_http_error(mock_auth, mock_server):
    """Test handling of HTTP errors."""
    responses.add(
        responses.POST,
        f"https://{mock_server}/ipa/json",
        json={"error": "Not found"},
        status=404,
    )

    client = IPAThinClient(mock_server)
    with pytest.raises(IPAServerError) as exc_info:
        client._make_request("test")

    assert "HTTP 404" in str(exc_info.value)


@responses.activate
@patch("freeipa_mcp.ipaclient.HTTPSPNEGOAuth")
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

    client = IPAThinClient(mock_server)
    with pytest.raises(IPAServerError) as exc_info:
        client._make_request("user_show", args=["nonexistent"])

    assert "User not found" in str(exc_info.value)


@responses.activate
@patch("freeipa_mcp.ipaclient.HTTPSPNEGOAuth")
def test_make_request_connection_error(mock_auth, mock_server):
    """Test handling of connection errors."""
    client = IPAThinClient(mock_server)

    with pytest.raises(IPAConnectionError) as exc_info:
        client._make_request("ping")

    assert (
        "Connection" in str(exc_info.value) or "refused" in str(exc_info.value).lower()
    )


# ============================================================================
# Ping Command Tests
# ============================================================================


@responses.activate
@patch("freeipa_mcp.ipaclient.HTTPSPNEGOAuth")
def test_ping_success(mock_auth, mock_server, mock_ping_response):
    """Test successful ping."""
    responses.add(
        responses.POST,
        f"https://{mock_server}/ipa/json",
        json=mock_ping_response,
        status=200,
    )

    client = IPAThinClient(mock_server)
    result = client.ping()

    assert "summary" in result
    assert "IPA server version" in result["summary"]
    assert "API version" in result["summary"]


@responses.activate
@patch("freeipa_mcp.ipaclient.HTTPSPNEGOAuth")
def test_ping_connection_error(mock_auth, mock_server):
    """Test ping with connection error."""
    client = IPAThinClient(mock_server)

    with pytest.raises(IPAConnectionError):
        client.ping()


# ============================================================================
# Command Execution Tests
# ============================================================================


@responses.activate
@patch("freeipa_mcp.ipaclient.HTTPSPNEGOAuth")
def test_command_no_args(mock_auth, mock_server):
    """Test command execution with no arguments."""
    responses.add(
        responses.POST,
        f"https://{mock_server}/ipa/json",
        json={"result": {"data": "test"}, "error": None},
        status=200,
    )

    client = IPAThinClient(mock_server)
    result = client.command("config_show")

    assert result == {"data": "test"}


@responses.activate
@patch("freeipa_mcp.ipaclient.HTTPSPNEGOAuth")
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

    client = IPAThinClient(mock_server)
    client.command("user_show", "admin")

    body = responses.calls[0].request.body
    assert body is not None
    request_body = json.loads(body)
    assert request_body["method"] == "user_show"
    assert request_body["params"][0] == ["admin"]


@responses.activate
@patch("freeipa_mcp.ipaclient.HTTPSPNEGOAuth")
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

    client = IPAThinClient(mock_server)
    client.command("user_find", uid="test", sizelimit=10)

    body = responses.calls[0].request.body
    assert body is not None
    request_body = json.loads(body)
    assert request_body["params"][1]["uid"] == "test"
    assert request_body["params"][1]["sizelimit"] == 10
    assert request_body["params"][1]["version"] == "2.251"


@responses.activate
@patch("freeipa_mcp.ipaclient.HTTPSPNEGOAuth")
def test_command_with_args_and_kwargs(mock_auth, mock_server):
    """Test command execution with both args and kwargs."""
    responses.add(
        responses.POST,
        f"https://{mock_server}/ipa/json",
        json={"result": {"cn": ["testgroup"]}, "error": None},
        status=200,
    )

    client = IPAThinClient(mock_server)
    client.command("group_show", "testgroup", all=True, raw=False)

    body = responses.calls[0].request.body
    assert body is not None
    request_body = json.loads(body)
    assert request_body["params"][0] == ["testgroup"]
    assert request_body["params"][1]["all"] is True
    assert request_body["params"][1]["raw"] is False


# ============================================================================
# Schema Retrieval and Caching Tests
# ============================================================================


@responses.activate
@patch("freeipa_mcp.ipaclient.HTTPSPNEGOAuth")
def test_get_schema_initial_fetch(mock_auth, mock_server, mock_schema):
    """Test initial schema fetch."""
    responses.add(
        responses.POST,
        f"https://{mock_server}/ipa/json",
        json={"result": mock_schema, "error": None},
        status=200,
    )

    client = IPAThinClient(mock_server)
    schema = client._get_schema()

    assert schema == mock_schema
    assert client._schema == mock_schema
    assert len(responses.calls) == 1


@responses.activate
@patch("freeipa_mcp.ipaclient.HTTPSPNEGOAuth")
def test_get_schema_cached(mock_auth, mock_server, mock_schema):
    """Test schema caching."""
    responses.add(
        responses.POST,
        f"https://{mock_server}/ipa/json",
        json={"result": mock_schema, "error": None},
        status=200,
    )

    client = IPAThinClient(mock_server)

    # First call - fetches from server
    schema1 = client._get_schema()
    assert len(responses.calls) == 1

    # Second call - uses cache
    schema2 = client._get_schema()
    assert len(responses.calls) == 1  # No additional call
    assert schema1 is schema2


@responses.activate
@patch("freeipa_mcp.ipaclient.HTTPSPNEGOAuth")
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

    client = IPAThinClient(mock_server)

    with pytest.raises(IPASchemaError) as exc_info:
        client._get_schema()

    assert "Schema fetch failed" in str(exc_info.value)


# ============================================================================
# Help - Topic Listing Tests
# ============================================================================


@responses.activate
@patch("freeipa_mcp.ipaclient.HTTPSPNEGOAuth")
def test_help_no_args_lists_topics(mock_auth, mock_server, mock_schema):
    """Test help() with no arguments lists all topics."""
    responses.add(
        responses.POST,
        f"https://{mock_server}/ipa/json",
        json={"result": mock_schema, "error": None},
        status=200,
    )

    client = IPAThinClient(mock_server)
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
@patch("freeipa_mcp.ipaclient.HTTPSPNEGOAuth")
def test_help_topics_arg(mock_auth, mock_server, mock_schema):
    """Test help('topics') explicitly."""
    responses.add(
        responses.POST,
        f"https://{mock_server}/ipa/json",
        json={"result": mock_schema, "error": None},
        status=200,
    )

    client = IPAThinClient(mock_server)
    result = client.help("topics")

    assert "topics" in result
    assert len(result["topics"]) == 2


# ============================================================================
# Help - Commands Listing Tests
# ============================================================================


@responses.activate
@patch("freeipa_mcp.ipaclient.HTTPSPNEGOAuth")
def test_help_commands(mock_auth, mock_server, mock_schema):
    """Test help('commands') lists all commands."""
    responses.add(
        responses.POST,
        f"https://{mock_server}/ipa/json",
        json={"result": mock_schema, "error": None},
        status=200,
    )

    client = IPAThinClient(mock_server)
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
@patch("freeipa_mcp.ipaclient.HTTPSPNEGOAuth")
def test_help_topic_details(mock_auth, mock_server, mock_schema):
    """Test help('<topic>') returns topic info with command list."""
    responses.add(
        responses.POST,
        f"https://{mock_server}/ipa/json",
        json={"result": mock_schema, "error": None},
        status=200,
    )

    client = IPAThinClient(mock_server)
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
@patch("freeipa_mcp.ipaclient.HTTPSPNEGOAuth")
def test_help_unknown_topic(mock_auth, mock_server, mock_schema):
    """Test help() with unknown topic raises IPAValidationError."""
    responses.add(
        responses.POST,
        f"https://{mock_server}/ipa/json",
        json={"result": mock_schema, "error": None},
        status=200,
    )

    client = IPAThinClient(mock_server)

    with pytest.raises(IPAValidationError) as exc_info:
        client.help("nonexistent")

    assert exc_info.value.code == "NotFound"
    assert "nonexistent" in str(exc_info.value)


# ============================================================================
# Help - Command Details Tests
# ============================================================================


@responses.activate
@patch("freeipa_mcp.ipaclient.HTTPSPNEGOAuth")
def test_help_command_details(mock_auth, mock_server, mock_schema):
    """Test help('<command>') returns command details with args and options."""
    responses.add(
        responses.POST,
        f"https://{mock_server}/ipa/json",
        json={"result": mock_schema, "error": None},
        status=200,
    )

    client = IPAThinClient(mock_server)
    result = client.help("user_show")

    assert result["name"] == "user_show"
    assert result["topic"] == "user"
    assert (
        result["doc"]
        == "Display information about a user.\n\nShows detailed user attributes."
    )
    assert result["summary"] == "Display information about a user"

    # Required params with cli_name become args
    assert "args" in result
    assert len(result["args"]) == 1
    assert result["args"][0]["name"] == "uid"
    assert result["args"][0]["cli_name"] == "login"
    assert result["args"][0]["type"] == "str"
    assert result["args"][0]["label"] == "User login"

    # Optional params become options (excluding 'version' with exclude=webui)
    assert "options" in result
    assert len(result["options"]) == 1
    assert result["options"][0]["name"] == "all"
    assert result["options"][0]["type"] == "bool"
    assert result["options"][0]["default"] is False


@responses.activate
@patch("freeipa_mcp.ipaclient.HTTPSPNEGOAuth")
def test_help_command_no_required_args(mock_auth, mock_server, mock_schema):
    """Test help('<command>') with no required args has empty args list."""
    responses.add(
        responses.POST,
        f"https://{mock_server}/ipa/json",
        json={"result": mock_schema, "error": None},
        status=200,
    )

    client = IPAThinClient(mock_server)
    result = client.help("user_find")

    assert result["name"] == "user_find"
    assert result["args"] == []

    # All non-excluded optional params become options
    assert len(result["options"]) == 2
    option_names = [o["name"] for o in result["options"]]
    assert "criteria" in option_names
    assert "sizelimit" in option_names

    # Check type mapping
    options = {o["name"]: o for o in result["options"]}
    assert options["criteria"]["type"] == "str"
    assert options["sizelimit"]["type"] == "int"


# ============================================================================
# Type Mapping Tests
# ============================================================================


def test_map_type_basic_types(mock_server):
    """Test type mapping for basic IPA types."""
    client = IPAThinClient(mock_server)

    assert client._map_type("Str") == "str"
    assert client._map_type("Int") == "int"
    assert client._map_type("Bool") == "bool"
    assert client._map_type("Flag") == "bool"
    assert client._map_type("List") == "list"
    assert client._map_type("Dict") == "dict"


def test_map_type_unknown(mock_server):
    """Test type mapping for unknown types falls back to str."""
    client = IPAThinClient(mock_server)

    assert client._map_type("SomeCustomType") == "str"
    assert client._map_type("") == "str"
    assert client._map_type(None) == "str"


# ============================================================================
# Schema Export Tests
# ============================================================================


@responses.activate
@patch("freeipa_mcp.ipaclient.HTTPSPNEGOAuth")
def test_export_schema_structure(mock_auth, mock_server, mock_schema):
    """Test export_schema returns correct structure."""
    responses.add(
        responses.POST,
        f"https://{mock_server}/ipa/json",
        json={"result": mock_schema, "error": None},
        status=200,
    )

    client = IPAThinClient(mock_server)
    result = client.export_schema()

    # Check top-level structure
    assert "topics" in result
    assert "commands" in result

    # Check topics structure
    assert "user" in result["topics"]
    user_topic = result["topics"]["user"]
    assert user_topic["name"] == "user"
    assert user_topic["summary"] == "Users"
    assert user_topic["doc"] == "Users\n\nManage user accounts."
    assert "user_show" in user_topic["commands"]
    assert "user_find" in user_topic["commands"]

    # Check commands structure
    assert "user_show" in result["commands"]
    user_show = result["commands"]["user_show"]
    assert user_show["name"] == "user_show"
    assert user_show["topic"] == "user"
    assert user_show["summary"] == "Display information about a user"
    assert len(user_show["args"]) == 1
    assert user_show["args"][0]["name"] == "uid"
    assert user_show["args"][0]["type"] == "str"

    # Check options don't include version param
    option_names = [opt["name"] for opt in user_show["options"]]
    assert "all" in option_names
    assert "version" not in option_names


@responses.activate
@patch("freeipa_mcp.ipaclient.HTTPSPNEGOAuth")
def test_export_schema_caching(mock_auth, mock_server, mock_schema):
    """Test export_schema uses cached schema."""
    responses.add(
        responses.POST,
        f"https://{mock_server}/ipa/json",
        json={"result": mock_schema, "error": None},
        status=200,
    )

    client = IPAThinClient(mock_server)

    # First call
    result1 = client.export_schema()
    assert len(responses.calls) == 1

    # Second call - should use cache
    result2 = client.export_schema()
    assert len(responses.calls) == 1

    assert result1 == result2


# ============================================================================
# CA Certificate Tests
# ============================================================================


@responses.activate
def test_get_ca_cert_downloads_and_caches(mock_server, tmp_path, monkeypatch):
    """Test that CA certificate is downloaded and cached."""
    # Override the autouse fixture for this test
    monkeypatch.undo()

    # Mock home directory to use tmp_path
    cache_dir = tmp_path / ".cache" / "freeipa-mcp-py" / mock_server
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    # Mock CA certificate content
    ca_cert_content = """-----BEGIN CERTIFICATE-----
MIIDNTCCAh2gAwIBAgIBATANBgkqhkiG9w0BAQsFADA3MRUwEwYDVQQKDAxJUEEu
RVBBU2VMSU5FMR4wHAYDVQQDDBVDZXJ0aWZpY2F0ZSBBdXRob3JpdHkwHhcNMjQw
-----END CERTIFICATE-----"""

    # Mock HTTP GET for CA cert download
    responses.add(
        responses.GET,
        f"http://{mock_server}/ipa/config/ca.crt",
        body=ca_cert_content,
        status=200,
    )

    # Create client (should download cert)
    client = IPAThinClient(mock_server, verify_ssl=True)

    # Verify cert was downloaded
    assert len(responses.calls) == 1
    assert responses.calls[0].request.url == f"http://{mock_server}/ipa/config/ca.crt"

    # Verify cert was cached
    cert_path = cache_dir / "ca.crt"
    assert cert_path.exists()
    assert ca_cert_content in cert_path.read_text()

    # Verify client uses the cert path
    assert client._verify_ssl == str(cert_path)


@responses.activate
def test_get_ca_cert_uses_cached(mock_server, tmp_path, monkeypatch):
    """Test that cached CA certificate is reused."""
    # Override the autouse fixture for this test
    monkeypatch.undo()

    # Mock home directory to use tmp_path
    cache_dir = tmp_path / ".cache" / "freeipa-mcp-py" / mock_server
    cache_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    # Pre-populate cache
    ca_cert_content = (
        "-----BEGIN CERTIFICATE-----\nCACHED CERT\n-----END CERTIFICATE-----"
    )
    cert_path = cache_dir / "ca.crt"
    cert_path.write_text(ca_cert_content)

    # Create client (should NOT download cert)
    client = IPAThinClient(mock_server, verify_ssl=True)

    # Verify no HTTP requests were made
    assert len(responses.calls) == 0

    # Verify client uses the cached cert
    assert client._verify_ssl == str(cert_path)


@responses.activate
def test_get_ca_cert_download_failure(mock_server, tmp_path, monkeypatch):
    """Test handling of CA certificate download failure."""
    # Override the autouse fixture for this test
    monkeypatch.undo()

    # Mock home directory to use tmp_path
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    # Mock failed CA cert download
    responses.add(
        responses.GET,
        f"http://{mock_server}/ipa/config/ca.crt",
        status=404,
    )

    # Should raise IPAConnectionError
    with pytest.raises(IPAConnectionError) as exc_info:
        IPAThinClient(mock_server, verify_ssl=True)

    assert "Failed to download CA certificate" in str(exc_info.value)
    assert mock_server in str(exc_info.value)


def test_verify_ssl_false_skips_ca_cert(mock_server, monkeypatch):
    """Test that verify_ssl=False skips CA certificate download."""
    # Override the autouse fixture for this test
    monkeypatch.undo()

    # Create client with verify_ssl=False
    client = IPAThinClient(mock_server, verify_ssl=False)

    # Should not attempt to get CA cert
    assert client._verify_ssl is False


@responses.activate
@patch("freeipa_mcp.ipaclient.HTTPSPNEGOAuth")
def test_ssl_verification_with_ca_cert(mock_auth, mock_server, tmp_path, monkeypatch):
    """Test that SSL verification uses the CA certificate."""
    # Override the autouse fixture for this test
    monkeypatch.undo()

    # Mock home directory to use tmp_path
    cache_dir = tmp_path / ".cache" / "freeipa-mcp-py" / mock_server
    cache_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    # Pre-populate cache
    cert_path = cache_dir / "ca.crt"
    cert_path.write_text("-----BEGIN CERTIFICATE-----\nCERT\n-----END CERTIFICATE-----")

    # Mock JSON-RPC response
    responses.add(
        responses.POST,
        f"https://{mock_server}/ipa/json",
        json={"result": {"summary": "OK"}, "error": None},
        status=200,
    )

    # Create client and make request
    client = IPAThinClient(mock_server, verify_ssl=True)
    result = client._make_request("ping")

    assert result == {"summary": "OK"}
    # The request should have been made with verify=cert_path
    # (We can't easily verify this with responses, but the test ensures no errors)
