# FreeIPA Vault Management

Complete client-side vault encryption/decryption implementation for FreeIPA MCP, providing secure storage and retrieval of sensitive data.

## Overview

FreeIPA vaults provide secure storage with three encryption modes:
- **standard**: Base64 encoding only (no encryption)
- **symmetric**: Password-based encryption using PBKDF2 + Fernet
- **asymmetric**: Public/private key encryption using RSA-OAEP

## Installation

```bash
pip install freeipa-mcp-py[vault]
```

This installs the required `cryptography` library for vault operations.

## Architecture

### Cryptographic Components

**PBKDF2 Key Derivation** (Symmetric Vaults)
- Algorithm: PBKDF2-HMAC-SHA256
- Iterations: 100,000
- Output: 32 bytes (16 for HMAC + 16 for AES)

**Fernet Encryption** (Symmetric Vaults)
- Encryption: AES-128-CBC
- MAC: HMAC-SHA256
- Encoding: URL-safe base64
- Token structure: `[version:1][timestamp:8][IV:16][ciphertext:n][HMAC:32]`

**RSA Transport Encryption**
- Session key wrapping: RSA-PKCS1v15 or RSA-OAEP-SHA256
- Vault data encryption (asymmetric): RSA-OAEP-SHA256
- Automatic fallback from PKCS1v15 to OAEP in FIPS mode

**Session Key Wrapping**
- AES-128-CBC: 16-byte keys with 16-byte IV
- 3DES-CBC: 24-byte keys with 8-byte IV (legacy KRAs)
- PKCS7 padding applied automatically

### KRA Configuration Caching

KRA transport certificates and wrapping algorithms are cached per-domain:

```
~/.cache/ipa/kra-config/{domain}.json
{
  "transport_cert": "base64_encoded_der",
  "wrapping_algo": "aes-128-cbc"
}
```

Cache is refreshed automatically when:
- Cache file doesn't exist
- Cache corrupted
- RSA wrapping fails (cert may be expired)

## Commands

### vaultconfig-show

Display KRA configuration (transport certificate and wrapping algorithm).

```json
{
  "name": "vaultconfig-show",
  "arguments": {}
}
```

**Returns**: Transport certificate (DER base64) and wrapping algorithm.

### vault-add

Create a new vault.

```json
{
  "name": "vault-add",
  "arguments": {
    "cn": "my-vault",
    "ipavaulttype": "symmetric"
  }
}
```

**Vault Types**:
- `"standard"` - No encryption (default)
- `"symmetric"` - Password-based encryption
- `"asymmetric"` - Public/private key encryption

**Auto-generated**:
- Salt (16 random bytes) for symmetric vaults if not provided
- Default type is "standard" if not specified

**Vault Selectors** (optional):
- `user`: Username (default: current user)
- `shared`: Shared vault
- `service`: Service vault
- `username`: Specific user

### vault-mod

Modify vault metadata.

```json
{
  "name": "vault-mod",
  "arguments": {
    "cn": "my-vault",
    "description": "Updated description"
  }
}
```

### vault-archive

Store encrypted data in a vault.

```json
{
  "name": "vault-archive",
  "arguments": {
    "cn": "my-vault",
    "in": "/path/to/secret.txt",
    "password": "vault_password"
  }
}
```

**Required**:
- `cn`: Vault name
- `in`: Input file path (max 1 MiB)

**Authentication**:
- Symmetric: `password` or `password_file`
- Asymmetric: No authentication needed (encrypted with public key)
- Standard: No authentication needed

**Flow**:
1. Read data from file (validates size ≤ 1 MiB)
2. Fetch vault metadata to determine type
3. Encrypt data:
   - **Standard**: Base64 encode
   - **Symmetric**: PBKDF2 derive key → Fernet encrypt
   - **Asymmetric**: RSA-OAEP encrypt with public key
4. Wrap encrypted data in session-key envelope (CBC)
5. RSA-wrap session key with KRA transport cert
6. Send to `vault_archive_internal`

### vault-retrieve

Retrieve and decrypt data from a vault.

```json
{
  "name": "vault-retrieve",
  "arguments": {
    "cn": "my-vault",
    "out": "/path/to/output.txt",
    "password": "vault_password"
  }
}
```

**Required**:
- `cn`: Vault name

**Optional**:
- `out`: Output file path (if omitted, returns base64)

**Authentication**:
- Symmetric: `password` or `password_file`
- Asymmetric: `private_key` or `private_key_file`
- Standard: No authentication needed

**Flow**:
1. Fetch vault metadata to determine type
2. Generate session key and RSA-wrap with KRA cert
3. Call `vault_retrieve_internal` with wrapped session key
4. CBC-unwrap response with session key
5. Decrypt inner data:
   - **Standard**: Base64 decode
   - **Symmetric**: PBKDF2 derive key → Fernet decrypt
   - **Asymmetric**: RSA-OAEP decrypt with private key
6. Write to file or return base64

## Usage Examples

### Create and Use Symmetric Vault

```json
// 1. Create vault
{
  "name": "vault-add",
  "arguments": {
    "cn": "credentials",
    "ipavaulttype": "symmetric"
  }
}

// 2. Archive secret
{
  "name": "vault-archive",
  "arguments": {
    "cn": "credentials",
    "in": "/tmp/api-key.txt",
    "password": "my_strong_password"
  }
}

// 3. Retrieve secret
{
  "name": "vault-retrieve",
  "arguments": {
    "cn": "credentials",
    "out": "/tmp/retrieved-key.txt",
    "password": "my_strong_password"
  }
}
```

### Create and Use Asymmetric Vault

```json
// 1. Generate key pair
// openssl genrsa -out private.pem 2048
// openssl rsa -in private.pem -pubout -out public.pem

// 2. Create vault with public key
{
  "name": "vault-add",
  "arguments": {
    "cn": "ssh-keys",
    "ipavaulttype": "asymmetric",
    "ipavaultpublickey": "<PEM public key>"
  }
}

// 3. Archive secret
{
  "name": "vault-archive",
  "arguments": {
    "cn": "ssh-keys",
    "in": "/home/user/.ssh/id_rsa"
  }
}

// 4. Retrieve secret
{
  "name": "vault-retrieve",
  "arguments": {
    "cn": "ssh-keys",
    "out": "/tmp/retrieved_key",
    "private_key_file": "/path/to/private.pem"
  }
}
```

### Use Password File

```json
// Store password in file
// echo "my_vault_password" > /tmp/vault.pwd

{
  "name": "vault-archive",
  "arguments": {
    "cn": "my-vault",
    "in": "/tmp/secret.txt",
    "password_file": "/tmp/vault.pwd"
  }
}
```

### Shared Vaults

```json
{
  "name": "vault-add",
  "arguments": {
    "cn": "team-secrets",
    "shared": true,
    "ipavaulttype": "symmetric"
  }
}

{
  "name": "vault-archive",
  "arguments": {
    "cn": "team-secrets",
    "shared": true,
    "in": "/tmp/team-api-key.txt",
    "password": "team_password"
  }
}
```

## Security Considerations

### Key Derivation

- **100,000 PBKDF2 iterations** resist brute-force attacks
- **Random 16-byte salt** prevents rainbow table attacks
- Salt stored server-side with vault metadata

### Transport Security

- Session keys randomized per operation (forward secrecy)
- RSA-OAEP with SHA-256 for transport cert encryption
- Automatic PKCS1v15 → OAEP fallback in FIPS mode

### Data Limits

- Maximum vault data size: **1 MiB** (1,048,576 bytes)
- Enforced client-side before encryption

### Fernet Token Format

- HMAC-SHA256 authentication prevents tampering
- AES-128-CBC encryption
- Timestamp included (token expiration can be enforced)
- Constant-time HMAC verification resists timing attacks

## Error Handling

| Error | Cause | Solution |
|-------|-------|----------|
| `ValueError: Required parameter 'in' not provided` | Missing input file | Provide `in` parameter |
| `FileNotFoundError: Input file not found` | File doesn't exist | Check file path |
| `ValueError: Data exceeds maximum vault size` | File > 1 MiB | Split data or use smaller file |
| `ValueError: Password required` | Missing password for symmetric vault | Provide `password` or `password_file` |
| `FileNotFoundError: Password file not found` | Password file missing | Check password file path |
| `ValueError: Asymmetric vault retrieve requires private_key_file` | Missing private key | Provide `private_key` or `private_key_file` |
| `VaultCryptoError: Fernet decryption failed` | Wrong password | Verify password is correct |
| `VaultCryptoError: RSA OAEP decryption failed` | Wrong private key | Verify private key matches public key |
| `VaultCryptoError: Unknown vault wrapping algorithm` | Unsupported KRA cipher | Server configuration issue |

## Implementation Details

### Module Structure

```
freeipa_mcp/
├── vault_crypto.py      # Cryptographic primitives
├── vault_cache.py       # KRA config caching
└── tools/
    └── vault.py         # Vault commands

tests/
├── test_vault_crypto.py # Crypto tests (26 tests)
└── test_vault_cache.py  # Cache tests (11 tests)
```

### Test Coverage

**37 tests total**, all passing:

- PBKDF2: Deterministic, salt-sensitive, password-sensitive
- Fernet: Roundtrip, wrong key rejection, empty/large data
- Session keys: AES-128/3DES length validation, uniqueness
- Data wrapping: AES-128-CBC/3DES-CBC roundtrip, wrong key/nonce detection
- KRA cache: Save/load, corruption handling, domain separation

### Dependencies

- `cryptography >= 41.0.0` - Core crypto operations
  - Fernet encryption
  - RSA operations
  - PBKDF2 key derivation
  - AES-CBC and 3DES ciphers

### Compatibility

| Feature | Python Implementation | mutqu (Rust) | Status |
|---------|----------------------|--------------|--------|
| PBKDF2-HMAC-SHA256 | ✅ | ✅ | Compatible |
| Fernet encryption | ✅ | ✅ | Compatible |
| RSA-PKCS1v15 wrapping | ✅ | ✅ | Compatible |
| RSA-OAEP wrapping | ✅ | ✅ | Compatible |
| AES-128-CBC | ✅ | ✅ | Compatible |
| 3DES-CBC (legacy) | ✅ | ✅ | Compatible |
| KRA config cache | ✅ | ✅ | Compatible |
| FIPS mode fallback | ✅ | ✅ | Compatible |

## Performance

- **PBKDF2**: ~50ms per key derivation (100,000 iterations)
- **Fernet encrypt**: <1ms for typical data sizes
- **RSA operations**: 5-10ms per operation
- **Session key wrapping**: <10ms with caching
- **Cache hit**: Saves ~100ms per vault operation

## Future Enhancements

- [ ] Interactive password prompts for CLI usage
- [ ] Batch archive/retrieve operations
- [ ] Streaming for large files (>1 MiB chunks)
- [ ] Password strength validation
- [ ] Vault access logging
- [ ] Migration from standard → symmetric vaults

## References

- [FreeIPA Vault Documentation](https://www.freeipa.org/page/V4/Password_Vault_2.0)
- [Fernet Specification](https://github.com/fernet/spec/blob/master/Spec.md)
- [PBKDF2 RFC 2898](https://tools.ietf.org/html/rfc2898)
- [RSA-OAEP RFC 8017](https://tools.ietf.org/html/rfc8017)
