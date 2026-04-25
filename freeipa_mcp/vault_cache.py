# SPDX-License-Identifier: GPL-3.0-or-later
"""
KRA configuration caching for vault operations.

Caches the KRA transport certificate and wrapping algorithm to avoid repeated
vaultconfig_show calls. Cache is stored per-server in the user's cache directory.
"""

import base64
import json
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .ipaclient import IPAThinClient


class KRAConfigCache:
    """
    Cache for KRA transport certificate and wrapping algorithm.

    Cache location: ~/.cache/freeipa-mcp-py/{server}/kra-config.json
    Cache format: {"transport_cert": "base64...", "wrapping_algo": "aes-128-cbc"}
    """

    def __init__(self, client: "IPAThinClient"):
        """
        Initialize KRA config cache.

        Args:
            client: IPA client instance (used to get server-specific cache dir)
        """
        self.cache_dir = client.get_cache_dir()
        self.cache_file = self.cache_dir / "kra-config.json"

    def load(self) -> Optional[tuple[bytes, str]]:
        """
        Load cached KRA configuration.

        Returns:
            (transport_cert_der, wrapping_algo) if cache exists, None otherwise
        """
        if not self.cache_file.exists():
            return None

        try:
            data = json.loads(self.cache_file.read_text())
            cert_b64 = data.get("transport_cert")
            algo = data.get("wrapping_algo", "aes-128-cbc")

            if not cert_b64:
                return None

            cert_der = base64.b64decode(cert_b64)
            return cert_der, algo
        except Exception:
            # Cache corrupted - return None to trigger refresh
            return None

    def save(self, cert_der: bytes, algo: str) -> None:
        """
        Save KRA configuration to cache.

        Args:
            cert_der: DER-encoded transport certificate
            algo: Wrapping algorithm name
        """
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            cache_data = {
                "transport_cert": base64.b64encode(cert_der).decode("ascii"),
                "wrapping_algo": algo,
            }
            self.cache_file.write_text(json.dumps(cache_data, indent=2))
        except Exception:
            # Cache write failure is non-fatal - just log and continue
            pass

    def clear(self) -> None:
        """Remove cached configuration."""
        try:
            self.cache_file.unlink(missing_ok=True)
        except Exception:
            pass
