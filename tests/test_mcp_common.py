# SPDX-License-Identifier: GPL-3.0-or-later
from unittest.mock import MagicMock, patch

import pytest


def test_to_cli_name():
    from freeipa_mcp.tools.common import to_cli_name
    assert to_cli_name("user_show") == "user-show"
    assert to_cli_name("cert_request") == "cert-request"
    assert to_cli_name("ping") == "ping"


def test_to_api_name():
    from freeipa_mcp.tools.common import to_api_name
    assert to_api_name("user-show") == "user_show"
    assert to_api_name("cert-request") == "cert_request"
    assert to_api_name("ping") == "ping"


def test_save_and_load_server_config(tmp_path):
    from freeipa_mcp.tools.common import load_server_config, save_server_config
    with patch("freeipa_mcp.tools.common.get_cache_dir", return_value=tmp_path):
        save_server_config("ipa.example.com")
        assert load_server_config() == "ipa.example.com"


def test_load_server_config_missing(tmp_path):
    from freeipa_mcp.tools.common import load_server_config
    with patch("freeipa_mcp.tools.common.get_cache_dir", return_value=tmp_path):
        assert load_server_config() is None


def test_get_client_raises_when_no_config():
    from freeipa_mcp.tools.common import get_client
    with patch("freeipa_mcp.tools.common.load_server_config", return_value=None):
        with pytest.raises(RuntimeError, match="No FreeIPA server configured"):
            get_client()


def test_get_client_returns_ipaclient():
    from freeipa_mcp.tools.common import get_client
    from freeipa_mcp.ipaclient import IPAThinClient
    with (
        patch(
            "freeipa_mcp.tools.common.load_server_config",
            return_value="ipa.example.com",
        ),
        patch("freeipa_mcp.tools.common.IPAThinClient") as mock_cls,
    ):
        mock_cls.return_value = MagicMock(spec=IPAThinClient)
        client = get_client()
        mock_cls.assert_called_once_with("ipa.example.com")
        assert client is mock_cls.return_value


def test_ipa_type_to_json_schema():
    from freeipa_mcp.tools.common import ipa_type_to_json_schema
    assert ipa_type_to_json_schema("str") == {"type": "string"}
    assert ipa_type_to_json_schema("int") == {"type": "integer"}
    assert ipa_type_to_json_schema("bool") == {"type": "boolean"}
    assert ipa_type_to_json_schema("list") == {
        "type": "array",
        "items": {"type": "string"},
    }
    assert ipa_type_to_json_schema("dict") == {"type": "object"}
    assert ipa_type_to_json_schema("unknown") == {"type": "string"}
