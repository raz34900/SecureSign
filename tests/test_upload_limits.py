"""Uploads are bounded by decoded size, not only by bytes on the wire.

A decompression bomb is cheap to send and ruinous to decode: a few hundred kilobytes
of PNG can declare dimensions that allocate hundreds of megabytes. The guard therefore
reads the header and refuses before anything decodes the pixels.
"""
import io
import zlib

from PIL import Image

from conftest import login
from test_signature_core import make_specimen_card


def png_declaring_size(width: int, height: int) -> bytes:
    """A structurally valid PNG whose IHDR claims a huge picture.

    The pixel data stays 4x4, which is exactly the shape of the attack. PNG layout:
    8-byte signature, then a chunk of 4-byte length, 4-byte type, 13-byte IHDR data,
    4-byte CRC over type+data.
    """
    buffer = io.BytesIO()
    Image.new("L", (4, 4), 255).save(buffer, format="PNG")
    raw = bytearray(buffer.getvalue())
    raw[16:20] = width.to_bytes(4, "big")
    raw[20:24] = height.to_bytes(4, "big")
    raw[29:33] = zlib.crc32(bytes(raw[12:29])).to_bytes(4, "big")
    return bytes(raw)


def stage_enrolment(client) -> str:
    login(client, "BA11", "clerk1")
    return client.post("/customers", json={
        "national_id": "123456850", "full_name": "Bomb Test",
        "consent": {"granted": True, "method": "signed_form"},
    }).json()["enrolment_id"]


def test_the_crafted_header_really_does_claim_a_huge_image():
    """Precondition: without this the test below could pass for the wrong reason."""
    bomb = png_declaring_size(10000, 8000)
    assert len(bomb) < 200
    with Image.open(io.BytesIO(bomb)) as probe:
        assert probe.size == (10000, 8000)


def test_enrolment_rejects_an_oversized_image(client, seeded):
    enrolment_id = stage_enrolment(client)
    response = client.post(f"/customers/{enrolment_id}/card",
                           files={"file": ("bomb.png", png_declaring_size(10000, 8000),
                                           "image/png")})
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "IMAGE_TOO_LARGE"


def test_verification_rejects_an_oversized_image(client, seeded):
    login(client, "SB44", "rep1")
    response = client.post("/verify", data={"national_id": "123456850"},
                           files={"file": ("bomb.png", png_declaring_size(10000, 8000),
                                           "image/png")})
    assert response.status_code == 413


def test_region_extraction_rejects_an_oversized_image(client, seeded):
    login(client, "SB44", "rep1")
    response = client.post("/verify/regions",
                           files={"file": ("bomb.png", png_declaring_size(10000, 8000),
                                           "image/png")})
    assert response.status_code == 413


def test_a_normal_specimen_card_is_unaffected(client, seeded):
    enrolment_id = stage_enrolment(client)
    response = client.post(f"/customers/{enrolment_id}/card",
                           files={"file": ("card.jpg", make_specimen_card(9), "image/jpeg")})
    assert response.status_code == 200


def test_unreadable_bytes_are_rejected_before_decoding(client, seeded):
    enrolment_id = stage_enrolment(client)
    response = client.post(f"/customers/{enrolment_id}/card",
                           files={"file": ("x.png", b"not an image at all", "image/png")})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_IMAGE"
