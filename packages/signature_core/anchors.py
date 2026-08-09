"""Specimen-card signature extraction (vertically stacked signatures)."""
import cv2
import numpy as np
from PIL import Image


def extract_vertical_anchors(image_bytes: bytes, min_area: int = 800) -> list[Image.Image]:
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return []

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (7, 7), 0)
    _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    kernel_clean = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    clean_thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel_clean, iterations=1)

    kernel_merge = cv2.getStructuringElement(cv2.MORPH_RECT, (100, 15))
    connected = cv2.morphologyEx(clean_thresh, cv2.MORPH_CLOSE, kernel_merge, iterations=1)

    contours, _ = cv2.findContours(connected, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    img_h, img_w = gray.shape
    bounding_boxes = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        area = w * h
        if area > min_area and area < (img_w * img_h * 0.8) and h > 20:
            bounding_boxes.append((x, y, w, h))
    bounding_boxes.sort(key=lambda b: b[1])

    anchors: list[Image.Image] = []
    for x, y, w, h in bounding_boxes:
        pad = 15
        y1, y2 = max(0, y - pad), min(img_h, y + h + pad)
        x1, x2 = max(0, x - pad), min(img_w, x + w + pad)
        anchors.append(Image.fromarray(gray[y1:y2, x1:x2]).convert("L"))
    return anchors
