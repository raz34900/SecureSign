"""Envelope encryption: what it protects, and what it deliberately does not.

Signature images used to sit beside the database as plain PNGs while the national ID
next to them was encrypted. Anyone holding a copy of both — a stray backup, a database
dump, a file-read bug — could put a name against a signature. The images are now
encrypted under a key held per customer, and that key is itself stored only encrypted
under the key from the environment.

The threat model is worth stating in the tests, because it is easy to oversell. The
running process holds the key encryption key, so this does not defend against code
execution on the host. It defends a stolen dump, a stray backup, a file-read bug and an
operator with database access but no shell.
"""
import pytest
from cryptography.exceptions import InvalidTag

from backend.app.security import envelope

KEK = "cc" * 32
OTHER_KEK = "dd" * 32
IMAGE = b"\x89PNG\r\n\x1a\n" + b"pretend this is a signature" * 40


def test_a_wrapped_key_comes_back_intact():
    dek = envelope.new_dek()
    assert len(dek) == envelope.DEK_LEN
    assert envelope.unwrap_dek(envelope.wrap_dek(dek, KEK), KEK) == dek


def test_a_key_is_never_stored_in_the_clear():
    dek = envelope.new_dek()
    assert dek not in envelope.wrap_dek(dek, KEK)


def test_the_wrong_key_encryption_key_cannot_unwrap():
    """The whole point of rotation: an old or foreign KEK opens nothing."""
    wrapped = envelope.wrap_dek(envelope.new_dek(), KEK)
    with pytest.raises(InvalidTag):
        envelope.unwrap_dek(wrapped, OTHER_KEK)


def test_wrapping_the_same_key_twice_gives_different_bytes():
    """A fresh nonce every time, so two customers with identical keys — or one key
    rewrapped during rotation — do not produce a matching pair anyone can spot."""
    dek = envelope.new_dek()
    assert envelope.wrap_dek(dek, KEK) != envelope.wrap_dek(dek, KEK)


def test_an_image_round_trips():
    dek = envelope.new_dek()
    blob = envelope.encrypt_image(IMAGE, dek, aad=b"ref-1")
    assert IMAGE not in blob
    assert envelope.decrypt_image(blob, dek, aad=b"ref-1") == IMAGE


def test_a_ciphertext_moved_to_another_row_does_not_decrypt():
    """The row id is authenticated. Without that, anyone able to write to the database
    could put one person's signature on another person's record and it would decrypt
    cleanly — a silent identity swap, with no failure to notice."""
    dek = envelope.new_dek()
    blob = envelope.encrypt_image(IMAGE, dek, aad=b"ref-1")
    with pytest.raises(InvalidTag):
        envelope.decrypt_image(blob, dek, aad=b"ref-2")


def test_a_tampered_ciphertext_is_refused_rather_than_returned_wrong():
    """GCM is authenticated: an altered byte fails loudly instead of decoding to
    something plausible."""
    dek = envelope.new_dek()
    blob = bytearray(envelope.encrypt_image(IMAGE, dek, aad=b"ref-1"))
    blob[-1] ^= 0x01
    with pytest.raises(InvalidTag):
        envelope.decrypt_image(bytes(blob), dek, aad=b"ref-1")


def test_another_customers_key_reads_nothing():
    blob = envelope.encrypt_image(IMAGE, envelope.new_dek(), aad=b"ref-1")
    with pytest.raises(InvalidTag):
        envelope.decrypt_image(blob, envelope.new_dek(), aad=b"ref-1")


def test_rotating_the_key_encryption_key_does_not_touch_the_images():
    """The property the extra layer exists for. Moving to a new KEK — or one day to a
    KMS — rewraps a short key per customer and leaves every image byte where it is."""
    dek = envelope.new_dek()
    image = envelope.encrypt_image(IMAGE, dek, aad=b"ref-1")

    rewrapped = envelope.wrap_dek(envelope.unwrap_dek(envelope.wrap_dek(dek, KEK), KEK),
                                  OTHER_KEK)
    recovered = envelope.unwrap_dek(rewrapped, OTHER_KEK)
    assert envelope.decrypt_image(image, recovered, aad=b"ref-1") == IMAGE, \
        "the image was never re-encrypted"
