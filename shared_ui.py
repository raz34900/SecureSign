import streamlit as st
import os
import tempfile
import torch
import torch.nn.functional as F
import torchvision.transforms as transforms
from PIL import Image
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import uuid
import cv2
import numpy as np

from utils import extract_vertical_anchors, UnifiedSignatureTransform

def inject_css():
    st.markdown("""
    <style>
        * { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
        h1, h2, h3 { color: #0b2b5e !important; text-align: center; }
        .subtitle { text-align: center; color: #8cc440; font-size: 1.2rem; margin-bottom: 2rem; font-weight: bold;}
        
        /* Primary Buttons */
        button[kind="primary"] { 
            background-color: #0b2b5e !important; 
            color: white !important; 
            border-radius: 8px !important; 
            font-weight: bold !important; 
            font-size: 16px !important; 
            border: none !important; 
            transition: 0.3s !important; 
        }
        button[kind="primary"]:hover { 
            background-color: #153c7a !important; 
        }
        
        /* FORCE Form Submit Buttons to be Blue (Fix for the red button) */
        div[data-testid="stFormSubmitButton"] > button,
        [data-testid="stForm"] button {
            background-color: #0b2b5e !important; 
            color: white !important; 
            border-color: #0b2b5e !important; 
            border-radius: 8px !important; 
            font-weight: bold !important; 
            font-size: 16px !important; 
            transition: 0.3s !important; 
        }
        div[data-testid="stFormSubmitButton"] > button:hover,
        [data-testid="stForm"] button:hover {
            background-color: #153c7a !important; 
            border-color: #153c7a !important; 
        }
        
        /* Secondary Action Buttons */
        button[kind="secondary"] { 
            background-color: transparent !important; 
            color: #b3b3b3 !important; 
            border: 0px solid transparent !important; 
            font-size: 18px !important; 
            box-shadow: none !important; 
            margin: 0 auto !important; 
            display: block; 
            padding: 0 !important; 
        }
        button[kind="secondary"]:hover, 
        button[kind="secondary"]:focus { 
            color: #ff4b4b !important; 
            background-color: transparent !important; 
            box-shadow: none !important; 
            border: 0px solid transparent !important; 
        }
        
        /* Logout Button specifically */
        .logout-btn>div>button { background-color: #f0f2f6 !important; color: #333 !important; height: 40px !important; border-radius: 8px !important;}
        .logout-btn>div>button:hover { background-color: #e0e2e6 !important; color: #333 !important; }
        
        /* Custom Camera Tips */
        .camera-tip { background-color: #e8f4f8; padding: 10px; border-radius: 8px; border-left: 4px solid #153c7a; margin-bottom: 15px; font-size: 0.9rem;}
    </style>
    """, unsafe_allow_html=True)

def calculate_confidence(distance, threshold=0.40):
    if distance <= threshold:
        conf = 99.0 - (distance / threshold) * 19.0
    else:
        conf = 79.0 - min(1.0, (distance - threshold) / (2.0 - threshold)) * 79.0
    return max(0.0, min(99.9, conf))

def render_id_form(key_prefix):
    """
    Centralized ID input form with a blue button, restricted width,
    perfect alignment, and strict input validation.
    """
    with st.form(f"{key_prefix}_id_form"):
        col1, col2, col3 = st.columns([3, 3, 6])
        with col1:
            cust_id = st.text_input("Customer ID (9 Digits):", max_chars=9, placeholder="123456789")
        with col2:
            st.markdown("<div style='padding-top: 28px;'></div>", unsafe_allow_html=True)
            submit = st.form_submit_button("Check Customer", use_container_width=True)
            
    if submit:
        if not cust_id:
            st.warning("Please enter a Customer ID.")
            return None
        if not cust_id.isdigit():
            st.error("❌ Invalid Input: Customer ID must contain numbers only (no letters or special characters).")
            return None
        if len(cust_id) != 9:
            st.error("❌ Invalid Input: Customer ID must be exactly 9 digits long.")
            return None
        return cust_id
        
    return None

def validate_image_quality(file_obj):
    """
    Strictly validates if the image is too dark or empty.
    """
    file_bytes = np.asarray(bytearray(file_obj.read()), dtype=np.uint8)
    img = cv2.imdecode(file_bytes, cv2.IMREAD_GRAYSCALE)
    file_obj.seek(0) 
    
    if img is None:
        return False, "Could not read the image data."
        
    mean_brightness = np.mean(img)
    if mean_brightness < 80: 
        return False, "The image is too dark. Please capture it again in a well-lit area."
        
    _, thresh = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    ink_pixels = cv2.countNonZero(thresh)
    
    if ink_pixels < 300: 
        return False, "The image appears to be blank. No valid signature was detected."

    return True, "Valid"

def get_image_input(label, key_prefix, show_tips=True, is_business=False):
    """Handles image input, displays context-aware tips, and validates quality instantly."""
    if show_tips:
        if is_business:
            st.markdown("<div class='camera-tip'>📸 <b>Capture Tips:</b> Ensure the signature is centered, the room is well-lit, and your device is held parallel to the paper.</div>", unsafe_allow_html=True)
        else:
            st.markdown("<div class='camera-tip'>📸 <b>Capture Tips:</b> Ensure the signature is centered, well-lit, device is parallel to the paper, and don't worry about printed lines.</div>", unsafe_allow_html=True)
        
    method = st.radio(f"Choose input method for {label}:", ["Upload File", "Camera"], horizontal=True, key=f"{key_prefix}_radio")
    
    file_obj = None
    if method == "Camera":
        file_obj = st.camera_input(f"Capture {label}", key=f"{key_prefix}_cam")
    else:
        file_obj = st.file_uploader(f"Upload {label}", type=['png', 'jpg', 'jpeg', 'pdf'], key=f"{key_prefix}_up")
        
    if file_obj:
        is_valid, error_msg = validate_image_quality(file_obj)
        if not is_valid:
            st.error(f"❌ {error_msg}")
            return None 
        return file_obj
        
    return None

def process_uploaded_document(file_obj):
    with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp:
        tmp.write(file_obj.getvalue())
        tmp_path = tmp.name
    anchors = extract_vertical_anchors(tmp_path)
    os.remove(tmp_path)
    return anchors

def save_anchors_to_db(cust_dir, anchors_list):
    os.makedirs(cust_dir, exist_ok=True)
    for img in anchors_list:
        unique_filename = f"anchor_{uuid.uuid4().hex[:8]}.jpg"
        img.save(os.path.join(cust_dir, unique_filename))

def run_verification_and_display(siamese_model, anchors_list, test_image_file, show_anchors=True):
    device = torch.device('cpu')
    transform = transforms.Compose([UnifiedSignatureTransform(), transforms.ToTensor()])
    
    with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp_test:
        tmp_test.write(test_image_file.getvalue())
        test_path = tmp_test.name
        
    try:
        test_img = Image.open(test_path).convert('L')
        test_tensor = transform(test_img).unsqueeze(0).to(device)

        distances = []
        processed_anchors_for_display = []

        with torch.no_grad():
            for anchor_img in anchors_list:
                anchor_tensor = transform(anchor_img).unsqueeze(0).to(device)
                processed_anchors_for_display.append(anchor_tensor.cpu().squeeze().numpy())
                
                out1, out2 = siamese_model(anchor_tensor, test_tensor)
                dist = F.pairwise_distance(out1, out2).item()
                distances.append(dist)

        avg_distance = sum(distances) / len(distances)
        threshold = 0.3999
        is_genuine = avg_distance < threshold
        final_confidence = calculate_confidence(avg_distance, threshold)

        main_color = 'green' if is_genuine else 'red'
        decision_text = "APPROVED (Genuine)" if is_genuine else "REJECTED (Forgery)"
        
        if show_anchors:
            num_anchors = len(processed_anchors_for_display)
            cols = 5 
            rows = (num_anchors - 1) // cols + 1
            
            fig = plt.figure(figsize=(14, 3 * rows + 4))
            gs = gridspec.GridSpec(rows + 1, cols, figure=fig, height_ratios=[1]*rows + [2])
            
            fig.suptitle(f"System Decision: {decision_text} | Confidence: {final_confidence:.1f}%", color=main_color, fontsize=18, fontweight='bold', y=0.98)
            
            for i, proc_anchor in enumerate(processed_anchors_for_display):
                r = i // cols
                c = i % cols
                ax = fig.add_subplot(gs[r, c])
                ax.imshow(1.0 - proc_anchor, cmap='gray')
                
                dist = distances[i]
                anchor_pass = dist < threshold
                color = 'green' if anchor_pass else '#d62728'
                conf = calculate_confidence(dist, threshold)
                ax.set_title(f"Anchor {i+1}\nMatch: {conf:.1f}%", color=color, fontsize=12, fontweight='bold')
                ax.axis('off')

            ax_test = fig.add_subplot(gs[rows, :])
            ax_test.imshow(1.0 - test_tensor.cpu().squeeze().numpy(), cmap='gray')
            ax_test.set_title("SCANNED SIGNATURE (Line Removed, Cropped & Deskewed)", fontweight='bold', fontsize=14, color='#153c7a')
            ax_test.axis('off')
            
            plt.tight_layout(rect=[0, 0, 1, 0.95])
            st.pyplot(fig)
        else:
            fig = plt.figure(figsize=(8, 4))
            ax_test = plt.subplot(1, 1, 1)
            ax_test.imshow(1.0 - test_tensor.cpu().squeeze().numpy(), cmap='gray')
            ax_test.set_title(f"Decision: {decision_text} ({final_confidence:.1f}%)", fontweight='bold', fontsize=16, color=main_color)
            ax_test.axis('off')
            plt.tight_layout()
            st.pyplot(fig)
            
        return is_genuine, final_confidence, test_img
    finally:
        os.remove(test_path)