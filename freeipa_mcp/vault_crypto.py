# SPDX-License-Identifier: GPL-3.0-or-later
"""
Vault cryptography operations for FreeIPA vault management.

Implements client-side encryption/decryption for vault archive and retrieve
operations. Supports three vault types:
- standard: Base64 encoding only (no encryption)
- symmetric: PBKDF2 + Fernet encryption with password
- asymmetric: RSA-OAEP encryption with public/private keys

Python equivalent of mutqu's ipa-crypto/src/vault.rs.
"""

import base64
import os
from typing import cast

from cryptography.fernet import Fernet as CryptoFernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
from cryptography.hazmat.primitives.asymmetric.rsa import (
    RSAPrivateKey,
    RSAPublicKey,
)
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.x509 import load_der_x509_certificate

# Constants
PBKDF2_ITERATIONS = 100_000
PBKDF2_KEY_LENGTH = 32  # 16 bytes for signing + 16 for encryption
FERNET_VERSION = 0x80
MAX_VAULT_DATA_SIZE = 1 << 20  # 1 MiB


class VaultCryptoError(Exception):
    """Vault cryptography operation failed."""

    pass


# ── PBKDF2 Key Derivation ─────────────────────────────────────────────────────


def derive_symmetric_key(password: bytes, salt: bytes) -> bytes:
    """
    Derive a 32-byte symmetric key from password and salt.

    Uses PBKDF2-HMAC-SHA256 with 100,000 iterations, matching Python FreeIPA
    client and mutqu implementations.

    Args:
        password: Password bytes
        salt: Random salt bytes

    Returns:
        32-byte key (16 for HMAC-SHA256 + 16 for AES-128-CBC)

    Raises:
        VaultCryptoError: If key derivation fails
    """
    try:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=PBKDF2_KEY_LENGTH,
            salt=salt,
            iterations=PBKDF2_ITERATIONS,
        )
        return kdf.derive(password)
    except Exception as e:
        raise VaultCryptoError(f"PBKDF2 key derivation failed: {e}") from e


# ── Fernet Encryption ─────────────────────────────────────────────────────────


def fernet_encrypt(data: bytes, key: bytes) -> bytes:
    """
    Encrypt data using Fernet (AES-128-CBC + HMAC-SHA256).

    Returns a URL-safe base64-encoded Fernet token compatible with Python's
    cryptography.fernet.Fernet.

    Token structure:
        [version:1][timestamp:8][IV:16][ciphertext:variable][HMAC:32]

    Args:
        data: Plaintext to encrypt
        key: 32-byte key from derive_symmetric_key()

    Returns:
        URL-safe base64 Fernet token (ASCII bytes)

    Raises:
        VaultCryptoError: If encryption fails or key is wrong length
    """
    if len(key) != PBKDF2_KEY_LENGTH:
        raise VaultCryptoError(f"Fernet key must be 32 bytes, got {len(key)}")

    try:
        fernet = CryptoFernet(base64.urlsafe_b64encode(key))
        return fernet.encrypt(data)
    except Exception as e:
        raise VaultCryptoError(f"Fernet encryption failed: {e}") from e


def fernet_decrypt(token: bytes, key: bytes) -> bytes:
    """
    Decrypt a Fernet token.

    Verifies HMAC-SHA256 signature and decrypts using AES-128-CBC.

    Args:
        token: Fernet token (URL-safe base64 ASCII bytes)
        key: 32-byte key from derive_symmetric_key()

    Returns:
        Decrypted plaintext

    Raises:
        VaultCryptoError: If decryption fails, HMAC invalid, or key wrong
    """
    if len(key) != PBKDF2_KEY_LENGTH:
        raise VaultCryptoError(f"Fernet key must be 32 bytes, got {len(key)}")

    try:
        fernet = CryptoFernet(base64.urlsafe_b64encode(key))
        return fernet.decrypt(token)
    except Exception as e:
        raise VaultCryptoError(f"Fernet decryption failed: {e}") from e


# ── RSA Transport Encryption ──────────────────────────────────────────────────


def cert_rsa_encrypt_pkcs1v15(data: bytes, cert_der: bytes) -> bytes:
    """
    RSA-PKCS1v15-encrypt data with public key from DER certificate.

    May fail in FIPS mode; use cert_rsa_encrypt_oaep() as fallback.

    Args:
        data: Data to encrypt
        cert_der: DER-encoded X.509 certificate

    Returns:
        RSA-encrypted ciphertext

    Raises:
        VaultCryptoError: If encryption fails
    """
    try:
        cert = load_der_x509_certificate(cert_der)
        public_key = cast(RSAPublicKey, cert.public_key())
        ciphertext = public_key.encrypt(data, asym_padding.PKCS1v15())
        return ciphertext
    except Exception as e:
        raise VaultCryptoError(f"RSA PKCS1v15 encryption failed: {e}") from e


def cert_rsa_encrypt_oaep(data: bytes, cert_der: bytes) -> bytes:
    """
    RSA-OAEP-SHA256-encrypt data with public key from DER certificate.

    Args:
        data: Data to encrypt
        cert_der: DER-encoded X.509 certificate

    Returns:
        RSA-encrypted ciphertext

    Raises:
        VaultCryptoError: If encryption fails
    """
    try:
        cert = load_der_x509_certificate(cert_der)
        public_key = cast(RSAPublicKey, cert.public_key())
        ciphertext = public_key.encrypt(
            data,
            asym_padding.OAEP(
                mgf=asym_padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
        return ciphertext
    except Exception as e:
        raise VaultCryptoError(f"RSA OAEP encryption failed: {e}") from e


def pem_rsa_encrypt_oaep(data: bytes, pubkey_pem: bytes) -> bytes:
    """
    RSA-OAEP-SHA256-encrypt data with PEM public key.

    Args:
        data: Data to encrypt
        pubkey_pem: PEM-encoded SubjectPublicKeyInfo

    Returns:
        RSA-encrypted ciphertext

    Raises:
        VaultCryptoError: If encryption fails
    """
    try:
        public_key = cast(RSAPublicKey, serialization.load_pem_public_key(pubkey_pem))
        ciphertext = public_key.encrypt(
            data,
            asym_padding.OAEP(
                mgf=asym_padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
        return ciphertext
    except Exception as e:
        raise VaultCryptoError(f"PEM RSA OAEP encryption failed: {e}") from e


def pem_rsa_decrypt_oaep(data: bytes, privkey_pem: bytes) -> bytes:
    """
    RSA-OAEP-SHA256-decrypt data with PEM private key.

    Args:
        data: RSA-encrypted ciphertext
        privkey_pem: PEM-encoded private key

    Returns:
        Decrypted plaintext

    Raises:
        VaultCryptoError: If decryption fails
    """
    try:
        private_key = cast(
            RSAPrivateKey,
            serialization.load_pem_private_key(privkey_pem, password=None),
        )
        plaintext = private_key.decrypt(
            data,
            asym_padding.OAEP(
                mgf=asym_padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
        return plaintext
    except Exception as e:
        raise VaultCryptoError(f"PEM RSA OAEP decryption failed: {e}") from e


# ── Session Key Generation ────────────────────────────────────────────────────


def generate_random_bytes(length: int) -> bytes:
    """
    Generate cryptographically secure random bytes.

    Args:
        length: Number of bytes to generate

    Returns:
        Random bytes

    Raises:
        VaultCryptoError: If random generation fails
    """
    try:
        return os.urandom(length)
    except Exception as e:
        raise VaultCryptoError(f"Random byte generation failed: {e}") from e


def generate_vault_session_key(algo: str) -> bytes:
    """
    Generate a random session key for vault wrapping algorithm.

    Supported algorithms:
    - "aes-128-cbc": 16-byte key
    - "des-ede3-cbc": 24-byte key (legacy)

    Args:
        algo: Wrapping algorithm name

    Returns:
        Random session key bytes

    Raises:
        VaultCryptoError: If algorithm unknown or generation fails
    """
    key_lengths = {"aes-128-cbc": 16, "des-ede3-cbc": 24}

    if algo not in key_lengths:
        raise VaultCryptoError(f"Unknown vault wrapping algorithm: {algo}")

    return generate_random_bytes(key_lengths[algo])


# ── Data Wrapping / Unwrapping ────────────────────────────────────────────────


def wrap_vault_data(algo: str, session_key: bytes, data: bytes) -> tuple[bytes, bytes]:
    """
    CBC-encrypt data with session key for transport to KRA.

    Generates a random IV (nonce) and encrypts using the specified cipher.
    Applies PKCS7 padding automatically.

    Args:
        algo: Wrapping algorithm ("aes-128-cbc" or "des-ede3-cbc")
        session_key: Symmetric key bytes
        data: Plaintext to encrypt

    Returns:
        (nonce, ciphertext) tuple - nonce is the IV used for encryption

    Raises:
        VaultCryptoError: If encryption fails or algorithm unknown
    """
    if algo == "aes-128-cbc":
        cipher_algo = algorithms.AES(session_key)
        nonce_len = 16
    elif algo == "des-ede3-cbc":
        cipher_algo = algorithms.TripleDES(session_key)
        nonce_len = 8
    else:
        raise VaultCryptoError(f"Unknown vault wrapping algorithm: {algo}")

    try:
        nonce = generate_random_bytes(nonce_len)
        cipher = Cipher(cipher_algo, modes.CBC(nonce))
        encryptor = cipher.encryptor()

        # Apply PKCS7 padding
        padding_len = cipher_algo.block_size // 8
        pad_amount = padding_len - (len(data) % padding_len)
        padded_data = data + bytes([pad_amount] * pad_amount)

        ciphertext = encryptor.update(padded_data) + encryptor.finalize()
        return nonce, ciphertext
    except Exception as e:
        raise VaultCryptoError(f"Vault data wrapping failed: {e}") from e


def unwrap_vault_data(
    algo: str, session_key: bytes, nonce: bytes, data: bytes
) -> bytes:
    """
    CBC-decrypt vault data received from KRA.

    Removes PKCS7 padding automatically.

    Args:
        algo: Wrapping algorithm ("aes-128-cbc" or "des-ede3-cbc")
        session_key: Symmetric key bytes
        nonce: IV used for encryption
        data: Ciphertext to decrypt

    Returns:
        Decrypted plaintext with padding removed

    Raises:
        VaultCryptoError: If decryption fails or algorithm unknown
    """
    if algo == "aes-128-cbc":
        cipher_algo = algorithms.AES(session_key)
    elif algo == "des-ede3-cbc":
        cipher_algo = algorithms.TripleDES(session_key)
    else:
        raise VaultCryptoError(f"Unknown vault wrapping algorithm: {algo}")

    try:
        cipher = Cipher(cipher_algo, modes.CBC(nonce))
        decryptor = cipher.decryptor()
        padded_data = decryptor.update(data) + decryptor.finalize()

        # Remove PKCS7 padding
        pad_amount = padded_data[-1]
        if pad_amount < 1 or pad_amount > (cipher_algo.block_size // 8):
            raise VaultCryptoError("Invalid PKCS7 padding")

        # Verify padding bytes
        if padded_data[-pad_amount:] != bytes([pad_amount] * pad_amount):
            raise VaultCryptoError("Invalid PKCS7 padding bytes")

        return padded_data[:-pad_amount]
    except VaultCryptoError:
        raise
    except Exception as e:
        raise VaultCryptoError(f"Vault data unwrapping failed: {e}") from e
