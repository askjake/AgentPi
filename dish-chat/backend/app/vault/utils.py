from __future__ import annotations

import logging
import re
from base64 import b64decode, b64encode
from typing import Optional

import argon2
from Crypto.Hash import SHA256
from Crypto.Random import get_random_bytes

from app.config import get_settings
from app.core.encryption import cipher, decipher
from .exceptions import InvalidHashException

settings = get_settings()
logger = logging.getLogger(__name__)


def encrypt_dek(
    passphrase: str,
    dek: Optional[str] = None,
) -> tuple[str, str]:
    """
    Encrypt (wrap) a 256-bit Data Encryption Key (DEK) using a key derived from the user's passphrase.

    Args:
        passphrase: User passphrase used to derive a key with Argon2.
        dek: Optional base64-encoded 256-bit DEK. If not provided, a random DEK is generated.

    Returns:
        (vhash, encrypted_dek)
        - vhash: base64-encoded SHA256 hash of the derived key (used to validate passphrase later)
        - encrypted_dek: string containing argon2 params + salt + base64(ciphertext)
          Format: "{argon2_params}${argon2_salt}${cipheredkey_b64}"
          Where argon2_params is the first 4 $-separated fields from argon2 output.
    """
    # Decode/generate DEK bytes
    if dek is None:
        dek_bytes = get_random_bytes(32)
    else:
        dek_bytes = b64decode(dek)

    if len(dek_bytes) != 32:
        raise ValueError("Data encryption key must be 256 bits (32 bytes).")

    # Argon2 hasher configured from settings
    argon2_hasher = argon2.PasswordHasher(
        time_cost=settings.ARGON2_TIME,
        memory_cost=settings.ARGON2_MEMORY,
        parallelism=settings.ARGON2_PARALLELISM,
        hash_len=settings.ARGON2_HASH_LEN,
        salt_len=settings.ARGON2_SALT_LEN,
    )

    # Hash passphrase -> yields: $argon2id$v=19$m=...,t=...,p=...$<salt_b64>$<hash_b64>
    derived_key_hash = argon2_hasher.hash(passphrase)
    parts = derived_key_hash.split("$")
    if len(parts) < 6:
        raise ValueError("Unexpected Argon2 hash format.")

    # Keep stable params block for later verification
    argon2_params = "$".join(parts[0:4])  # e.g. "$argon2id$v=19$m=...,t=...,p=..."
    argon2_salt = parts[4]               # b64 salt (no padding sometimes)
    derived_key = parts[5]               # b64 hash (no padding sometimes)

    # Encrypt DEK with derived key
    ciphered_key = cipher(dek_bytes, derived_key)

    # Compute validation hash of derived key
    sha256 = SHA256.new()
    sha256.update(b64decode(derived_key + "=="))
    vhash = b64encode(sha256.digest()).decode("ascii")

    # Store: params + salt + ciphertext
    encrypted_dek = argon2_params + f"${argon2_salt}$" + b64encode(ciphered_key).decode("ascii")
    return vhash, encrypted_dek


def decrypt_dek(passphrase: str, vhash: str, encrypted_dek: str) -> str:
    """
    Validate passphrase and decrypt (unwrap) a 256-bit DEK.

    Args:
        passphrase: User passphrase
        vhash: base64-encoded SHA256 hash of derived key (from encrypt_dek)
        encrypted_dek: string containing argon2 params + salt + base64(ciphertext)
            Format: "{argon2_params}${argon2_salt}${cipheredkey_b64}"

    Returns:
        Base64-encoded 256-bit DEK if passphrase is valid.

    Raises:
        InvalidHashException if passphrase is wrong.
        ValueError for malformed input.
    """
    parts = encrypted_dek.split("$")
    # Expected: ['', 'argon2id', 'v=19', 'm=...,t=...,p=...', <salt>, <cipher_b64>]
    if len(parts) < 6:
        raise ValueError("Malformed encrypted_dek format.")

    # Extract argon2 params
    match = re.search(r"m=(\d+),t=(\d+),p=(\d+)", parts[3])
    if not match:
        raise ValueError("Malformed Argon2 parameters in encrypted_dek.")
    m = int(match.group(1))
    t = int(match.group(2))
    p = int(match.group(3))

    argon2_salt_b64 = parts[4]
    ciphered_key_b64 = parts[5]

    # Salt in argon2 string is base64; may be missing padding
    salt_bytes = b64decode(argon2_salt_b64 + "==")
    ciphered_key = b64decode(ciphered_key_b64 + "==")

    # Recompute derived key using Argon2 settings read from stored params
    argon2_hasher = argon2.PasswordHasher(
        time_cost=t,
        memory_cost=m,
        parallelism=p,
        hash_len=settings.ARGON2_HASH_LEN,
        salt_len=settings.ARGON2_SALT_LEN,
    )

    derived_key_hash = argon2_hasher.hash(passphrase, salt=salt_bytes)
    derived_key = derived_key_hash.split("$")[5]

    # Validate derived key against vhash
    sha256 = SHA256.new()
    sha256.update(b64decode(derived_key + "=="))
    vhash2 = b64encode(sha256.digest()).decode("ascii")
    if vhash2 != vhash:
        raise InvalidHashException()

    # Decrypt DEK
    decrypted_dek = decipher(ciphered_key, derived_key)
    return b64encode(decrypted_dek).decode("ascii")
