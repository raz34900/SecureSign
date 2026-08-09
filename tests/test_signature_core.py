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
