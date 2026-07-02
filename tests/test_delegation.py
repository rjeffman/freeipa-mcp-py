# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for delegation identity functionality."""

import os
import time
from unittest.mock import patch

import pytest
import responses

from freeipa_mcp.delegation import ActorContext, DelegationConfig, OBOClient


class TestDelegationConfig:
    """Tests for DelegationConfig."""

    def test_from_env_disabled(self):
        """Test DelegationConfig.from_env() when delegation is disabled."""
        with patch.dict(os.environ, {}, clear=True):
            config = DelegationConfig.from_env()
            assert config.enabled is False
            assert config.obo_exchange_url == "http://localhost:8900"
            assert config.client_id == "freeipa-mcp"
            assert config.client_secret_file == ""
            assert config.token_endpoint == ""
            assert config.scopes == ["ipa:read", "ipa:write"]
            assert config.spiffe_id == ""

    def test_from_env_enabled(self):
        """Test DelegationConfig.from_env() with all env vars set."""
        env = {
            "FREEIPA_MCP_DELEGATION_ENABLED": "true",
            "FREEIPA_MCP_OBO_URL": "http://localhost:8901",
            "FREEIPA_MCP_CLIENT_ID": "test-client",
            "FREEIPA_MCP_CLIENT_SECRET_FILE": "/tmp/secret",
            "FREEIPA_MCP_TOKEN_ENDPOINT": "https://ipa.test/oauth/token",
            "FREEIPA_MCP_SCOPES": "ipa:read,ipa:write,ipa:admin",
            "FREEIPA_MCP_SPIFFE_ID": "spiffe://example.com/freeipa",
        }
        with patch.dict(os.environ, env, clear=True):
            config = DelegationConfig.from_env()
            assert config.enabled is True
            assert config.obo_exchange_url == "http://localhost:8901"
            assert config.client_id == "test-client"
            assert config.client_secret_file == "/tmp/secret"
            assert config.token_endpoint == "https://ipa.test/oauth/token"
            assert config.scopes == ["ipa:read", "ipa:write", "ipa:admin"]
            assert config.spiffe_id == "spiffe://example.com/freeipa"

    def test_from_env_partial(self):
        """Test DelegationConfig.from_env() with partial env vars."""
        env = {
            "FREEIPA_MCP_DELEGATION_ENABLED": "yes",  # truthy value
            "FREEIPA_MCP_CLIENT_ID": "custom-id",
        }
        with patch.dict(os.environ, env, clear=True):
            config = DelegationConfig.from_env()
            assert config.enabled is True
            assert config.client_id == "custom-id"
            assert config.obo_exchange_url == "http://localhost:8900"  # default
            assert config.scopes == ["ipa:read", "ipa:write"]  # default


class TestActorContext:
    """Tests for ActorContext."""

    def test_anonymous(self):
        """Test ActorContext.anonymous() creates unknown/freeipa-mcp context."""
        ctx = ActorContext.anonymous()
        assert ctx.principal == "unknown"
        assert ctx.tool_identity == "freeipa-mcp"
        assert ctx.delegation_rule is None
        assert ctx.scopes is None
        assert ctx.spiffe_id is None

    def test_to_dict(self):
        """Test ActorContext.to_dict() serialization."""
        ctx = ActorContext(
            principal="alice@REALM",
            tool_identity="freeipa-mcp",
            delegation_rule="rule1",
            scopes=["ipa:read"],
            spiffe_id="spiffe://example.com/freeipa",
        )
        result = ctx.to_dict()
        assert result == {
            "principal": "alice@REALM",
            "tool": "freeipa-mcp",
            "delegation_rule": "rule1",
        }


class TestOBOClient:
    """Tests for OBOClient."""

    def test_init_disabled(self):
        """Test OBOClient initialization when delegation disabled."""
        config = DelegationConfig(enabled=False)
        client = OBOClient(config)
        assert client.config == config
        assert client._client_secret is None

    def test_init_missing_secret_file(self):
        """Test OBOClient initialization fails when secret file is missing."""
        config = DelegationConfig(enabled=True, client_secret_file="")
        with pytest.raises(ValueError, match="client_secret_file must be set"):
            OBOClient(config)

    def test_init_secret_file_not_found(self):
        """Test OBOClient initialization fails when secret file doesn't exist."""
        config = DelegationConfig(
            enabled=True, client_secret_file="/nonexistent/secret"
        )
        with pytest.raises(ValueError, match="Client secret file not found"):
            OBOClient(config)

    def test_init_secret_file_bad_permissions(self, tmp_path):
        """Test OBOClient initialization fails when secret file has wrong permissions."""
        secret_file = tmp_path / "secret"
        secret_file.write_text("my-secret")
        secret_file.chmod(0o644)  # Too permissive

        config = DelegationConfig(enabled=True, client_secret_file=str(secret_file))
        with pytest.raises(ValueError, match="must have 0600 permissions"):
            OBOClient(config)

    def test_init_secret_file_success(self, tmp_path):
        """Test OBOClient initialization succeeds with correct secret file."""
        secret_file = tmp_path / "secret"
        secret_file.write_text("my-secret\n")
        secret_file.chmod(0o600)

        config = DelegationConfig(enabled=True, client_secret_file=str(secret_file))
        client = OBOClient(config)
        assert client._client_secret == "my-secret"

    @responses.activate
    def test_get_own_token(self, tmp_path):
        """Test get_own_token() client credentials flow."""
        secret_file = tmp_path / "secret"
        secret_file.write_text("test-secret")
        secret_file.chmod(0o600)

        config = DelegationConfig(
            enabled=True,
            client_id="freeipa-mcp",
            client_secret_file=str(secret_file),
            token_endpoint="https://ipa.test/oauth/token",
        )
        client = OBOClient(config)

        # Mock token endpoint
        responses.add(
            responses.POST,
            "https://ipa.test/oauth/token",
            json={"access_token": "token123", "expires_in": 3600},
            status=200,
        )

        token = client.get_own_token()
        assert token == "token123"
        assert len(responses.calls) == 1
        assert responses.calls[0].request.body == (
            "grant_type=client_credentials&client_id=freeipa-mcp&"
            "client_secret=test-secret"
        )

        # Second call should use cache
        token2 = client.get_own_token()
        assert token2 == "token123"
        assert len(responses.calls) == 1  # No additional call

    @responses.activate
    def test_get_own_token_cache_expiry(self, tmp_path):
        """Test get_own_token() refetches after token expires."""
        secret_file = tmp_path / "secret"
        secret_file.write_text("test-secret")
        secret_file.chmod(0o600)

        config = DelegationConfig(
            enabled=True,
            client_id="freeipa-mcp",
            client_secret_file=str(secret_file),
            token_endpoint="https://ipa.test/oauth/token",
        )
        client = OBOClient(config)

        # First token with short expiry
        responses.add(
            responses.POST,
            "https://ipa.test/oauth/token",
            json={"access_token": "token1", "expires_in": 1},
            status=200,
        )

        token1 = client.get_own_token()
        assert token1 == "token1"

        # Wait for expiry (1s + 60s early expiry = negative, forces refresh)
        time.sleep(0.1)
        client._own_token_expiry = (
            time.monotonic() + 30
        )  # 30s remaining < 60s threshold

        # Second token
        responses.add(
            responses.POST,
            "https://ipa.test/oauth/token",
            json={"access_token": "token2", "expires_in": 3600},
            status=200,
        )

        token2 = client.get_own_token()
        assert token2 == "token2"
        assert len(responses.calls) == 2

    @responses.activate
    def test_get_delegated_token(self, tmp_path):
        """Test get_delegated_token() RFC 8693 exchange."""
        secret_file = tmp_path / "secret"
        secret_file.write_text("test-secret")
        secret_file.chmod(0o600)

        config = DelegationConfig(
            enabled=True,
            client_id="freeipa-mcp",
            client_secret_file=str(secret_file),
            token_endpoint="https://ipa.test/oauth/token",
            obo_exchange_url="http://localhost:8900",
            scopes=["ipa:read", "ipa:write"],
        )
        client = OBOClient(config)

        # Mock client credentials
        responses.add(
            responses.POST,
            "https://ipa.test/oauth/token",
            json={"access_token": "own-token", "expires_in": 3600},
            status=200,
        )

        # Mock token exchange
        responses.add(
            responses.POST,
            "http://localhost:8900/token",
            json={
                "access_token": "delegated-token",
                "expires_in": 300,
                "scope": "ipa:read ipa:write",
            },
            status=200,
        )

        result = client.get_delegated_token("alice@REALM")
        assert result.access_token == "delegated-token"
        assert result.expires_in == 300
        assert result.actor.principal == "alice@REALM"
        assert result.actor.tool_identity == "freeipa-mcp"
        assert result.actor.scopes == ["ipa:read", "ipa:write"]

        # Verify token exchange request
        exchange_call = responses.calls[1]
        assert (
            "grant_type=urn%3Aietf%3Aparams%3Aoauth%3Agrant-type%3Atoken-exchange"
            in exchange_call.request.body
        )
        assert "subject_token=own-token" in exchange_call.request.body
        assert "requested_subject=alice%40REALM" in exchange_call.request.body

    @responses.activate
    def test_get_delegated_ccache(self, tmp_path):
        """Test get_delegated_ccache() Kerberos bridge."""
        secret_file = tmp_path / "secret"
        secret_file.write_text("test-secret")
        secret_file.chmod(0o600)

        config = DelegationConfig(
            enabled=True,
            client_id="freeipa-mcp",
            client_secret_file=str(secret_file),
            token_endpoint="https://ipa.test/oauth/token",
            obo_exchange_url="http://localhost:8900",
            scopes=["ipa:read", "ipa:write"],
        )
        client = OBOClient(config)

        # Mock client credentials
        responses.add(
            responses.POST,
            "https://ipa.test/oauth/token",
            json={"access_token": "own-token", "expires_in": 3600},
            status=200,
        )

        # Mock ccache endpoint
        responses.add(
            responses.POST,
            "http://localhost:8900/kerberos",
            json={"ccache": "/tmp/krb5cc_12345"},
            status=200,
        )

        ccache = client.get_delegated_ccache(
            "bob@REALM", target_service="HTTP/ipa.test"
        )
        assert ccache == "/tmp/krb5cc_12345"

        # Verify ccache request
        ccache_call = responses.calls[1]
        assert "subject_token=own-token" in ccache_call.request.body
        assert "requested_subject=bob%40REALM" in ccache_call.request.body
        assert "target_service=HTTP%2Fipa.test" in ccache_call.request.body
        assert "return_contents=true" in ccache_call.request.body


class TestIPAClientCcache:
    """Tests for IPAThinClient ccache_path integration."""

    def test_ipaclient_accepts_ccache_path(self):
        """Test IPAThinClient accepts ccache_path parameter."""
        from freeipa_mcp.ipaclient import IPAThinClient

        with patch.object(IPAThinClient, "_get_ca_cert", return_value=True):
            client = IPAThinClient("ipa.test", ccache_path="/tmp/krb5cc_test")
            assert client._ccache_path == "/tmp/krb5cc_test"

    @responses.activate
    def test_ipaclient_sets_krb5ccname(self):
        """Test IPAThinClient sets KRB5CCNAME before auth."""
        from freeipa_mcp.ipaclient import IPAThinClient

        with patch.dict(os.environ, {}, clear=True):
            with patch.object(IPAThinClient, "_get_ca_cert", return_value=True):
                client = IPAThinClient("ipa.test", ccache_path="/tmp/krb5cc_alice")

                # Mock the JSON-RPC endpoint
                responses.add(
                    responses.POST,
                    "https://ipa.test/ipa/json",
                    json={
                        "result": {"result": "pong"},
                        "error": None,
                    },
                    status=200,
                )

                # Mock SPNEGO auth
                with patch("freeipa_mcp.ipaclient.HTTPSPNEGOAuth"):
                    with patch("freeipa_mcp.ipaclient.requests.post") as mock_post:
                        mock_post.return_value.status_code = 200
                        mock_post.return_value.json.return_value = {
                            "result": {"result": "pong"},
                            "error": None,
                        }

                        client.command("ping")

                        # Verify KRB5CCNAME was set
                        assert os.environ.get("KRB5CCNAME") == "/tmp/krb5cc_alice"


class TestDynamicToolsOnBehalfOf:
    """Tests for on_behalf_of parameter in dynamic tools."""

    def test_non_readonly_tool_has_on_behalf_of(self):
        """Test non-read-only tools have on_behalf_of parameter."""
        from freeipa_mcp.tools.dynamic import build_tool, is_read_only

        # Create a mock non-read-only command
        cmd = {
            "name": "user_add",
            "doc": "Add a user",
            "args": [{"name": "uid", "type": "str", "required": True}],
            "options": [],
        }

        tool = build_tool(cmd)
        assert not is_read_only("user_add")
        assert "on_behalf_of" in tool.inputSchema["properties"]
        assert (
            "Principal to act on behalf of"
            in tool.inputSchema["properties"]["on_behalf_of"]["description"]
        )

    def test_readonly_tool_no_on_behalf_of(self):
        """Test read-only tools don't have on_behalf_of parameter."""
        from freeipa_mcp.tools.dynamic import build_tool, is_read_only

        # Create a mock read-only command
        cmd = {
            "name": "user_find",
            "doc": "Find users",
            "args": [],
            "options": [],
        }

        tool = build_tool(cmd)
        assert is_read_only("user_find")
        assert "on_behalf_of" not in tool.inputSchema["properties"]


class TestBackwardCompatibility:
    """Tests for backward compatibility without delegation."""

    def test_delegation_disabled_no_env_vars(self):
        """Test everything works without delegation env vars."""
        with patch.dict(os.environ, {}, clear=True):
            config = DelegationConfig.from_env()
            assert config.enabled is False

            # OBOClient should initialize without errors
            client = OBOClient(config)
            assert client._client_secret is None

    def test_get_client_without_ccache(self):
        """Test get_client() works without ccache_path."""
        from freeipa_mcp.tools.common import get_client, save_server_config

        with patch(
            "freeipa_mcp.ipaclient.IPAThinClient._get_ca_cert", return_value=True
        ):
            save_server_config("ipa.test")
            client = get_client()
            assert client._ccache_path is None


# Test resolve_actor logic (will be in server.py)
class TestActorResolution:
    """Tests for actor resolution logic."""

    @patch("freeipa_mcp.server._detect_kerberos_principal")
    def test_resolve_actor_disabled(self, mock_detect):
        """Test _resolve_actor returns None when delegation disabled."""
        from freeipa_mcp.server import _resolve_actor

        # Delegation not initialized
        with patch("freeipa_mcp.server._delegation_config", None):
            actor = _resolve_actor("alice@REALM")
            assert actor is None

    @patch("freeipa_mcp.server._obo_client")
    @patch("freeipa_mcp.server._delegation_config")
    def test_resolve_actor_explicit(self, mock_config, mock_obo):
        """Test _resolve_actor uses explicit on_behalf_of param."""
        from freeipa_mcp.delegation import DelegatedToken
        from freeipa_mcp.server import _resolve_actor

        mock_config.enabled = True
        mock_actor = ActorContext(principal="alice@REALM", tool_identity="freeipa-mcp")
        mock_obo.get_delegated_token.return_value = DelegatedToken(
            access_token="token",
            actor=mock_actor,
            expires_in=300,
            delegation_rule=None,
        )

        with patch.dict(os.environ, {}, clear=True):
            actor = _resolve_actor("alice@REALM")
            assert actor is not None
            assert actor.principal == "alice@REALM"
            mock_obo.get_delegated_token.assert_called_once_with("alice@REALM")

    @patch("freeipa_mcp.server._obo_client")
    @patch("freeipa_mcp.server._delegation_config")
    def test_resolve_actor_env(self, mock_config, mock_obo):
        """Test _resolve_actor uses MCP_ON_BEHALF_OF env var."""
        from freeipa_mcp.delegation import DelegatedToken
        from freeipa_mcp.server import _resolve_actor

        mock_config.enabled = True
        mock_actor = ActorContext(principal="bob@REALM", tool_identity="freeipa-mcp")
        mock_obo.get_delegated_token.return_value = DelegatedToken(
            access_token="token",
            actor=mock_actor,
            expires_in=300,
            delegation_rule=None,
        )

        with patch.dict(os.environ, {"MCP_ON_BEHALF_OF": "bob@REALM"}, clear=True):
            actor = _resolve_actor(None)
            assert actor is not None
            assert actor.principal == "bob@REALM"

    @patch("freeipa_mcp.server._detect_kerberos_principal")
    @patch("freeipa_mcp.server._obo_client")
    @patch("freeipa_mcp.server._delegation_config")
    def test_resolve_actor_klist(self, mock_config, mock_obo, mock_detect):
        """Test _resolve_actor uses klist fallback."""
        from freeipa_mcp.delegation import DelegatedToken
        from freeipa_mcp.server import _resolve_actor

        mock_config.enabled = True
        mock_detect.return_value = "charlie@REALM"
        mock_actor = ActorContext(
            principal="charlie@REALM", tool_identity="freeipa-mcp"
        )
        mock_obo.get_delegated_token.return_value = DelegatedToken(
            access_token="token",
            actor=mock_actor,
            expires_in=300,
            delegation_rule=None,
        )

        with patch.dict(os.environ, {}, clear=True):
            actor = _resolve_actor(None)
            assert actor is not None
            assert actor.principal == "charlie@REALM"
            mock_detect.assert_called_once()

    @patch("freeipa_mcp.server._detect_kerberos_principal")
    @patch("freeipa_mcp.server._delegation_config")
    def test_resolve_actor_anonymous(self, mock_config, mock_detect):
        """Test _resolve_actor returns anonymous when no principal found."""
        from freeipa_mcp.server import _resolve_actor

        mock_config.enabled = True
        mock_detect.return_value = None

        with patch.dict(os.environ, {}, clear=True):
            actor = _resolve_actor(None)
            assert actor is not None
            assert actor.principal == "unknown"
            assert actor.tool_identity == "freeipa-mcp"
