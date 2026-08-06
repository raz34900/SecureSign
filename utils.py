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

# ==========================================
# 2. Smart Anchor Extraction
# ==========================================
def extract_vertical_anchors(image_path, min_area=800):
    """
    Extracts signatures that are written one under the other from a single document.
    """
    img = cv2.imread(image_path)
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

    bounding_boxes = []
    img_h, img_w = gray.shape

    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        area = w * h
        if area > min_area and area < (img_w * img_h * 0.8) and h > 20:
            bounding_boxes.append((x, y, w, h))

    # Sort boxes from top to bottom
    bounding_boxes = sorted(bounding_boxes, key=lambda b: b[1])

    extracted_anchors = []
    for idx, (x, y, w, h) in enumerate(bounding_boxes):
        pad = 15
        y1 = max(0, y - pad)
        y2 = min(gray.shape[0], y + h + pad)
        x1 = max(0, x - pad)
        x2 = min(gray.shape[1], x + w + pad)

        roi = gray[y1:y2, x1:x2]
        pil_img = Image.fromarray(roi).convert('L')
        extracted_anchors.append(pil_img)

    return extracted_anchors

# ==========================================
# 3. Custom Siamese CNN Architecture
# ==========================================
class CustomSiameseCNN(nn.Module):
    """
    A custom, lightweight CNN architecture designed specifically for
    signature verification to prevent overfitting.
    """
    def __init__(self, embedding_dim=128):
        super(CustomSiameseCNN, self).__init__()

        self.features = nn.Sequential(
            # Block 1
            nn.Conv2d(1, 32, kernel_size=3, stride=1, padding=1),
            nn.BatchNorm2d(32),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(kernel_size=2, stride=2),

            # Block 2
            nn.Conv2d(32, 64, kernel_size=3, stride=1, padding=1),
            nn.BatchNorm2d(64),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(kernel_size=2, stride=2),

            # Block 3
            nn.Conv2d(64, 128, kernel_size=3, stride=1, padding=1),
            nn.BatchNorm2d(128),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(kernel_size=2, stride=2),

            # Block 4
            nn.Conv2d(128, 256, kernel_size=3, stride=1, padding=1),
            nn.BatchNorm2d(256),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(kernel_size=2, stride=2)
        )

        self.fc = nn.Sequential(
            nn.Linear(256 * 14 * 14, 512),
            nn.BatchNorm1d(512),
            nn.ReLU(inplace=True),
            nn.Dropout(p=0.6),
            nn.Linear(512, embedding_dim)
        )

    def forward_once(self, x):
        x = self.features(x)
        x = x.view(x.size(0), -1)
        x = self.fc(x)
        return x

    def forward(self, input1, input2):
        output1 = self.forward_once(input1)
        output2 = self.forward_once(input2)
        return output1, output2