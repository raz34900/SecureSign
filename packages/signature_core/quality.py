"""Input sanity check: dark / blank / unreadable images."""
import cv2
import numpy as np


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
