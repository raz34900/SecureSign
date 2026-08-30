"""Strip non-signature marks from a region cut out of a document.

This runs before `UnifiedSignatureTransform`, never inside it: the transform is
shared with training, and changing it would break train/serve parity.

A region cut from a real document carries more than the signature - a cheque brings
corner registration squares and a reference number, which survive binarisation and
inflate the bounding box the transform crops to, leaving the signature a fraction of the
224x224 input. Measured on a real cheque: 0.4696 raw (rejected), 0.2350 cleaned
(accepted).
"""
import io
import math

import cv2
import numpy as np
from PIL import Image

from signature_core.anchors import extract_vertical_anchors
from signature_core.quality import MAX_INK_FRACTION, MIN_INK_PIXELS, looks_like_signature

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


def pad_for_rotation(img: Image.Image) -> Image.Image:
    """Give the deskew room to turn in, so it stops cutting the ends off the writing.

    The transform rotates about the centre into a same-sized canvas, so whatever swings
    outside is discarded - and a signature is wide, short and slanted, which puts its
    first and last strokes where the arc is widest. Four photographs, deskew of -12° to
    -13.5°, destroying 2.6% to 4.4% of the ink each time.

    Padding to a square of the diagonal means no centre rotation can push ink off canvas;
    the tight crop afterwards keeps the padding away from the model. Over the same four
    photographs mean distance fell 0.2835 to 0.1828 and the worst pair 0.4862 to 0.2711,
    from one pair reading FRAUD to all six agreeing. Both sides must be padded or neither.
    """
    side = math.ceil(math.hypot(*img.size))
    padded = Image.new("L", (side, side), PAPER)
    padded.paste(img.convert("L"), ((side - img.width) // 2, (side - img.height) // 2))
    return padded


def flatten_image_bytes(image_bytes: bytes) -> bytes:
    """Even out lighting before extraction, and return encoded bytes.

    Extraction thresholds the whole frame with one Otsu cut, so a shadow across a
    close-up hides the strokes it falls on and the signature is found in pieces or not
    at all. Flattening afterwards is too late - by then extraction has already decided
    what to cut out. Re-encoded as PNG so nothing is lost to compression, and the
    extractor's own decode stays exactly as it was.
    """
    gray = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        return image_bytes
    ok, encoded = cv2.imencode(".png", flatten_illumination(gray))
    return encoded.tobytes() if ok else image_bytes


# How far above or below the main stroke a detached mark may sit and still be part of
# the signature, as a fraction of the main stroke's own height.
ACCENT_REACH = 0.25

# How far to the side of the main stroke a detached letter may sit, as a fraction of the
# main stroke's own height. Letter spacing within one signature is under a letter-height;
# a cheque's corner squares and reference number sit whole signature-widths away.
NEIGHBOUR_REACH = 1.0


def _belongs_to(blob, main) -> bool:
    """Is this detached mark part of the signature rather than document furniture?

    Two ways in. An accent - a dot over an i, a diacritic, a crossed t - sits within the
    horizontal run of the writing and hugs it vertically. A detached letter - the ר of a
    רז written with daylight between the letters - sits just beside the main stroke on
    the same line. Both are far smaller than a quarter of the signature, so the size rule
    alone deletes them. Furniture sits out at the margins, whole signature-widths away.
    """
    left, top, width, height = (blob[cv2.CC_STAT_LEFT], blob[cv2.CC_STAT_TOP],
                                blob[cv2.CC_STAT_WIDTH], blob[cv2.CC_STAT_HEIGHT])
    main_left, main_top, main_width, main_height = (
        main[cv2.CC_STAT_LEFT], main[cv2.CC_STAT_TOP],
        main[cv2.CC_STAT_WIDTH], main[cv2.CC_STAT_HEIGHT])
    rows_overlap = (top < main_top + main_height) and (top + height > main_top)
    if left < main_left or left + width > main_left + main_width:
        gap = max(main_left - (left + width), left - (main_left + main_width))
        return rows_overlap and gap <= NEIGHBOUR_REACH * main_height
    reach = ACCENT_REACH * main_height
    return (top + height >= main_top - reach) and (top <= main_top + main_height + reach)


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
    main = stats[1 + int(areas.argmax())]
    keep = {index + 1 for index, area in enumerate(areas)
            if area >= largest * min_area_ratio or _belongs_to(stats[index + 1], main)}
    if len(keep) == count - 1:
        return flattened

    kept_mask = np.isin(labels, list(keep))
    cleaned = np.where(kept_mask, source, PAPER).astype(np.uint8)
    return Image.fromarray(cleaned)


# At most this many surviving regions reads as a close-up of one signature, where the
# extractor may have split the letters apart; a specimen card yields far more.
CLOSE_UP_REGIONS = 3


def candidate_crops(image_bytes: bytes) -> list[Image.Image]:
    """Every region of a photograph that could be a signature, prepared for the model.

    One copy, because enrolment and verification must prepare images identically - a
    reference and a query prepared differently are not comparable. Flatten first:
    extraction thresholds globally and cannot see past a shadow. Then drop what cannot be
    handwriting, because a photographed page's dark edge extracts like any other region.

    A close-up of a signature written with space between its letters extracts as one
    region per letter, and no piece is the signature. The extractor cannot be widened -
    it is shared with training - so a photograph that yields only a few regions also
    offers the whole frame prepared the same way, letters reunited.
    """
    even = flatten_image_bytes(image_bytes)
    regions = extract_vertical_anchors(even)
    crops = [crop for crop in (isolate_signature_ink(region) for region in regions)
             if looks_like_signature(np.asarray(crop.convert("L")))]
    # One region that survived intact is the ordinary close-up and needs no company.
    # Several small regions are letters split apart; fewer kept than found means the
    # filter discarded pieces. Both are reasons to offer the frame as well.
    if len(crops) <= CLOSE_UP_REGIONS and (len(crops) != 1 or len(crops) < len(regions)):
        whole = isolate_signature_ink(
            Image.open(io.BytesIO(even)).convert("L"))
        pixels = np.asarray(whole.convert("L"))
        ink = pixels < 128
        # The frame's own shape says nothing about the writing on it, so the aspect
        # rule does not apply here - a portrait photo of a wide signature is fine.
        if int(ink.sum()) >= MIN_INK_PIXELS and float(ink.mean()) <= MAX_INK_FRACTION:
            crops.append(whole)
    return crops
