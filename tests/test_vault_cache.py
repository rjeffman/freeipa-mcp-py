# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for KRA configuration caching."""

import base64
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock

from freeipa_mcp.vault_cache import KRAConfigCache


class TestKRAConfigCache:
    """Test KRA configuration caching."""

    def _make_mock_client(self, cache_dir: Path):
        """Create a mock client with get_cache_dir method."""
        client = Mock()
        client.get_cache_dir.return_value = cache_dir
        return client

    def test_cache_save_and_load(self):
        """Save and load cache successfully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            client = self._make_mock_client(Path(tmpdir))
            cache = KRAConfigCache(client)

            cert_der = b"fake_cert_data_123"
            algo = "aes-128-cbc"

            cache.save(cert_der, algo)
            loaded = cache.load()

            assert loaded is not None
            loaded_cert, loaded_algo = loaded
            assert loaded_cert == cert_der
            assert loaded_algo == algo

    def test_cache_missing_returns_none(self):
        """Load returns None if cache doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            client = self._make_mock_client(Path(tmpdir))
            cache = KRAConfigCache(client)

            loaded = cache.load()
            assert loaded is None

    def test_cache_creates_directory(self):
        """Cache save creates directory if missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            client = self._make_mock_client(Path(tmpdir))
            cache = KRAConfigCache(client)

            cache.save(b"cert", "aes-128-cbc")

            assert cache.cache_file.exists()
            assert cache.cache_file.parent.exists()

    def test_cache_file_format(self):
        """Cache file has correct JSON format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            client = self._make_mock_client(Path(tmpdir))
            cache = KRAConfigCache(client)

            cert_der = b"cert_data"
            algo = "des-ede3-cbc"

            cache.save(cert_der, algo)

            # Verify JSON structure
            data = json.loads(cache.cache_file.read_text())
            assert "transport_cert" in data
            assert "wrapping_algo" in data
            assert data["wrapping_algo"] == algo

            # Verify cert is base64
            decoded_cert = base64.b64decode(data["transport_cert"])
            assert decoded_cert == cert_der

    def test_cache_corrupted_returns_none(self):
        """Load returns None if cache file corrupted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            client = self._make_mock_client(Path(tmpdir))
            cache = KRAConfigCache(client)

            # Create corrupted cache file
            cache.cache_dir.mkdir(parents=True, exist_ok=True)
            cache.cache_file.write_text("invalid json{")

            loaded = cache.load()
            assert loaded is None

    def test_cache_missing_cert_returns_none(self):
        """Load returns None if cache missing transport_cert."""
        with tempfile.TemporaryDirectory() as tmpdir:
            client = self._make_mock_client(Path(tmpdir))
            cache = KRAConfigCache(client)

            # Create cache without transport_cert
            cache.cache_dir.mkdir(parents=True, exist_ok=True)
            cache.cache_file.write_text(json.dumps({"wrapping_algo": "aes-128-cbc"}))

            loaded = cache.load()
            assert loaded is None

    def test_cache_defaults_algorithm(self):
        """Load defaults to aes-128-cbc if algo missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            client = self._make_mock_client(Path(tmpdir))
            cache = KRAConfigCache(client)

            cert_der = b"cert"
            # Save without algo
            cache.cache_dir.mkdir(parents=True, exist_ok=True)
            data = {"transport_cert": base64.b64encode(cert_der).decode("ascii")}
            cache.cache_file.write_text(json.dumps(data))

            loaded = cache.load()
            assert loaded is not None
            _, algo = loaded
            assert algo == "aes-128-cbc"

    def test_cache_clear(self):
        """Clear removes cache file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            client = self._make_mock_client(Path(tmpdir))
            cache = KRAConfigCache(client)

            cache.save(b"cert", "aes-128-cbc")
            assert cache.cache_file.exists()

            cache.clear()
            assert not cache.cache_file.exists()

    def test_cache_clear_missing_file(self):
        """Clear doesn't fail if file missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            client = self._make_mock_client(Path(tmpdir))
            cache = KRAConfigCache(client)

            # Should not raise
            cache.clear()

    def test_cache_server_separation(self):
        """Different servers use different cache directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            server1_dir = base_dir / "server1.example.com"
            server2_dir = base_dir / "server2.example.com"
            server1_dir.mkdir(parents=True, exist_ok=True)
            server2_dir.mkdir(parents=True, exist_ok=True)

            client1 = self._make_mock_client(server1_dir)
            client2 = self._make_mock_client(server2_dir)

            cache1 = KRAConfigCache(client1)
            cache2 = KRAConfigCache(client2)

            cache1.save(b"cert1", "aes-128-cbc")
            cache2.save(b"cert2", "des-ede3-cbc")

            loaded1 = cache1.load()
            loaded2 = cache2.load()

            assert loaded1 is not None
            assert loaded2 is not None
            assert loaded1[0] == b"cert1"
            assert loaded2[0] == b"cert2"
            assert loaded1[1] == "aes-128-cbc"
            assert loaded2[1] == "des-ede3-cbc"

    def test_cache_save_failure_silent(self):
        """Cache save failure doesn't raise exception."""
        # Use invalid path
        client = self._make_mock_client(Path("/nonexistent/path"))
        cache = KRAConfigCache(client)

        # Should not raise
        cache.save(b"cert", "aes-128-cbc")
