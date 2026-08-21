"""Envelope encryption for signature images.

Each customer has a data encryption key; the image is encrypted under it, and that key is
stored only wrapped by the key encryption key from the environment. The extra layer buys
two things. Destroying one wrapped key erases that customer's signatures everywhere the
ciphertext exists, backups included. And moving the key encryption key - one day into a
KMS - rewraps a few short keys instead of rewriting every image.

It does not survive code execution on the host, which holds the key encryption key. It
defends a stolen dump, a stray backup, a file-read bug, and database access without a
shell.
"""
import os

from backend.app.security.crypto import seal, unseal

DEK_LEN = 32  # AES-256


def new_dek() -> bytes:
    return os.urandom(DEK_LEN)


def wrap_dek(dek: bytes, kek_hex: str) -> bytes:
    """A customer's key, encrypted under the environment's key. Never stored bare."""
    return seal(bytes.fromhex(kek_hex), dek)


def unwrap_dek(wrapped: bytes, kek_hex: str) -> bytes:
    return unseal(bytes.fromhex(kek_hex), wrapped)


def encrypt_image(data: bytes, dek: bytes, *, aad: bytes | None = None) -> bytes:
    """AES-256-GCM. `aad` binds the ciphertext to the row it belongs to.

    Without it a reference image could be moved onto another customer's row and would
    still decrypt, which would let anyone with write access to the database swap one
    person's signature for another's without leaving a decryption failure behind.
    """
    return seal(dek, data, aad)


def decrypt_image(blob: bytes, dek: bytes, *, aad: bytes | None = None) -> bytes:
    return unseal(dek, blob, aad)
