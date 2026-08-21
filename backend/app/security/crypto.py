"""PII protection: HMAC blind index for lookup, AES-GCM for storage."""
import hashlib
import hmac
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_NONCE_LEN = 12


def seal(key: bytes, data: bytes, aad: bytes | None = None) -> bytes:
    """AES-256-GCM, nonce prefixed. One place, so every caller gets the same framing."""
    nonce = os.urandom(_NONCE_LEN)
    return nonce + AESGCM(key).encrypt(nonce, data, aad)


def unseal(key: bytes, blob: bytes, aad: bytes | None = None) -> bytes:
    return AESGCM(key).decrypt(blob[:_NONCE_LEN], blob[_NONCE_LEN:], aad)


def blind_index(national_id: str, key_hex: str) -> str:
    return hmac.new(bytes.fromhex(key_hex), national_id.encode(), hashlib.sha256).hexdigest()


def encrypt_pii(plaintext: str, key_hex: str) -> bytes:
    return seal(bytes.fromhex(key_hex), plaintext.encode())


def decrypt_pii(blob: bytes, key_hex: str) -> str:
    return unseal(bytes.fromhex(key_hex), blob).decode()
