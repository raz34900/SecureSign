"""Document cleanup, and the boundary it must not cross.

`isolate_signature_ink` runs between extraction and embedding, on both the enrolment
and the verification path, so a reference and a query are prepared identically.

The boundary is the model pipeline itself. `extract_vertical_anchors`,
`UnifiedSignatureTransform` and the embedder are shared with training, and cleanup
must never be pulled inside any of them: that would change what the trained weights
were fitted to and move every distance the system has ever produced.
"""
import base64
import io
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw

from conftest import login
from signature_core.anchors import extract_vertical_anchors
from signature_core.cleanup import flatten_image_bytes, isolate_signature_ink
from signature_core.preprocess import UnifiedSignatureTransform
from test_signature_core import make_signature, make_specimen_card

REPO_ROOT = Path(__file__).resolve().parents[1]


def ink_pixels(img: Image.Image) -> int:
    return int((np.asarray(img.convert("L")) < 128).sum())


def make_region_with_furniture() -> Image.Image:
    """A signature plus the marks a cheque brings with it: a printed reference number,
    two registration squares and the ruled line they sit on."""
    region = Image.new("L", (1400, 280), 255)
    region.paste(make_signature(seed=3).resize((620, 170)), (330, 60))
    draw = ImageDraw.Draw(region)
    draw.text((30, 20), "230519", fill=0)
    draw.rectangle([(20, 235), (52, 262)], fill=0)
    draw.rectangle([(1340, 235), (1372, 262)], fill=0)
    draw.line([(36, 258), (1356, 258)], fill=0, width=4)
    return region


def test_cleanup_removes_furniture_but_keeps_the_signature():
    region = make_region_with_furniture()
    cleaned = isolate_signature_ink(region)

    assert cleaned.size == region.size
    assert ink_pixels(cleaned) < ink_pixels(region)

    left_margin = np.asarray(cleaned)[:, :300]
    assert (left_margin < 128).sum() == 0

    # The signature itself must still be substantially present.
    signature_band = np.asarray(cleaned)[40:230, 320:960]
    assert (signature_band < 128).sum() > 0.5 * ink_pixels(cleaned)


def test_cleanup_keeps_an_accent_but_still_drops_furniture():
    """A dot over an i is a detached blob far under a quarter of the signature, which is
    exactly the size the furniture rule deletes. Position is what separates them: an
    accent sits within the horizontal run of the writing, furniture sits out at the
    margins. Measured on a real photograph, the size rule alone removed 2.9% of the ink.
    """
    region = make_region_with_furniture()
    draw = ImageDraw.Draw(region)
    # Just clear of the writing, the way a macron or a dot over an i sits. The signature
    # occupies rows 80-199 of this fixture.
    draw.line([(600, 68), (700, 66)], fill=0, width=6)
    accent_band = (slice(60, 78), slice(590, 710))

    cleaned = np.asarray(isolate_signature_ink(region))
    assert (cleaned[accent_band] < 128).sum() > 0, "the accent was deleted with the furniture"
    assert (cleaned[:, :300] < 128).sum() == 0, "the reference number survived"


def test_cleanup_leaves_an_already_clean_crop_alone():
    """Evenly-lit ink has nothing to strip and no shadow to flatten, so what the model
    sees is unchanged. Asserted on the transform output rather than object identity:
    cleanup always returns a flattened image, and the property that matters is that
    flattening a clean crop is a no-op in effect."""
    clean = make_signature(seed=8)
    assert np.array_equal(np.asarray(UnifiedSignatureTransform()(clean)),
                          np.asarray(UnifiedSignatureTransform()(isolate_signature_ink(clean))))


@pytest.mark.parametrize("module", [
    "packages/signature_core/anchors.py",
    "packages/signature_core/preprocess.py",
    "packages/signature_core/embed.py",
])
def test_cleanup_stays_out_of_the_model_pipeline(module):
    """Guard rail. These three are shared with training; cleanup belongs around them,
    never inside them, or the weights no longer match what they were fitted to."""
    source = (REPO_ROOT / module).read_text()
    assert "isolate_signature_ink" not in source
    assert "signature_core.cleanup" not in source


def test_enrolment_crops_are_extraction_then_cleanup(client, seeded):
    """A reference must be prepared exactly the way a query is, or the two are not
    comparable. Extract, then strip non-signature ink; nothing else."""
    login(client, "BA11", "clerk1")
    card = make_specimen_card(9)

    enrolment_id = client.post("/customers", json={
        "national_id": "445566778",
        "full_name": "Pipeline Check",
        "consent": {"granted": True, "method": "signed_form"},
    }).json()["enrolment_id"]

    response = client.post(f"/customers/{enrolment_id}/card",
                           files={"file": ("card.jpg", card, "image/jpeg")})
    assert response.status_code == 200
    returned = response.json()["crops"]

    expected = [isolate_signature_ink(crop)
                for crop in extract_vertical_anchors(flatten_image_bytes(card))]
    assert len(returned) == len(expected)

    for crop, reference in zip(returned, expected):
        decoded = Image.open(io.BytesIO(base64.b64decode(crop["preview_png_base64"])))
        assert np.array_equal(np.asarray(decoded.convert("L")),
                              np.asarray(reference.convert("L")))


def test_a_clean_specimen_card_is_unchanged_by_enrolment_cleanup():
    """The no-op case, stated as a test: cleanup must not disturb card scans, which is
    what makes it safe to apply on both the enrolment and the verification path."""
    transform = UnifiedSignatureTransform()
    for crop in extract_vertical_anchors(make_specimen_card(9)):
        assert np.array_equal(np.asarray(transform(crop)),
                              np.asarray(transform(isolate_signature_ink(crop))))


def test_cleanup_flattens_a_shadowed_capture():
    """The reason flattening exists. A phone's own shadow over a close-up pushes a
    genuine signature past the fraud threshold; dividing out the background removes it."""
    from signature_core.cleanup import flatten_illumination

    clean = make_signature(seed=5)
    pixels = np.asarray(clean.convert("L")).astype(np.float32)
    height, width = pixels.shape
    gradient = np.linspace(1.0, 0.35, width)[None, :] * np.linspace(1.0, 0.75, height)[:, None]
    shadowed = Image.fromarray(np.clip(pixels * gradient, 0, 255).astype(np.uint8))

    # The shadow is real: the raw capture differs from the clean one.
    assert not np.array_equal(np.asarray(shadowed), np.asarray(clean.convert("L")))

    # After flattening, the transform sees the same thing it would have seen unshadowed.
    transform = UnifiedSignatureTransform()
    recovered = Image.fromarray(flatten_illumination(np.asarray(shadowed)))
    before = np.asarray(transform(shadowed)).astype(int)
    after = np.asarray(transform(recovered)).astype(int)
    target = np.asarray(transform(clean)).astype(int)
    assert np.abs(after - target).mean() < np.abs(before - target).mean()


def shadowed_card(count: int = 9) -> bytes:
    """A specimen card photographed with the phone's own shadow across it."""
    card = Image.open(io.BytesIO(make_specimen_card(count))).convert("L")
    pixels = np.asarray(card).astype(np.float32)
    height, width = pixels.shape
    gradient = np.linspace(1.0, 0.3, width)[None, :] * np.linspace(1.0, 0.7, height)[:, None]
    darkened = Image.fromarray(np.clip(pixels * gradient, 0, 255).astype(np.uint8))
    buffer = io.BytesIO()
    darkened.convert("RGB").save(buffer, format="JPEG", quality=92)
    return buffer.getvalue()


def test_flattening_happens_before_extraction_not_after():
    """The ordering is the whole point, and it is invisible on a clean card.

    Extraction thresholds the entire frame with one Otsu cut, so a shadow hides the
    strokes it falls on and the card is read in pieces. Flattening the crops afterwards
    cannot help: by then extraction has already decided what to cut out. This failed in
    production at roughly one capture in ten before the order was fixed.
    """
    clean, shadowed = make_specimen_card(9), shadowed_card(9)

    # Precondition: the shadow really does defeat raw extraction.
    assert len(extract_vertical_anchors(shadowed)) < len(extract_vertical_anchors(clean))

    # Flattening first recovers every signature.
    assert (len(extract_vertical_anchors(flatten_image_bytes(shadowed)))
            == len(extract_vertical_anchors(clean)))


def test_enrolment_finds_every_signature_on_a_shadowed_card(client, seeded):
    """End to end: a shadowed card must enrol, not fail the eight-signature floor."""
    login(client, "BA11", "clerk1")
    enrolment_id = client.post("/customers", json={
        "national_id": "445566779", "full_name": "Shadowed Capture",
        "consent": {"granted": True, "method": "signed_form"},
    }).json()["enrolment_id"]

    response = client.post(f"/customers/{enrolment_id}/card",
                           files={"file": ("card.jpg", shadowed_card(9), "image/jpeg")})
    assert response.status_code == 200, response.text
    assert len(response.json()["crops"]) == 9


@pytest.mark.parametrize("module", [
    "backend/app/services/enrolment.py",
    "backend/app/services/verification.py",
    "scripts/reembed_references.py",
])
def test_nothing_reaches_the_model_without_room_to_deskew(module):
    """Guard rail, and the reason it needs to be one.

    The transform deskews by rotating into a canvas of its own size, so ink that swings
    outside is thrown away — measured at 2.6-4.4% on real photographs, taken off the
    first and last strokes. `pad_for_rotation` gives it room. An embedding made without
    it is not comparable with one made with it, so a single call site left unpadded
    silently corrupts every comparison against those references rather than failing.
    """
    source = (REPO_ROOT / module).read_text()
    for line in source.splitlines():
        if ".embed(" in line or "UnifiedSignatureTransform()(" in line:
            assert "pad_for_rotation" in line, f"{module}: unpadded — {line.strip()}"


def test_padding_survives_the_rotation_the_transform_applies():
    """The property that matters: after padding, deskew destroys no ink."""
    from signature_core.cleanup import pad_for_rotation

    wide = Image.new("L", (1200, 300), 255)
    wide.paste(make_signature(seed=11).resize((1100, 240)), (50, 30))

    def ink_through_deskew(img):
        pixels = np.array(img.convert("L"))
        _, mask = cv2.threshold(cv2.GaussianBlur(pixels, (5, 5), 0), 0, 255,
                                cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        height, width = pixels.shape[:2]
        rotation = cv2.getRotationMatrix2D((width // 2, height // 2), 20.0, 1.0)
        turned = cv2.warpAffine(mask, rotation, (width, height), flags=cv2.INTER_CUBIC,
                                borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        return int(mask.sum()), int(turned.sum())

    before, after = ink_through_deskew(wide)
    assert after < before, "fixture does not actually lose ink to rotation"

    before, after = ink_through_deskew(pad_for_rotation(wide))
    assert after >= 0.999 * before


def test_flattening_is_idempotent():
    """It runs before extraction and again inside cleanup, so it must be safe twice."""
    once = flatten_image_bytes(shadowed_card(9))
    assert np.array_equal(np.asarray(Image.open(io.BytesIO(once)).convert("L")),
                          np.asarray(Image.open(io.BytesIO(flatten_image_bytes(once))).convert("L")))


def test_a_dark_page_edge_is_not_offered_as_a_signature():
    """A photographed card brings its own border: the dark strip down one side of the
    frame extracts as a region like any other, and then fails the consistency check
    against the real specimens — which reads to the clerk as their card being rejected.
    A band of writing is always wider than tall; the narrowest genuine region measured
    across this project's cards, cheques and photographs is 1.79."""
    from signature_core.quality import looks_like_signature

    edge = np.zeros((1400, 40), dtype=np.uint8)          # tall, narrow, solid
    assert not looks_like_signature(edge)

    block = np.zeros((200, 900), dtype=np.uint8)         # wide but solid ink
    assert not looks_like_signature(block)

    signature = np.asarray(make_signature(seed=2).convert("L"))
    assert looks_like_signature(signature)


def test_every_genuine_specimen_on_a_card_survives_the_plausibility_check():
    """The filter must never cost a real signature — that would silently shrink the
    reference set and push a card under the eight-signature floor."""
    from signature_core.quality import looks_like_signature

    for count in (8, 9, 10):
        crops = [isolate_signature_ink(crop)
                 for crop in extract_vertical_anchors(flatten_image_bytes(make_specimen_card(count)))]
        kept = [c for c in crops if looks_like_signature(np.asarray(c.convert("L")))]
        assert len(kept) == len(crops) == count
