"""Document cleanup, and the boundary that keeps it off the enrolment path.

`isolate_signature_ink` exists only to make a region cut from a document comparable
to an enrolled reference. It must never touch enrolment: stored anchors and their
embeddings were produced by the untouched pipeline, and re-processing them would
silently move every future distance for that customer.
"""
import base64
import io
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from conftest import login
from signature_core.anchors import extract_vertical_anchors
from signature_core.cleanup import isolate_signature_ink
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


def test_cleanup_leaves_an_already_clean_crop_alone():
    """A specimen-card crop has nothing to strip, so it comes back untouched."""
    clean = make_signature(seed=8)
    assert isolate_signature_ink(clean) is clean


@pytest.mark.parametrize("module", [
    "backend/app/services/enrolment.py",
    "backend/app/services/verification.py",
    "packages/signature_core/anchors.py",
    "packages/signature_core/preprocess.py",
    "packages/signature_core/embed.py",
])
def test_cleanup_stays_off_the_enrolment_and_model_path(module):
    """Guard rail. Stored anchors were embedded by the untouched pipeline; pulling
    cleanup into it would move every distance for every already-enrolled customer."""
    source = (REPO_ROOT / module).read_text()
    assert "isolate_signature_ink" not in source
    assert "signature_core.cleanup" not in source


def test_enrolment_crops_are_the_raw_extractor_output(client, seeded):
    """Enrolment must hand back exactly what the extractor produced, with no extra
    processing applied on the way."""
    login(client, "Bank A", "clerk1")
    card = make_specimen_card(6)

    enrolment_id = client.post("/customers", json={
        "national_id": "445566778",
        "full_name": "Pipeline Check",
        "consent": {"granted": True, "method": "signed_form"},
    }).json()["enrolment_id"]

    response = client.post(f"/customers/{enrolment_id}/card",
                           files={"file": ("card.jpg", card, "image/jpeg")})
    assert response.status_code == 200
    returned = response.json()["crops"]

    expected = extract_vertical_anchors(card)
    assert len(returned) == len(expected)

    for crop, reference in zip(returned, expected):
        decoded = Image.open(io.BytesIO(base64.b64decode(crop["preview_png_base64"])))
        assert np.array_equal(np.asarray(decoded.convert("L")),
                              np.asarray(reference.convert("L")))
