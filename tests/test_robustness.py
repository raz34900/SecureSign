import numpy as np
import torch
import torchvision.transforms as transforms
from PIL import Image, ImageDraw
import os
import sys

# Add the root directory to the path so we can import our modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import CustomSiameseCNN, UnifiedSignatureTransform
from shared_ui import calculate_confidence


def test_scale_and_rotation_robustness():
    print("Loading model for robustness test (NFR-04)...")
    device = torch.device('cpu')
    model = CustomSiameseCNN(embedding_dim=128).to(device)
    
    # Load model weights
    model_path = os.path.join("..", "models", "secure_sign_epoch_50_loss_0.2009_acc_83.48.pth")
    if os.path.exists(model_path):
        model.load_state_dict(torch.load(model_path, map_location=device, weights_only=True))
    model.eval()

    transform = transforms.Compose([UnifiedSignatureTransform(), transforms.ToTensor()])
    
    # Create a synthetic signature image
    original_img = Image.new('L', (800, 400), color=255)
    draw = ImageDraw.Draw(original_img)
    draw.line((200, 200, 600, 200), fill=0, width=5)
    draw.arc((300, 150, 500, 250), start=0, end=180, fill=0, width=5)

    # Create a rotated and scaled version of the same image
    altered_img = original_img.copy()
    altered_img = altered_img.rotate(15, expand=True, fillcolor=255) # Rotate by 15 degrees
    altered_img = altered_img.resize((int(altered_img.width * 0.5), int(altered_img.height * 0.5))) # Scale down by 50%

    print("Extracting embeddings for both images...")
    
    with torch.no_grad():
        tensor_original = transform(original_img).unsqueeze(0).to(device)
        tensor_altered = transform(altered_img).unsqueeze(0).to(device)
        
        # We compare the original to itself to get the baseline distance (should be 0)
        out_base1, out_base2 = model(tensor_original, tensor_original)
        base_distance = torch.nn.functional.pairwise_distance(out_base1, out_base2).item()
        
        # We compare the original to the altered version
        out_alt1, out_alt2 = model(tensor_original, tensor_altered)
        altered_distance = torch.nn.functional.pairwise_distance(out_alt1, out_alt2).item()

    threshold = 0.3999
    base_confidence = calculate_confidence(base_distance, threshold)
    altered_confidence = calculate_confidence(altered_distance, threshold)
    
    deviation = abs(base_confidence - altered_confidence)

    print("\n--- ROBUSTNESS TEST RESULTS ---")
    print(f"Baseline Confidence (Identical): {base_confidence:.2f}%")
    print(f"Altered Confidence (Rotated & Scaled): {altered_confidence:.2f}%")
    print(f"Deviation: {deviation:.2f}%")
    
    if deviation <= 5.0:
        print("✅ TEST PASSED: The algorithm is robust to scale and rotation (deviation < 5%).")
    else:
        print("❌ TEST FAILED: Deviation exceeded 5%.")

if __name__ == "__main__":
    test_scale_and_rotation_robustness()