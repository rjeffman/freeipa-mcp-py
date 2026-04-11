"""
Minimal IPA Client - JSON-RPC interface to FreeIPA servers.

This module provides a lightweight client for interacting with FreeIPA
servers via JSON-RPC. It requires Kerberos authentication (existing tickets
via kinit) and returns pure Python dictionaries suitable for MCP integration.

Example:
    >>> from ipaclient import IPAClient
    >>> client = IPAClient("ipa.example.com")
    >>> result = client.ping()
    >>> print(result["summary"])
    IPA server version 4.9.8. API version 2.251

Dependencies:
    - requests: HTTP client
    - requests-gssapi: Kerberos authentication
"""

from typing import Dict, List, Optional, Any
import requests
from requests_gssapi import HTTPSPNEGOAuth


__version__ = "0.1.0"
__all__ = [
    "IPAClient",
    "IPAError",
    "IPAConnectionError",
    "IPAAuthenticationError",
    "IPAServerError",
    "IPASchemaError",
    "IPAValidationError",
]


# ============================================================================
# Exceptions
# ============================================================================


class IPAError(Exception):
    """Base exception for all IPA client errors.

    All IPA exceptions include a `.to_dict()` method for easy serialization
    in MCP server responses.

    Attributes:
        message: Human-readable error message
        code: Error code (defaults to class name)
        data: Additional error context
    """

    def __init__(
        self,
        message: str,
        code: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
    ):
        """Initialize IPA error.

        Args:
            message: Human-readable error message
            code: Optional error code (defaults to class name)
            data: Optional additional error context
        """
        super().__init__(message)
        self.message = message
        self.code = code or self.__class__.__name__
        self.data = data or {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dict for MCP integration.

        Returns:
            Dictionary with error details suitable for JSON serialization.
        """
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "data": self.data,
            }
        }


class IPAConnectionError(IPAError):
    """Network or connection failure."""

    pass


class IPAAuthenticationError(IPAError):
    """Kerberos authentication failure."""

    pass


class IPAServerError(IPAError):
    """IPA server returned an error."""

    pass


class IPASchemaError(IPAError):
    """Schema fetch or parse failure."""

    pass


class IPAValidationError(IPAError):
    """Invalid parameters or arguments."""

    pass
