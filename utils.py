import cv2
import numpy as np
import torch
import torch.nn as nn
from PIL import Image

# ==========================================
# 1. Image Preprocessing Pipeline
# ==========================================
class UnifiedSignatureTransform(object):
    """
    Applies the full preprocessing pipeline on the fly:
    Otsu Binarization -> Horizontal Line Removal -> Deskew -> Crop -> Pad -> Resize.
    """
    def __call__(self, img):
        img_np = np.array(img)

        # 1. Blur & Binarize (Inverse: Ink becomes 255, Paper becomes 0)
        blurred = cv2.GaussianBlur(img_np, (5, 5), 0)
        _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        # 2. Horizontal Line Removal (Detect continuous straight pixels)
        # Create a horizontal kernel (length is 20% of image width)
        kernel_length = max(10, img_np.shape[1] // 5)
        horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_length, 1))
        
        # Detect the lines
        detected_lines = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, horizontal_kernel, iterations=2)
        
        # Dilate slightly to ensure the entire thickness of the line is covered
        dilate_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        detected_lines = cv2.dilate(detected_lines, dilate_kernel, iterations=1)
        
        # Subtract the detected line from the thresholded image
        thresh = cv2.subtract(thresh, detected_lines)

        # 3. Deskew (Calculate angle using moments on the cleaned image)
        M_moments = cv2.moments(thresh)
        angle = 0
        if M_moments['m00'] > 0:
            mu20 = M_moments['mu20']
            mu02 = M_moments['mu02']
            mu11 = M_moments['mu11']
            if (mu20 - mu02) != 0:
                angle_rad = 0.5 * np.arctan2(2 * mu11, mu20 - mu02)
                angle_deg = np.degrees(angle_rad)
                if -45 < angle_deg < 45: angle = angle_deg

        (h, w) = img_np.shape[:2]
        center = (w // 2, h // 2)
        M_rot = cv2.getRotationMatrix2D(center, angle, 1.0)
        rotated = cv2.warpAffine(thresh, M_rot, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=0)

        # 4. Crop tightly around the remaining ink
        coords = cv2.findNonZero(rotated)
        if coords is not None and len(coords) > 50:
            x, y, w_crop, h_crop = cv2.boundingRect(coords)
            pad = 15
            x1, y1 = max(0, x - pad), max(0, y - pad)
            x2, y2 = min(w, x + w_crop + pad), min(h, y + h_crop + pad)
            cropped = rotated[y1:y2, x1:x2]
        else:
            cropped = rotated

        # 5. Pad to square & Resize (Model input format)
        h_c, w_c = cropped.shape[:2]
        target_size = max(h_c, w_c)
        top = (target_size - h_c) // 2
        bottom = target_size - h_c - top
        left = (target_size - w_c) // 2
        right = target_size - w_c - left

        squared = cv2.copyMakeBorder(cropped, top, bottom, left, right, cv2.BORDER_CONSTANT, value=0)
        final_img = cv2.resize(squared, (224, 224))

        return Image.fromarray(final_img)

# Keep the rest of utils.py (extract_vertical_anchors, CustomSiameseCNN) exactly as they were!