# SPDX-License-Identifier: GPL-3.0-or-later
"""
Vault management tools for FreeIPA MCP.

Implements client-side vault operations with encryption/decryption:
- vaultconfig-show: Display KRA configuration
- vault-add: Create a vault
- vault-mod: Modify vault metadata
- vault-archive: Store encrypted data in vault
- vault-retrieve: Retrieve and decrypt vault data

All commands support dynamic parameters and perform client-side cryptography.
"""

import base64
import json
from pathlib import Path
from typing import Optional

from ..ipaclient import IPAThinClient
from ..vault_cache import KRAConfigCache
from ..vault_crypto import (
    VaultCryptoError,
    cert_rsa_encrypt_oaep,
    cert_rsa_encrypt_pkcs1v15,
    derive_symmetric_key,
    fernet_decrypt,
    fernet_encrypt,
    generate_random_bytes,
    generate_vault_session_key,
    pem_rsa_decrypt_oaep,
    pem_rsa_encrypt_oaep,
    unwrap_vault_data,
    wrap_vault_data,
)
from . import dynamic
from ._vault_dialog import (
    get_password_from_file_or_dialog,
    save_or_display_vault_data,
)
from .common import get_client

MAX_VAULT_DATA_SIZE = 1 << 20  # 1 MiB
DEFAULT_WRAPPING_ALGO = "aes-128-cbc"
VAULT_SELECTOR_OPTIONS = ["user", "shared", "service", "username"]


# ── Helper Functions ──────────────────────────────────────────────────────────


def extract_base64_value(data) -> bytes:
    """
    Extract base64-encoded bytes from FreeIPA response format.

    FreeIPA returns binary data as {"__base64__": "encoded_data"} or as
    plain base64 strings.

    Args:
        data: Server response data (dict, str, or bytes)

    Returns:
        Decoded bytes

    Raises:
        ValueError: If data format is invalid
    """
    if isinstance(data, bytes):
        return data
    if isinstance(data, dict) and "__base64__" in data:
        return base64.b64decode(data["__base64__"])
    if isinstance(data, str):
        return base64.b64decode(data)
    raise ValueError(f"Invalid base64 data format: {type(data).__name__}")


def get_input_data(arguments: dict) -> bytes:
    """
    Read vault data from --in file.

    Args:
        arguments: Command arguments

    Returns:
        File contents as bytes

    Raises:
        ValueError: If file not specified, not found, or too large
    """
    in_file = arguments.get("in")
    if not in_file:
        raise ValueError("Required parameter 'in' not provided")

    path = Path(in_file)
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {in_file}")

    data = path.read_bytes()
    if len(data) > MAX_VAULT_DATA_SIZE:
        raise ValueError(
            f"Data exceeds maximum vault size of {MAX_VAULT_DATA_SIZE} bytes"
        )

    return data


def get_private_key_pem(arguments: dict) -> Optional[bytes]:
    """
    Get PEM private key from arguments.

    Args:
        arguments: Command arguments (may contain 'private_key' or 'private_key_file')

    Returns:
        PEM private key bytes, or None if not provided

    Raises:
        FileNotFoundError: If private_key_file specified but not found
    """
    if "private_key" in arguments:
        return arguments["private_key"].encode("utf-8")

    if "private_key_file" in arguments:
        path = Path(arguments["private_key_file"])
        if not path.exists():
            raise FileNotFoundError(
                f"Private key file not found: {arguments['private_key_file']}"
            )
        return path.read_bytes()

    return None


def vault_selector_options(arguments: dict) -> dict:
    """
    Extract vault selector options for RPC calls.

    Args:
        arguments: Full command arguments

    Returns:
        Dictionary containing only vault selector options
    """
    return {k: v for k, v in arguments.items() if k in VAULT_SELECTOR_OPTIONS}


def get_vaultconfig(
    client: IPAThinClient, force_refresh: bool = False
) -> tuple[bytes, str]:
    """
    Get KRA transport certificate and wrapping algorithm.

    Uses cache unless force_refresh is True.

    Args:
        client: IPA client instance
        force_refresh: If True, bypass cache and fetch from server

    Returns:
        (transport_cert_der, wrapping_algo) tuple

    Raises:
        Exception: If vaultconfig_show fails or response invalid
    """
    # Get server-specific cache
    cache = KRAConfigCache(client)

    # Try cache first
    if not force_refresh:
        cached = cache.load()
        if cached:
            return cached

    # Fetch from server
    result = client.command("vaultconfig_show")
    inner = result.get("result", {})

    # Extract transport cert
    cert_data = inner.get("transport_cert")
    if isinstance(cert_data, list):
        cert_data = cert_data[0] if cert_data else None

    if not cert_data:
        raise ValueError("vaultconfig_show returned no transport_cert")

    # Cert may be in __base64__ format, plain base64 string, or bytes
    cert_der = extract_base64_value(cert_data)

    # Extract wrapping algorithm (defaults to AES-128-CBC)
    algo_data = inner.get("wrapping_default_algorithm")
    if isinstance(algo_data, list):
        algo = algo_data[0] if algo_data else DEFAULT_WRAPPING_ALGO
    else:
        algo = algo_data or DEFAULT_WRAPPING_ALGO

    # Cache for future use
    cache.save(cert_der, algo)
    return cert_der, algo


def wrap_session_key_with_fallback(
    client: IPAThinClient, session_key: bytes, cached_cert: bytes
) -> bytes:
    """
    RSA-wrap session key with KRA transport cert, with fallback logic.

    Attempts:
    1. PKCS1v15 with cached cert
    2. OAEP with cached cert (if PKCS1v15 rejected by FIPS)
    3. PKCS1v15 with fresh cert
    4. OAEP with fresh cert

    Args:
        client: IPA client instance
        session_key: Session key bytes to wrap
        cached_cert: Cached KRA transport certificate DER

    Returns:
        RSA-encrypted session key

    Raises:
        VaultCryptoError: If all attempts fail
    """
    # Attempt 1 & 2: Try cached cert with PKCS1v15, fallback to OAEP
    try:
        return cert_rsa_encrypt_pkcs1v15(session_key, cached_cert)
    except VaultCryptoError:
        try:
            return cert_rsa_encrypt_oaep(session_key, cached_cert)
        except VaultCryptoError:
            pass

    # Attempt 3 & 4: Refresh cert and retry
    try:
        fresh_cert, _ = get_vaultconfig(client, force_refresh=True)
        try:
            return cert_rsa_encrypt_pkcs1v15(session_key, fresh_cert)
        except VaultCryptoError:
            return cert_rsa_encrypt_oaep(session_key, fresh_cert)
    except Exception as e:
        raise VaultCryptoError(f"Failed to wrap session key: {e}") from e


# ── Vault Commands ────────────────────────────────────────────────────────────


def execute_vaultconfig_show(arguments: dict) -> str:
    """
    Show vault configuration (KRA transport cert and wrapping algorithm).

    Args:
        arguments: Command arguments

    Returns:
        JSON-formatted result
    """
    client = get_client()
    result = client.command("vaultconfig_show", **arguments)
    return json.dumps(result, indent=2, default=str)


def execute_vault_add(arguments: dict) -> str:
    """
    Create a new vault.

    Automatically generates salt for symmetric vaults if not provided.
    Defaults vault type to 'standard' if not specified.

    Args:
        arguments: Command arguments

    Returns:
        JSON-formatted result
    """
    client = get_client()

    # Set default vault type
    if "ipavaulttype" not in arguments:
        arguments["ipavaulttype"] = "standard"

    vault_type = arguments["ipavaulttype"]

    # Generate salt for symmetric vaults if not provided
    if vault_type == "symmetric" and "ipavaultsalt" not in arguments:
        salt = generate_random_bytes(16)
        arguments["ipavaultsalt"] = base64.b64encode(salt).decode("ascii")

    # Extract vault name (first positional argument in cn format)
    vault_name = arguments.get("cn")
    if not vault_name:
        raise ValueError("Vault name (cn) required")

    # Remove cn from options (it's positional)
    options = {k: v for k, v in arguments.items() if k != "cn"}

    # Build RPC call
    result = client.command("vault_add_internal", vault_name, **options)
    return json.dumps(result, indent=2, default=str)


def execute_vault_mod(arguments: dict) -> str:
    """
    Modify a vault.

    Args:
        arguments: Command arguments

    Returns:
        JSON-formatted result
    """
    client = get_client()

    vault_name = arguments.get("cn")
    if not vault_name:
        raise ValueError("Vault name (cn) required")

    # Remove cn from options (it's positional)
    options = {k: v for k, v in arguments.items() if k != "cn"}

    result = client.command("vault_mod_internal", vault_name, **options)
    return json.dumps(result, indent=2, default=str)


def execute_vault_archive(arguments: dict) -> str:
    """
    Archive data into a vault with client-side encryption.

    Flow:
    1. Read data from --in file
    2. Fetch vault metadata to determine type
    3. Encrypt data according to vault type
    4. Wrap encrypted data in session-key envelope
    5. Send to vault_archive_internal

    Args:
        arguments: Command arguments including 'in', vault selectors, etc.

    Returns:
        JSON-formatted result

    Raises:
        ValueError: If required parameters missing or data too large
        VaultCryptoError: If encryption fails
    """
    client = get_client()
    data = get_input_data(arguments)

    vault_name = arguments.get("cn")
    if not vault_name:
        raise ValueError("Vault name (cn) required")

    # Get vault metadata
    selector = vault_selector_options(arguments)
    vault_info = client.command("vault_show", vault_name, **selector)
    vault_result = vault_info.get("result", {})

    # Extract vault type and metadata
    vault_type_data = vault_result.get("ipavaulttype", ["standard"])
    vault_type = (
        vault_type_data[0] if isinstance(vault_type_data, list) else vault_type_data
    )

    # Encrypt data according to vault type
    if vault_type == "symmetric":
        password = get_password_from_file_or_dialog(arguments, vault_name, "archive")
        salt_data = vault_result.get("ipavaultsalt")
        if not salt_data:
            raise ValueError("Symmetric vault has no salt")
        salt_item = salt_data[0] if isinstance(salt_data, list) else salt_data
        salt = extract_base64_value(salt_item)

        key = derive_symmetric_key(password.encode("utf-8"), salt)
        fernet_token = fernet_encrypt(data, key)
        token_str = fernet_token.decode("ascii")
        json_vault_data = {"data": token_str}

    elif vault_type == "asymmetric":
        pubkey_data = vault_result.get("ipavaultpublickey")
        if not pubkey_data:
            raise ValueError("Asymmetric vault has no public key")
        pubkey = pubkey_data[0] if isinstance(pubkey_data, list) else pubkey_data
        if isinstance(pubkey, str):
            pubkey = pubkey.encode("utf-8")

        encrypted = pem_rsa_encrypt_oaep(data, pubkey)
        json_vault_data = {"data": base64.b64encode(encrypted).decode("ascii")}

    else:  # standard
        json_vault_data = {"data": base64.b64encode(data).decode("ascii")}

    # Get KRA config
    cert_der, algo = get_vaultconfig(client, force_refresh=False)

    # Wrap data in session-key envelope
    json_bytes = json.dumps(json_vault_data).encode("utf-8")
    session_key = generate_vault_session_key(algo)
    nonce, cbc_vault_data = wrap_vault_data(algo, session_key, json_bytes)
    enc_session_key = wrap_session_key_with_fallback(client, session_key, cert_der)

    # Build RPC options (encode bytes as base64)
    rpc_options = selector.copy()
    rpc_options["nonce"] = base64.b64encode(nonce).decode("ascii")
    rpc_options["session_key"] = base64.b64encode(enc_session_key).decode("ascii")
    rpc_options["vault_data"] = base64.b64encode(cbc_vault_data).decode("ascii")
    rpc_options["wrapping_algo"] = algo

    # Call server
    result = client.command("vault_archive_internal", vault_name, **rpc_options)

    # Return success message
    return json.dumps(
        {"summary": "Successfully archived data into vault.", "result": result},
        indent=2,
        default=str,
    )


def execute_vault_retrieve(arguments: dict) -> str:
    """
    Retrieve data from a vault with client-side decryption.

    Flow:
    1. Fetch vault metadata to determine type
    2. Generate session key and wrap with KRA cert
    3. Call vault_retrieve_internal with wrapped session key
    4. Unwrap response with session key
    5. Decrypt inner data according to vault type
    6. Write to --out file or return base64

    Args:
        arguments: Command arguments including vault selectors, --out, etc.

    Returns:
        JSON-formatted result with summary

    Raises:
        ValueError: If required parameters missing
        VaultCryptoError: If decryption fails
    """
    client = get_client()

    vault_name = arguments.get("cn")
    if not vault_name:
        raise ValueError("Vault name (cn) required")

    selector = vault_selector_options(arguments)

    # Get vault metadata
    vault_info = client.command("vault_show", vault_name, **selector)
    vault_result = vault_info.get("result", {})

    vault_type_data = vault_result.get("ipavaulttype", ["standard"])
    vault_type = (
        vault_type_data[0] if isinstance(vault_type_data, list) else vault_type_data
    )

    # Get KRA config and generate session key
    cert_der, algo = get_vaultconfig(client, force_refresh=False)
    session_key = generate_vault_session_key(algo)
    enc_session_key = wrap_session_key_with_fallback(client, session_key, cert_der)

    # Build RPC options (encode bytes as base64)
    rpc_options = selector.copy()
    rpc_options["session_key"] = base64.b64encode(enc_session_key).decode("ascii")
    rpc_options["wrapping_algo"] = algo

    # Call server
    result = client.command("vault_retrieve_internal", vault_name, **rpc_options)
    inner = result.get("result", {})

    # Extract wrapped vault data
    nonce_data = inner.get("nonce")
    vault_data = inner.get("vault_data")

    if not nonce_data or not vault_data:
        raise ValueError("vault_retrieve_internal returned incomplete data")

    nonce_item = nonce_data[0] if isinstance(nonce_data, list) else nonce_data
    cbc_item = vault_data[0] if isinstance(vault_data, list) else vault_data

    nonce = extract_base64_value(nonce_item)
    cbc_data = extract_base64_value(cbc_item)

    # Unwrap with session key
    json_bytes = unwrap_vault_data(algo, session_key, nonce, cbc_data)
    json_data = json.loads(json_bytes)
    data_str = json_data.get("data")

    if not data_str:
        raise ValueError("Vault data JSON missing 'data' field")

    # Decrypt according to vault type
    if vault_type == "symmetric":
        password = get_password_from_file_or_dialog(arguments, vault_name, "retrieve")
        salt_data = vault_result.get("ipavaultsalt")
        if not salt_data:
            raise ValueError("Symmetric vault has no salt")
        salt_item = salt_data[0] if isinstance(salt_data, list) else salt_data
        salt = extract_base64_value(salt_item)

        key = derive_symmetric_key(password.encode("utf-8"), salt)
        raw_data = fernet_decrypt(data_str.encode("ascii"), key)

    elif vault_type == "asymmetric":
        privkey_pem = get_private_key_pem(arguments)
        if not privkey_pem:
            raise ValueError("Asymmetric vault retrieve requires private_key_file")

        enc_data = base64.b64decode(data_str)
        raw_data = pem_rsa_decrypt_oaep(enc_data, privkey_pem)

    else:  # standard
        raw_data = base64.b64decode(data_str)

    # Output data securely - never return to AI agent
    message = save_or_display_vault_data(arguments, vault_name, raw_data)

    return json.dumps({"summary": message}, indent=2)


# ── Command Registration ──────────────────────────────────────────────────────

# Register custom executors for vault commands
dynamic.register_custom_executor("vaultconfig-show", execute_vaultconfig_show)
dynamic.register_custom_executor("vault-add", execute_vault_add)
dynamic.register_custom_executor("vault-mod", execute_vault_mod)
dynamic.register_custom_executor("vault-archive", execute_vault_archive)
dynamic.register_custom_executor("vault-retrieve", execute_vault_retrieve)
