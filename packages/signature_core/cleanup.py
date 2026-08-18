"""Strip non-signature marks from a region cut out of a document.

This runs before `UnifiedSignatureTransform`, never inside it: the transform is
shared with training, and changing it would break train/serve parity.

A region cut from a real document carries more than the signature. A cheque brings
corner registration squares and a small reference number. Those survive binarisation,
and because the transform crops tightly around every remaining mark, they inflate the
bounding box and leave the signature occupying a fraction of the model's 224x224
input. Measured on a real cheque: the raw region scored 0.4696 (rejected) while the
same signature with these marks removed scored 0.2350 (accepted).
"""
import cv2
import numpy as np
from PIL import Image

DEFAULT_MIN_AREA_RATIO = 0.25

PAPER = 255

# Wide enough to span the strokes, so the closing sees paper rather than ink.
BACKGROUND_KERNEL = 51


def flatten_illumination(gray: np.ndarray) -> np.ndarray:
    """Divide out the lighting, the way a document scanner does.

    A close-up photograph carries the phone's own shadow, and Otsu picks one threshold
    for the whole image: a shadowed corner either swallows the signature or is read as
    ink. Estimating the background with a morphological close and dividing by it leaves
    the strokes and flattens everything else to paper.
    """
    background = cv2.morphologyEx(
        gray, cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (BACKGROUND_KERNEL, BACKGROUND_KERNEL)))
    return cv2.divide(gray, background, scale=PAPER)


def flatten_image_bytes(image_bytes: bytes) -> bytes:
    """Even out lighting before extraction, and return encoded bytes.

    Extraction thresholds the whole frame with one Otsu cut, so a shadow across a
    close-up hides the strokes it falls on and the signature is found in pieces or not
    at all. Flattening afterwards is too late — by then extraction has already decided
    what to cut out. Re-encoded as PNG so nothing is lost to compression, and the
    extractor's own decode stays exactly as it was.
    """
    gray = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        return image_bytes
    ok, encoded = cv2.imencode(".png", flatten_illumination(gray))
    return encoded.tobytes() if ok else image_bytes


def isolate_signature_ink(img: Image.Image,
                          min_area_ratio: float = DEFAULT_MIN_AREA_RATIO) -> Image.Image:
    """Blank out ink blobs far smaller than the dominant one.

    Returns a grayscale image with the same dimensions, so the caller can hand it to
    the normal preprocessing transform. Illumination is flattened first, so the result
    is always the evenly-lit image even when there are no blobs to strip.
    """
    source = flatten_illumination(np.array(img.convert("L")))
    flattened = Image.fromarray(source)

    blurred = cv2.GaussianBlur(source, (5, 5), 0)
    _, ink = cv2.threshold(blurred, 0, PAPER, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    rule_length = max(10, ink.shape[1] // 5)
    rules = cv2.morphologyEx(
        ink, cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (rule_length, 1)), iterations=2)
    rules = cv2.dilate(rules, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
    ink = cv2.subtract(ink, rules)

    joined = cv2.morphologyEx(
        ink, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9)))

    count, labels, stats, _ = cv2.connectedComponentsWithStats(joined, connectivity=8)
    if count <= 1:
        return flattened

    areas = stats[1:, cv2.CC_STAT_AREA]
    largest = int(areas.max())
    keep = {index + 1 for index, area in enumerate(areas)
            if area >= largest * min_area_ratio}
    if len(keep) == count - 1:
        return flattened

    kept_mask = np.isin(labels, list(keep))
    cleaned = np.where(kept_mask, source, PAPER).astype(np.uint8)
    return Image.fromarray(cleaned)
