"""Encrypting secrets at rest: a student's Google Drive refresh token and OAuth verifier.

AES-256-GCM (the `cryptography` package) with DRIVE_TOKEN_KEY, a fresh random 96-bit nonce for
every encryption, and associated data naming the student and the purpose. The associated data is
authenticated but not stored: a ciphertext copied into another student's row (or used for another
purpose) fails to decrypt. Stored as "v1.<nonce>.<ciphertext+tag>" in URL-safe base64.

Nothing here logs a value, and a failure never says why beyond "cannot decrypt".
"""

import base64
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from piq.config import settings

VERSION = "v1"
NONCE_BYTES = 12  # 96 bits, the size GCM is designed for


class SecretError(Exception):
    """The value cannot be decrypted (wrong key, wrong student or purpose, or tampered)."""


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _aad(student_id: str, purpose: str) -> bytes:
    return f"skill-scout-nexus|{purpose}|{student_id}".encode()


def _cipher(key: bytes | None) -> AESGCM:
    key = settings().drive_token_key if key is None else key
    if len(key) != 32:
        raise SecretError("no encryption key is configured")
    return AESGCM(key)


def seal(plaintext: str, *, student_id: str, purpose: str, key: bytes | None = None) -> str:
    """Encrypt `plaintext` for this student and purpose (a new random nonce every time)."""
    nonce = os.urandom(NONCE_BYTES)
    data = _cipher(key).encrypt(nonce, plaintext.encode(), _aad(student_id, purpose))
    return f"{VERSION}.{_b64(nonce)}.{_b64(data)}"


def open_(sealed: str, *, student_id: str, purpose: str, key: bytes | None = None) -> str:
    """Decrypt a value sealed for this student and purpose; SecretError otherwise."""
    try:
        version, nonce, data = sealed.split(".")
        if version != VERSION:
            raise ValueError
        plain = _cipher(key).decrypt(_unb64(nonce), _unb64(data), _aad(student_id, purpose))
    except (ValueError, InvalidTag) as e:
        raise SecretError("cannot decrypt") from e
    return plain.decode()
