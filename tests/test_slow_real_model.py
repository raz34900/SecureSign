import os
import time

import numpy as np
import pytest
from PIL import Image

from signature_core.decision import decide
from signature_core.embed import Embedder

WEIGHTS = "models/secure_sign_epoch_50_loss_0.2009_acc_83.48.pth"
# mock_database is demo data and is not committed. Point this elsewhere with
# SS_TEST_SAMPLE_DIR when running against a different set of genuine signatures.
SAMPLE_DIR = os.environ.get("SS_TEST_SAMPLE_DIR", "mock_database/123456789")

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


def _paste_on_form(signature: Image.Image) -> bytes:
    """Put a real signature on a printed form, the way a clerk photographs a cheque."""
    import io

    from PIL import ImageDraw

    doc = Image.new("L", (1100, 800), 255)
    draw = ImageDraw.Draw(doc)
    y = 60
    for width in (700, 560, 620, 480):
        draw.rectangle([(70, y), (70 + width, y + 30)], fill=35)
        y += 85
    scaled = signature.resize((460, int(signature.size[1] * 460 / signature.size[0])))
    doc.paste(scaled, (330, y + 70))
    buffer = io.BytesIO()
    doc.convert("RGB").save(buffer, format="JPEG", quality=95)
    return buffer.getvalue()


@needs_weights
@needs_samples
def test_region_selection_rescues_a_signature_on_a_form(embedder):
    """Regression for the verify-path crop gap.

    Preprocessing tight-crops around every mark it finds, so a genuine signature
    photographed on a form embeds the form and is rejected. Isolating the region
    first is what makes the same signature verifiable.
    """
    import io

    from signature_core.anchors import extract_vertical_anchors

    imgs = sample_images()
    refs = [embedder.embed(i) for i in imgs[:-1]]
    document = _paste_on_form(imgs[-1])

    def distances_for(image):
        query = embedder.embed(image)
        return [float(np.linalg.norm(ref - query)) for ref in refs]

    whole_page = decide(distances_for(Image.open(io.BytesIO(document)).convert("L")))
    assert whole_page.verdict == "FRAUD", (
        "fixture no longer reproduces the bug it guards against"
    )

    regions = extract_vertical_anchors(document)
    assert regions, "no candidate region found on the form"
    best = min((decide(distances_for(crop)) for crop in regions), key=lambda d: d.distance)

    assert best.verdict == "VALID"
    assert best.distance < whole_page.distance


CHEQUE = "data/check.jpg"

needs_cheque = pytest.mark.skipif(
    not os.path.exists(CHEQUE),
    reason="data/check.jpg is gitignored local test data",
)


@needs_weights
@needs_samples
@needs_cheque
def test_real_cheque_signature_verifies_once_isolated(embedder):
    """End to end on a photographed cheque, the case the verify path was failing.

    The whole page embeds the form. The region as the extractor returns it still
    carries the printed reference number and two registration squares, which inflate
    the crop so the signature occupies a fraction of the model input. Only after the
    furniture is stripped does the genuine signature match.
    """
    import io

    from signature_core.anchors import extract_vertical_anchors
    from signature_core.cleanup import isolate_signature_ink

    imgs = sample_images()
    refs = [embedder.embed(i) for i in imgs]

    def verdict_for(image):
        query = embedder.embed(image)
        return decide([float(np.linalg.norm(ref - query)) for ref in refs])

    with open(CHEQUE, "rb") as f:
        page = f.read()
    regions = extract_vertical_anchors(page)
    assert regions, "extractor found nothing on the cheque"

    cleaned = [isolate_signature_ink(region) for region in regions]
    best = min((verdict_for(region) for region in cleaned), key=lambda d: d.distance)
    assert best.verdict == "VALID", (
        f"the signature on the cheque should verify once isolated, got {best.distance:.4f}"
    )

    # And the raw page on its own must not be treated as a usable query.
    whole_page = verdict_for(Image.open(io.BytesIO(page)).convert("L"))
    assert best.distance < whole_page.distance


@pytest.mark.xfail(strict=True, reason=(
    "Book 10.2.4 claims under 5% score deviation at 15 degrees and 50% rescale. "
    "Measured against the trained model: rotate -15 deviates 2.85%, rotate +15 "
    "12.95%, scale 1.5x 25.11%, scale 0.5x 131.52%. Three of four variants exceed "
    "the claim, so the book must be corrected rather than the assertion relaxed. "
    "This marker is strict: if the model improves and the test passes, the suite "
    "fails until the book and this marker are updated together."))
@needs_weights
@needs_samples
def test_robustness_to_rotation_and_scale(embedder):
    """Book 10.2.4: up to 15 degrees and 50% rescale, under 5% score deviation.

    Stronger than a verdict-stability check: a score that survives the verdict boundary
    by luck would pass that and fail this.
    """
    images = sample_images()
    references = [embedder.embed(image) for image in images[:-1]]
    original = images[-1]

    def mean_distance(image):
        query = embedder.embed(image)
        return float(np.mean([np.linalg.norm(r - query) for r in references]))

    baseline = mean_distance(original)
    width, height = original.size

    variants = {
        "rotate +15": original.rotate(15, fillcolor=255, expand=True),
        "rotate -15": original.rotate(-15, fillcolor=255, expand=True),
        "scale 0.5": original.resize((max(1, width // 2), max(1, height // 2))),
        "scale 1.5": original.resize((int(width * 1.5), int(height * 1.5))),
    }

    for label, variant in variants.items():
        deviation = abs(mean_distance(variant) - baseline) / baseline
        assert deviation < 0.05, f"{label}: score moved {deviation:.1%}, limit 5%"


@needs_weights
def test_specimen_card_extraction_accuracy():
    """Book 6.4.6: at least 90% of the signatures on a card are extracted.

    Measured over a range of card sizes so the figure is not one lucky layout.
    """
    from signature_core.anchors import extract_vertical_anchors
    from test_signature_core import make_specimen_card

    expected_total, found_total = 0, 0
    for count in (8, 9, 10, 12, 15):
        found = len(extract_vertical_anchors(make_specimen_card(count)))
        expected_total += count
        found_total += min(found, count)  # extra regions are the clerk's to deselect

    accuracy = found_total / expected_total
    assert accuracy >= 0.90, f"extraction accuracy {accuracy:.1%}, book claims 92%"
