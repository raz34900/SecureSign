<div align="center">
  
# SecureSign
<img width="533" height="666" alt="gemini-svg (3)" src="https://github.com/user-attachments/assets/ab83738e-9523-471c-bf9e-bc2fcff46d69" />


**Financial Signature Verification & Forgery Detection Portal**

[![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://www.python.org)
[![PyTorch](https://img.shields.io/badge/PyTorch-EE4C2C?logo=pytorch&logoColor=white)](https://pytorch.org/)
[![Streamlit](https://img.shields.io/badge/Streamlit-FF4B4B?logo=streamlit&logoColor=white)](https://streamlit.io/)
[![OpenCV](https://img.shields.io/badge/OpenCV-5C3EE8?logo=opencv&logoColor=white)](https://opencv.org/)

</div>

---

## About The Project
SecureSign is an advanced Siamese Convolutional Neural Network (CNN) system designed to detect signature forgery in financial institutions. The system provides an end-to-end pipeline, from active-learning model training to a fully functional multi-role UI for immediate deployment.

This system was developed as a comprehensive academic capstone project by **Raz and Daniel**.

## Key Features
The portal is divided into three role-based workspaces:
*   **Business Panel:** Enables retail branches to verify customer signatures against the central bank database in real-time, providing an immediate Confidence Score.
*   **Bank Panel:** Allows bank tellers to enroll new customers, capture multiple anchor signatures safely, manage the database, and verify identities with a detailed visual breakdown.
*   **Admin Panel:** A dedicated ML-Ops environment displaying live analytics, model learning curves, ROC/Confusion matrices, and a manual testing ground with a continuous feedback loop (Active Learning).

---

## Preprocessing Pipeline in Action
Before inference, every signature undergoes a strict transformation pipeline using OpenCV to isolate the ink, remove printed lines, and align the signature perfectly:

<img width="1591" height="1635" alt="הורדה (2)" src="https://github.com/user-attachments/assets/e9d14f05-90e3-4ea3-9b67-5d32d5216b94" />

---

## Model Architecture
Our system utilizes a **Siamese Neural Network** with a custom contrastive loss function to calculate the Euclidean distance between signature embeddings. 

1.  **Otsu Binarization:** Isolating ink from paper.
2.  **Morphological Line Removal:** Automatically detecting and erasing printed signature lines.
3.  **Deskewing & Cropping:** Aligning the signature and cropping out white margins.
4.  **Padding & Resizing:** Centering the image into a 224x224 tensor.

---


## Smart Anchor Extraction
Our system effortlessly handles bulk enrollments. By uploading a single scanned document containing multiple signatures, the application automatically detects, crops, and extracts each signature into individual verified anchors for the customer's database profile.

<img width="713" height="2048" alt="מאגר" src="https://github.com/user-attachments/assets/aa2029f1-f293-4b26-8444-e82c1533bf7a" />

---

## Verification Results
The core of SecureSign is providing explainable, clear results for bank tellers and business branches. The system compares a scanned test signature against all saved database anchors, calculating a final Confidence Score.

<img width="1460" height="862" alt="da7d4c3d0526703b614aac8e320ffeac" src="https://github.com/user-attachments/assets/8b796884-dbda-49b1-80d5-8eca2611f4ee" />

<img width="1460" height="862" alt="48caaf69ac30a4ee0f0c3c8721a66b92" src="https://github.com/user-attachments/assets/2f3c208a-71fe-42af-a50a-040ace2aee40" />


---

## 📊 Analytics & Performance

### Model Learning Curve

<img width="1189" height="590" alt="הורדה" src="https://github.com/user-attachments/assets/d5ffe563-a3b7-4590-b853-329a834fd9a1" />

### ROC and Confusion Matrix

<img width="1589" height="690" alt="הורדה (1)" src="https://github.com/user-attachments/assets/1ba39fcb-2c32-425f-a005-cee6c03ff7ad" />

---

## System Interfaces

### The Bank & Admin Dashboards

#################################################UPLOAD PHOTO################################################
---

## 🚀 How to Run Locally

1. Clone this repository:
    ```bash
    git clone [https://github.com/raz34900/SecureSign.git](https://github.com/raz34900/SecureSign.git)
    ```
2. Install the required dependencies:
    ```bash
    pip install torch torchvision streamlit opencv-python Pillow matplotlib
    ```
3. Run the Streamlit application:
    ```bash
    streamlit run app.py
    ```
