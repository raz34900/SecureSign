import os
import sys
import io
from PIL import Image

# Add the root directory to the path so we can import our modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shared_ui import validate_image_quality


class MockUploadedFile:
    """A helper class to simulate Streamlit's file_uploader object."""
    def __init__(self, image):
        # Save the PIL image to a bytes buffer
        self.img_byte_arr = io.BytesIO()
        image.save(self.img_byte_arr, format='JPEG')
        self.img_byte_arr = self.img_byte_arr.getvalue()
        
    def getvalue(self):
        return self.img_byte_arr


def test_empty_document_rejection():
    print("Running Equivalence Class test: EC-4 (Empty Document)...")
    
    # Create a completely blank white image
    blank_image = Image.new('RGB', (800, 600), color=(255, 255, 255))
    
    # Wrap it in our mock object to pretend it came from Streamlit
    mock_file = MockUploadedFile(blank_image)
    
    # Pass it to the validation function
    is_valid, error_msg = validate_image_quality(mock_file)
    
    print("\n--- FUNCTIONAL TEST RESULTS ---")
    print(f"Validation Result: {is_valid}")
    print(f"Returned Message: {error_msg}")
    
    # Check if the system correctly rejected the blank image
    if not is_valid and "blank" in error_msg.lower():
        print("✅ TEST PASSED: System successfully intercepted and rejected a blank document without crashing.")
    else:
        print("❌ TEST FAILED: System did not reject the blank document properly.")

if __name__ == "__main__":
    test_empty_document_rejection()