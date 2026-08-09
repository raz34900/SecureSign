"""PII protection: HMAC blind index for lookup, AES-GCM for storage."""
import hashlib
import hmac
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_NONCE_LEN = 12


def blind_index(national_id: str, key_hex: str) -> str:
    return hmac.new(bytes.fromhex(key_hex), national_id.encode(), hashlib.sha256).hexdigest()


def encrypt_pii(plaintext: str, key_hex: str) -> bytes:
    nonce = os.urandom(_NONCE_LEN)
    ct = AESGCM(bytes.fromhex(key_hex)).encrypt(nonce, plaintext.encode(), None)
    return nonce + ct


def decrypt_pii(blob: bytes, key_hex: str) -> str:
    nonce, ct = blob[:_NONCE_LEN], blob[_NONCE_LEN:]
    return AESGCM(bytes.fromhex(key_hex)).decrypt(nonce, ct, None).decode()
