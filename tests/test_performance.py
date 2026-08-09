import time
import numpy as np
import torch
import torchvision.transforms as transforms
from PIL import Image
import os
import sys

# Add the root directory to the path so we can import our modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import CustomSiameseCNN, UnifiedSignatureTransform


def test_verification_latency():
    print("Loading model and preparing test environment...")
    device = torch.device('cpu')
    model = CustomSiameseCNN(embedding_dim=128).to(device)
    
    # Load model weights (ensure the path is correct)
    model_path = os.path.join("..", "models", "secure_sign_epoch_50_loss_0.2009_acc_83.48.pth")
    if os.path.exists(model_path):
        model.load_state_dict(torch.load(model_path, map_location=device, weights_only=True))
    model.eval()

    transform = transforms.Compose([UnifiedSignatureTransform(), transforms.ToTensor()])
    
    # Create a dummy image simulating a scanned signature to test the engine
    dummy_image = Image.new('L', (800, 400), color=255)
    
    latency_times = []
    iterations = 50

    print(f"Running {iterations} consecutive automated latency measurements (NFR-01)...")
    
    for i in range(iterations):
        start_time = time.time()
        
        # 1. Image Preprocessing
        tensor_img = transform(dummy_image).unsqueeze(0).to(device)
        
        # 2. Model Inference
        with torch.no_grad():
            out1, out2 = model(tensor_img, tensor_img)
            
        end_time = time.time()
        latency_times.append(end_time - start_time)

    # Calculate results
    p95_latency = np.percentile(latency_times, 95)
    mean_latency = np.mean(latency_times)
    
    print("\n--- PERFORMANCE TEST RESULTS ---")
    print(f"Mean Latency: {mean_latency:.3f} seconds")
    print(f"95th Percentile Latency: {p95_latency:.3f} seconds")
    
    if p95_latency < 2.0:
        print("✅ TEST PASSED: 95% of executions completed in under 2 seconds.")
    else:
        print("❌ TEST FAILED: Latency exceeded 2 seconds.")

if __name__ == "__main__":
    test_verification_latency()