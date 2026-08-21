import numpy as np
import torch
from PIL import Image, ImageDraw

from signature_core.preprocess import UnifiedSignatureTransform
from signature_core.model import CustomSiameseCNN
from signature_core.decision import THRESHOLD, calculate_confidence, decide, mean_distance


def make_signature(seed: int = 1, size: tuple[int, int] = (400, 200)) -> Image.Image:
    img = Image.new("L", size, 255)
    d = ImageDraw.Draw(img)
    rng = np.random.default_rng(seed)
    pts = [(int(x), int(y)) for x, y in zip(rng.integers(20, size[0] - 20, 12),
                                            rng.integers(20, size[1] - 20, 12))]
    d.line(pts, fill=0, width=4)
    return img


def test_preprocess_output_shape_and_determinism():
    t = UnifiedSignatureTransform()
    img = make_signature()
    out1, out2 = t(img), t(img)
    assert out1.size == (224, 224)
    assert np.array_equal(np.array(out1), np.array(out2))


def test_model_batch_of_one_in_eval():
    m = CustomSiameseCNN()
    m.eval()
    x = torch.rand(1, 1, 224, 224)
    with torch.no_grad():
        v = m.forward_once(x)
    assert v.shape == (1, 128)


def test_confidence_boundaries():
    t = 0.3999
    assert calculate_confidence(0.0, t) == 99.0
    at = calculate_confidence(t, t)
    assert 79.9 < at <= 80.0
    assert calculate_confidence(5.0, t) == 0.0


def test_decide_valid_and_fraud():
    assert decide([0.1, 0.2]).verdict == "VALID"
    assert decide([0.5, 0.6]).verdict == "FRAUD"
    d = decide([0.2, 0.4])
    assert d.distance == mean_distance([0.2, 0.4])
    assert d.threshold == THRESHOLD
    # strict <: exactly at threshold is FRAUD
    assert decide([THRESHOLD]).verdict == "FRAUD"


import io

from signature_core.anchors import extract_vertical_anchors
from signature_core.embed import Embedder
from signature_core.quality import validate_image_quality


def make_specimen_card(n: int = 9, variant: int = 0) -> bytes:
    # Row pitch is a multiple of 8 so every row sits at the same JPEG block phase
    # and all n crops decode byte-identical (the card is meant to be one writer).
    #
    # `variant` stands in for a second photograph: same writer, different picture. It
    # changes the stroke, not the layout, so rows within one card stay identical to each
    # other while two variants do not collide. Enrolment drops a crop it has already
    # collected byte for byte, so a test that means "another photograph" has to hand it
    # one rather than the same file again.
    card = Image.new("L", (800, 80 + n * 184 + 100), 255)
    d = ImageDraw.Draw(card)
    for i in range(n):
        y = 80 + i * 184
        d.line([(150 + variant * 7, y), (300, y + 40 - variant * 5),
                (450, y - 10), (650 + variant * 3, y + 30)], fill=0, width=6)
    buf = io.BytesIO()
    card.convert("RGB").save(buf, format="JPEG")
    return buf.getvalue()


def png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_anchor_extraction_counts_stacked_signatures():
    crops = extract_vertical_anchors(make_specimen_card(6))
    assert 5 <= len(crops) <= 7


def test_anchor_extraction_garbage_bytes():
    assert extract_vertical_anchors(b"not an image") == []


def test_quality_rejects_blank_and_accepts_signature():
    ok, _ = validate_image_quality(png_bytes(Image.new("L", (300, 200), 255)))
    assert not ok
    ok, msg = validate_image_quality(png_bytes(make_signature()))
    assert ok and msg == "Valid"


def test_quality_rejects_dark():
    ok, _ = validate_image_quality(png_bytes(Image.new("L", (300, 200), 10)))
    assert not ok


def test_embedder_shape_and_determinism():
    emb = Embedder(CustomSiameseCNN())  # random weights fine for shape test
    v1 = emb.embed(make_signature())
    v2 = emb.embed(make_signature())
    assert v1.shape == (128,) and v1.dtype == np.float32
    assert np.allclose(v1, v2)
