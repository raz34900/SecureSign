# SecureSign
<div align="center">
  
# ✍️ SecureSign
**Financial Signature Verification & Forgery Detection Portal**

[![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://www.python.org)
[![PyTorch](https://img.shields.io/badge/PyTorch-EE4C2C?logo=pytorch&logoColor=white)](https://pytorch.org/)
[![Streamlit](https://img.shields.io/badge/Streamlit-FF4B4B?logo=streamlit&logoColor=white)](https://streamlit.io/)
[![OpenCV](https://img.shields.io/badge/OpenCV-5C3EE8?logo=opencv&logoColor=white)](https://opencv.org/)

</div>

---

## 📖 About The Project
SecureSign is an advanced Siamese Convolutional Neural Network (CNN) system designed to detect signature forgery in financial institutions. The system provides an end-to-end pipeline, from active active-learning model training to a fully functional multi-role UI for immediate deployment.

This system was developed as a comprehensive academic capstone project by **Raz and Daniel**.

## ✨ Key Features
The portal is divided into three role-based workspaces:
*   🏢 **Business Panel:** Enables retail branches to verify customer signatures against the central bank database in real-time, providing an immediate Confidence Score.
*   🏦 **Bank Panel:** Allows bank tellers to enroll new customers, capture multiple anchor signatures safely, manage the database, and verify identities with a detailed visual breakdown.
*   ⚙️ **Admin Panel:** A dedicated ML-Ops environment displaying live analytics, model learning curves, ROC/Confusion matrices, and a manual testing ground with a continuous feedback loop (Active Learning).

---

## 🧠 Model Architecture & Pipeline
Our system utilizes a **Siamese Neural Network** with a custom contrastive loss function to calculate the Euclidean distance between signature embeddings. 

**Preprocessing Pipeline:**
Before inference, every signature undergoes a strict transformation pipeline using OpenCV:
1.  **Otsu Binarization:** Isolating ink from paper.
2.  **Morphological Line Removal:** Automatically detecting and erasing printed signature lines.
3.  **Deskewing & Cropping:** Aligning the signature and cropping out white margins.
4.  **Padding & Resizing:** Centering the image into a 224x224 tensor.

---

## 📊 Analytics & Performance
*(Replace the placeholder below with the actual Learning Curve graph)*

![Learning Curve](https://via.placeholder.com/800x300.png?text=Drag+and+drop+your+Learning+Curve+Image+Here)

*(Replace the placeholder below with the ROC and Confusion Matrix)*

![ROC Curve](https://via.placeholder.com/800x300.png?text=Drag+and+drop+your+ROC+Curve+Image+Here)

---

## 💻 System Interfaces

### The Bank / Admin Interface
*(Showcase the UI here)*

![System UI](https://via.placeholder.com/800x400.png?text=Drag+and+drop+a+screenshot+of+the+Bank+or+Admin+Panel+Here)

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
