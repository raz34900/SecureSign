import pytest

from backend.app.security.crypto import blind_index, decrypt_pii, encrypt_pii

KEY_A = "aa" * 32
KEY_B = "bb" * 32


def test_blind_index_deterministic_and_key_dependent():
    assert blind_index("123456789", KEY_A) == blind_index("123456789", KEY_A)
    assert blind_index("123456789", KEY_A) != blind_index("123456789", KEY_B)
    assert blind_index("123456789", KEY_A) != blind_index("123456788", KEY_A)
    assert len(blind_index("123456789", KEY_A)) == 64


def test_encrypt_roundtrip_and_nondeterminism():
    blob1 = encrypt_pii("123456789", KEY_A)
    blob2 = encrypt_pii("123456789", KEY_A)
    assert blob1 != blob2  # random nonce
    assert decrypt_pii(blob1, KEY_A) == "123456789"


def test_decrypt_wrong_key_raises():
    blob = encrypt_pii("123456789", KEY_A)
    with pytest.raises(Exception):
        decrypt_pii(blob, KEY_B)
