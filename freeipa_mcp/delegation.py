# SPDX-License-Identifier: GPL-3.0-or-later

"""OAuth2 delegation identity for FreeIPA MCP server.

Provides actor context, delegation configuration, and OBO token exchange
for impersonation-based authentication to FreeIPA.
"""

from __future__ import annotations

import os
import socket
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests


@dataclass
class ActorContext:
    """Actor context for delegation-based identity.

    Represents the authenticated principal acting through the MCP server,
    with optional delegation metadata.
    """

    principal: str
    tool_identity: str
    delegation_rule: str | None = None
    scopes: list[str] | None = None
    spiffe_id: str | None = None

    @staticmethod
    def anonymous() -> "ActorContext":
        """Create anonymous actor context.

        Returns:
            ActorContext with unknown principal and freeipa-mcp tool identity
        """
        return ActorContext(principal="unknown", tool_identity="freeipa-mcp")

    def to_dict(self) -> dict:
        """Serialize to dictionary.

        Returns:
            Dictionary with principal, tool, delegation_rule keys
        """
        return {
            "principal": self.principal,
            "tool": self.tool_identity,
            "delegation_rule": self.delegation_rule,
        }


@dataclass
class DelegationConfig:
    """Configuration for OAuth2 delegation.

    All settings can be provided via environment variables:
    - FREEIPA_MCP_DELEGATION_ENABLED: Enable delegation (true/yes/1)
    - FREEIPA_MCP_OBO_URL: OBO exchange service URL
    - FREEIPA_MCP_CLIENT_ID: OAuth2 client ID
    - FREEIPA_MCP_CLIENT_SECRET_FILE: Path to client secret file
    - FREEIPA_MCP_TOKEN_ENDPOINT: OAuth2 token endpoint
    - FREEIPA_MCP_SCOPES: Comma-separated list of scopes
    - FREEIPA_MCP_SPIFFE_ID: SPIFFE ID for this service
    """

    enabled: bool = False
    obo_exchange_url: str = "http://localhost:8900"
    client_id: str = "freeipa-mcp"
    client_secret_file: str = ""
    token_endpoint: str = ""
    scopes: list[str] = field(default_factory=lambda: ["ipa:read", "ipa:write"])
    spiffe_id: str = ""

    @staticmethod
    def from_env() -> "DelegationConfig":
        """Load configuration from environment variables.

        Returns:
            DelegationConfig instance populated from env vars
        """
        enabled_str = os.environ.get("FREEIPA_MCP_DELEGATION_ENABLED", "").lower()
        enabled = enabled_str in ("true", "yes", "1")

        scopes_str = os.environ.get("FREEIPA_MCP_SCOPES", "")
        scopes = (
            [s.strip() for s in scopes_str.split(",") if s.strip()]
            if scopes_str
            else ["ipa:read", "ipa:write"]
        )

        return DelegationConfig(
            enabled=enabled,
            obo_exchange_url=os.environ.get(
                "FREEIPA_MCP_OBO_URL", "http://localhost:8900"
            ),
            client_id=os.environ.get("FREEIPA_MCP_CLIENT_ID", "freeipa-mcp"),
            client_secret_file=os.environ.get("FREEIPA_MCP_CLIENT_SECRET_FILE", ""),
            token_endpoint=os.environ.get("FREEIPA_MCP_TOKEN_ENDPOINT", ""),
            scopes=scopes,
            spiffe_id=os.environ.get("FREEIPA_MCP_SPIFFE_ID", ""),
        )


@dataclass
class DelegatedToken:
    """Delegated token from OBO exchange."""

    access_token: str
    actor: ActorContext
    expires_in: int
    delegation_rule: str | None


class OBOClient:
    """Client for OAuth2 On-Behalf-Of token exchange.

    Handles:
    1. Client credentials flow (get own token)
    2. RFC 8693 token exchange (get delegated token)
    3. Kerberos bridge (get delegated ccache)

    Tokens are cached until 60 seconds before expiry.
    """

    def __init__(self, config: DelegationConfig):
        """Initialize OBO client.

        Args:
            config: Delegation configuration

        Raises:
            ValueError: If delegation enabled but client_secret_file
                missing/unreadable/insecure
        """
        self.config = config
        self._client_secret: str | None = None
        self._own_token: str | None = None
        self._own_token_expiry: float = 0.0
        self._delegated_tokens: dict[tuple[str, frozenset[str]], tuple[str, float]] = {}

        if config.enabled:
            if not config.client_secret_file:
                raise ValueError(
                    "delegation.client_secret_file must be set "
                    "when delegation is enabled"
                )
            secret_path = Path(config.client_secret_file)
            if not secret_path.exists():
                raise ValueError(
                    f"Client secret file not found: {config.client_secret_file}"
                )
            try:
                self._client_secret = self._load_secret(secret_path)
            except Exception as e:
                raise ValueError(
                    f"Failed to read client secret "
                    f"from {config.client_secret_file}: {e}"
                ) from e

    def _load_secret(self, secret_path: Path) -> str:
        """Load and validate client secret file.

        Args:
            secret_path: Path to secret file

        Returns:
            Secret content (stripped)

        Raises:
            ValueError: If file permissions are not 0600
        """
        # Check file permissions (must be 0600)
        stat_info = secret_path.stat()
        mode = stat_info.st_mode & 0o777
        if mode != 0o600:
            raise ValueError(
                f"Client secret file must have 0600 permissions, found {oct(mode)}"
            )
        return secret_path.read_text().strip()

    def _build_actor_context(
        self,
        on_behalf_of: str,
        scopes: list[str],
        delegation_rule: str | None = None,
    ) -> ActorContext:
        """Build ActorContext from delegation data.

        Args:
            on_behalf_of: Principal being delegated to
            scopes: Granted scopes
            delegation_rule: Optional delegation rule name

        Returns:
            ActorContext instance
        """
        return ActorContext(
            principal=on_behalf_of,
            tool_identity=self.config.client_id,
            scopes=scopes,
            spiffe_id=self.config.spiffe_id or None,
        )

    def get_own_token(self) -> str:
        """Get own JWT via client credentials flow.

        Returns cached token if valid, otherwise fetches fresh token.

        Returns:
            JWT access token for this MCP server

        Raises:
            ValueError: If token endpoint not configured
            requests.RequestException: On network/HTTP errors
        """
        # Check cache (with 60s early expiry)
        now = time.monotonic()
        if self._own_token and (self._own_token_expiry - 60) > now:
            return self._own_token

        if not self.config.token_endpoint:
            raise ValueError("delegation.token_endpoint must be configured")

        # Client credentials flow
        data = {
            "grant_type": "client_credentials",
            "client_id": self.config.client_id,
            "client_secret": self._client_secret,
        }

        resp = requests.post(
            self.config.token_endpoint,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()

        self._own_token = result["access_token"]
        expires_in = result.get("expires_in", 3600)
        self._own_token_expiry = now + expires_in

        return self._own_token

    def get_delegated_token(
        self,
        on_behalf_of: str,
        scopes: list[str] | None = None,
    ) -> DelegatedToken:
        """Exchange own token for delegated token via RFC 8693.

        Args:
            on_behalf_of: Principal to act on behalf of (e.g., "alice@REALM")
            scopes: Scopes to request (defaults to config.scopes)

        Returns:
            DelegatedToken with access token and actor context

        Raises:
            requests.RequestException: On network/HTTP errors
        """
        use_scopes = scopes or self.config.scopes
        cache_key = (on_behalf_of, frozenset(use_scopes))

        # Check cache
        now = time.monotonic()
        if cache_key in self._delegated_tokens:
            token, expiry = self._delegated_tokens[cache_key]
            if (expiry - 60) > now:
                # Build ActorContext from cached data
                actor = self._build_actor_context(on_behalf_of, list(use_scopes))
                # We don't cache delegation_rule, so return None
                return DelegatedToken(
                    access_token=token,
                    actor=actor,
                    expires_in=int(expiry - now),
                    delegation_rule=None,
                )

        # Fetch fresh delegated token
        own_token = self.get_own_token()
        hostname = socket.gethostname()

        data = {
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "subject_token": own_token,
            "requested_subject": on_behalf_of,
            "scope": " ".join(use_scopes),
            "on_host": hostname,
        }

        url = f"{self.config.obo_exchange_url}/token"
        resp = requests.post(
            url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()

        delegated_token = result["access_token"]
        expires_in = result.get("expires_in", 300)
        returned_scope = result.get("scope", " ".join(use_scopes))

        # Cache the token
        self._delegated_tokens[cache_key] = (delegated_token, now + expires_in)

        actor = self._build_actor_context(on_behalf_of, returned_scope.split())

        return DelegatedToken(
            access_token=delegated_token,
            actor=actor,
            expires_in=expires_in,
            delegation_rule=None,  # Not returned by token exchange endpoint
        )

    def get_delegated_ccache(
        self,
        on_behalf_of: str,
        target_service: str | None = None,
    ) -> str:
        """Get delegated Kerberos ccache via OBO bridge.

        This is NOT cached — each call returns a fresh ccache file.

        Args:
            on_behalf_of: Principal to act on behalf of (e.g., "alice@REALM")
            target_service: Optional service principal (e.g., "HTTP/ipa.example.com")

        Returns:
            Path to ccache file (e.g., "/tmp/krb5cc_...")

        Raises:
            requests.RequestException: On network/HTTP errors
        """
        own_token = self.get_own_token()
        hostname = socket.gethostname()

        data = {
            "subject_token": own_token,
            "requested_subject": on_behalf_of,
            "scope": " ".join(self.config.scopes),
            "on_host": hostname,
            "return_contents": "true",
        }

        if target_service:
            data["target_service"] = target_service

        url = f"{self.config.obo_exchange_url}/kerberos"
        resp = requests.post(
            url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()

        return result["ccache"]
