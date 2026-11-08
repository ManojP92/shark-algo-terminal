"""
vault.py
──────────────────────────────────────────────────────────────────────────────
Banking-Grade AES-256 (Fernet) Encryption & Key Vault.
Secures client exchange API keys and secrets at rest.
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
from typing import Optional

from cryptography.fernet import Fernet

log = logging.getLogger("vault")

# Default fallback pepper for development (Production MUST set ENCRYPTION_MASTER_KEY in .env)
_DEFAULT_PEPPER = "shark-algo-master-pepper-seed-2026-btc-usd"


def generate_master_key() -> str:
    """Generate a random 32-byte master key string."""
    import secrets
    return secrets.token_hex(32)


def _derive_fernet_key(master_secret: Optional[str] = None) -> bytes:
    """
    Derives a deterministic 32-byte URL-safe base64-encoded Fernet key
    from the master secret string using SHA-256.
    """
    secret = master_secret or os.getenv("ENCRYPTION_MASTER_KEY", _DEFAULT_PEPPER)
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def get_fernet_cipher(master_secret: Optional[str] = None) -> Fernet:
    key = _derive_fernet_key(master_secret)
    return Fernet(key)


def encrypt_secret(plaintext: str, master_secret: Optional[str] = None) -> str:
    """
    Encrypts a plaintext string (e.g. Shark API Key / Secret) into AES-256 ciphertext.
    Returns URL-safe string.
    """
    if not plaintext:
        return ""
    cipher = get_fernet_cipher(master_secret)
    encrypted_bytes = cipher.encrypt(plaintext.encode("utf-8"))
    return encrypted_bytes.decode("utf-8")


def decrypt_secret(ciphertext: str, master_secret: Optional[str] = None) -> str:
    """
    Decrypts AES-256 ciphertext back into plaintext.
    """
    if not ciphertext:
        return ""
    cipher = get_fernet_cipher(master_secret)
    decrypted_bytes = cipher.decrypt(ciphertext.encode("utf-8"))
    return decrypted_bytes.decode("utf-8")
