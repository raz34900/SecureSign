"""Input sanity check: dark / blank / unreadable images."""
import cv2
import numpy as np

# Extraction leaves a margin of paper around the ink it cut out, so ink sitting on the
# edge of a region means the stroke continued past it. A few pixels are threshold noise;
# a stroke is thicker than that.
CLIPPED_STROKE_PIXELS = 8


# A region cut out of a document is a band of a line of writing, so it is always wider
# than it is tall - the narrowest genuine signature measured on this project's own cards,
# cheques and photographs is 1.79. What comes in under 1.0 is the dark edge of the page,
# the shadow down one side of a phone photograph, or a registration mark: measured at
# 0.50 and 0.68 on a real cheque, and far lower on a photographed card whose right-hand
# border was picked up as a "signature" and then failed the consistency check.
MIN_ASPECT = 1.0

# Handwriting is sparse. Genuine crops measure 0.05 to 0.17 ink; a solid block is a
# blown-out shadow or a filled rectangle, not a signature.
MAX_INK_FRACTION = 0.6


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
    return float((region < 128).mean()) <= MAX_INK_FRACTION


def region_is_clipped(region: np.ndarray) -> bool:
    """Did the writing continue past the edge of what was cut out?

    This matters more than it looks. The preprocessing transform crops tightly to the
    ink and then scales that crop to a fixed square, so ink that fell outside the
    picture changes the apparent size of everything still inside it - and the model is
    sensitive to scale. Measured on four photographs of one physical signature, framing
    alone put the two nearest at 0.1189 and the two furthest at 0.4862, either side of
    the 0.3999 threshold. The furthest pair were the two framed differently, and the
    long trailing stroke ran off the picture in one of them.
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
