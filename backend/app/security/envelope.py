"""Envelope encryption for signature images.

Every customer gets a data encryption key of their own. The image is encrypted under that
key; the key itself is stored only in a form encrypted under the key encryption key from
the environment. Two consequences, and both are the reason for the extra layer:

**Erasure that reaches backups.** Destroy one customer's wrapped key and their signatures
become unrecoverable everywhere that ciphertext exists, including in tapes nobody can
reach to edit. A shared registry that several institutions write to has no other honest
answer to a deletion request.

**Rotation without re-encrypting anything.** Moving the key encryption key - to a new
value, or one day to a KMS or an HSM - rewraps a few hundred small keys rather than
rewriting every image. That property is the whole reason this pattern exists, and it is
what makes the environment variable a starting point rather than a dead end.

What it does not protect against is worth being just as clear about: the running process
holds the key encryption key, so anything with code execution on the host reads
everything. This defends a stolen dump, a stray backup, a file-read bug and an operator
with database access but no shell - which is most of what actually happens - and not root.
"""
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_NONCE_LEN = 12
DEK_LEN = 32  # AES-256


def new_dek() -> bytes:
    return os.urandom(DEK_LEN)


def wrap_dek(dek: bytes, kek_hex: str) -> bytes:
    """A customer's key, encrypted under the environment's key. Never stored bare."""
    nonce = os.urandom(_NONCE_LEN)
    return nonce + AESGCM(bytes.fromhex(kek_hex)).encrypt(nonce, dek, None)


def unwrap_dek(wrapped: bytes, kek_hex: str) -> bytes:
    return AESGCM(bytes.fromhex(kek_hex)).decrypt(wrapped[:_NONCE_LEN], wrapped[_NONCE_LEN:], None)


def encrypt_image(data: bytes, dek: bytes, *, aad: bytes | None = None) -> bytes:
    """AES-256-GCM. `aad` binds the ciphertext to the row it belongs to.

    Without it a reference image could be moved onto another customer's row and would
    still decrypt, which would let anyone with write access to the database swap one
    person's signature for another's without leaving a decryption failure behind.
    """
    nonce = os.urandom(_NONCE_LEN)
    return nonce + AESGCM(dek).encrypt(nonce, data, aad)


def decrypt_image(blob: bytes, dek: bytes, *, aad: bytes | None = None) -> bytes:
    return AESGCM(dek).decrypt(blob[:_NONCE_LEN], blob[_NONCE_LEN:], aad)
