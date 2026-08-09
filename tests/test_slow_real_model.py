import os
import time

import numpy as np
import pytest
from PIL import Image

from signature_core.decision import decide
from signature_core.embed import Embedder

WEIGHTS = "models/secure_sign_epoch_50_loss_0.2009_acc_83.48.pth"
SAMPLE_DIR = "mock_database/123456789"

pytestmark = pytest.mark.slow

needs_weights = pytest.mark.skipif(not os.path.exists(WEIGHTS), reason="real weights not present")
needs_samples = pytest.mark.skipif(not os.path.isdir(SAMPLE_DIR), reason="mock_database not present")


@pytest.fixture(scope="module")
def embedder():
    return Embedder.load(WEIGHTS)


def sample_images() -> list[Image.Image]:
    files = sorted(f for f in os.listdir(SAMPLE_DIR) if f.endswith((".jpg", ".png")))
    return [Image.open(os.path.join(SAMPLE_DIR, f)).convert("L") for f in files]


@needs_weights
@needs_samples
def test_genuine_same_person_low_distance(embedder):
    imgs = sample_images()
    assert len(imgs) >= 2
    refs = [embedder.embed(i) for i in imgs[:-1]]
    query = embedder.embed(imgs[-1])
    result = decide([float(np.linalg.norm(r - query)) for r in refs])
    assert result.verdict == "VALID"


@needs_weights
@needs_samples
def test_metamorphic_rotation_and_scale(embedder):
    """Book 10.1.7: small rotation / margin crop / mild rescale must not flip the verdict."""
    imgs = sample_images()
    refs = [embedder.embed(i) for i in imgs[:-1]]
    base_img = imgs[-1]

    def distances(img):
        q = embedder.embed(img)
        return [float(np.linalg.norm(r - q)) for r in refs]

    base = decide(distances(base_img))
    rotated = decide(distances(base_img.rotate(5, fillcolor=255)))
    w, h = base_img.size
    scaled = decide(distances(base_img.resize((int(w * 0.8), int(h * 0.8)))))

    assert rotated.verdict == base.verdict
    assert scaled.verdict == base.verdict


@needs_weights
@needs_samples
def test_latency_p95_under_2s(embedder):
    imgs = sample_images()
    refs = [embedder.embed(i) for i in imgs[:-1]]
    times = []
    for _ in range(50):
        start = time.perf_counter()
        q = embedder.embed(imgs[-1])
        decide([float(np.linalg.norm(r - q)) for r in refs])
        times.append(time.perf_counter() - start)
    p95 = sorted(times)[int(0.95 * len(times)) - 1]
    assert p95 < 2.0, f"p95={p95:.3f}s"
