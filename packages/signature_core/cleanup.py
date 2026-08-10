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


def isolate_signature_ink(img: Image.Image,
                          min_area_ratio: float = DEFAULT_MIN_AREA_RATIO) -> Image.Image:
    """Blank out ink blobs far smaller than the dominant one.

    Returns a grayscale image with the same dimensions, so the caller can hand it to
    the normal preprocessing transform. If nothing is confidently removable the input
    is returned unchanged, which keeps an already-clean crop untouched.
    """
    source = np.array(img.convert("L"))

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
        return img

    areas = stats[1:, cv2.CC_STAT_AREA]
    largest = int(areas.max())
    keep = {index + 1 for index, area in enumerate(areas)
            if area >= largest * min_area_ratio}
    if len(keep) == count - 1:
        return img

    kept_mask = np.isin(labels, list(keep))
    cleaned = np.where(kept_mask, source, PAPER).astype(np.uint8)
    return Image.fromarray(cleaned)
