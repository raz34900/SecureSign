"""Input sanity check: dark / blank / unreadable images."""
import cv2
import numpy as np

# Extraction leaves a margin of paper around the ink it cut out, so ink sitting on the
# edge of a region means the stroke continued past it. A few pixels are threshold noise;
# a stroke is thicker than that.
CLIPPED_STROKE_PIXELS = 8


# Writing is wider than it is tall, but not by as much as this project first measured:
# a looping two-letter signature photographed close up came out at 0.94. Page edges,
# registration marks and background clutter measure 0.26 to 0.80, so 0.85 separates them.
MIN_ASPECT = 0.85

# Handwriting is sparse. Genuine crops measure 0.05 to 0.17 ink; a solid block is a
# blown-out shadow or a filled rectangle, not a signature.
MAX_INK_FRACTION = 0.6

# Below this there is not enough left to compare. Background specks come out of cleanup
# blank and a torn scrap of a stroke carries ~1300 pixels; the smallest genuine cleaned
# crop measured across three writers carries ~6000. A blank or near-blank crop still
# embeds - to a garbage vector that poisons every verification against that customer.
MIN_INK_PIXELS = 1500


def looks_like_signature(region: np.ndarray) -> bool:
    """Cheap plausibility check on an extracted region.

    Deliberately loose. Its job is to drop things that cannot be handwriting at all, not
    to judge handwriting - a specimen that merely looks unlike its siblings is the
    consistency check's business, and rejecting it here would hide a real mismatch.
    """
    height, width = region.shape[:2]
    if height == 0 or width == 0:
        return False
    if width / height < MIN_ASPECT:
        return False
    ink = region < 128
    if int(ink.sum()) < MIN_INK_PIXELS:
        return False
    return float(ink.mean()) <= MAX_INK_FRACTION


def region_is_clipped(region: np.ndarray) -> bool:
    """Did the writing continue past the edge of what was cut out?

    The transform crops tightly to the ink then scales to a fixed square, so ink that
    fell outside the picture changes the apparent size of everything inside it, and the
    model is sensitive to scale. Four photographs of one signature: framing alone put the
    nearest pair at 0.1189 and the furthest at 0.4862, either side of the 0.3999
    threshold, with a trailing stroke running off the picture in one of them.
    """
    ink = region < 128
    return any(int(border.sum()) >= CLIPPED_STROKE_PIXELS
               for border in (ink[0, :], ink[-1, :], ink[:, 0], ink[:, -1]))


def validate_image_quality(image_bytes: bytes) -> tuple[bool, str]:
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return False, "Could not read the image data."

    if float(np.mean(img)) < 80:
        return False, "The image is too dark. Please capture it again in a well-lit area."

    _, thresh = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    if cv2.countNonZero(thresh) < 300:
        return False, "The image appears to be blank. No valid signature was detected."
    return True, "Valid"
