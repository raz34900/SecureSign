<table>
  <tr>
    <td align="center">
      <img width="156" height="217" alt="לוגו" src="https://github.com/user-attachments/assets/00859042-a9fc-42f6-b428-87800a5d9878" />
    </td>
    <td valign="center">
      <h1>SecureSign</h1>
      <h3>Financial Signature Verification & Forgery Detection Portal</h3>
    </td>
  </tr>
</table>

<br>


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

## Datasets & Distribution

ChiSig - A Chinese document signature forgery detection benchmark containing 10,242 images across 500 distinct signed names.
https://github.com/dskezju/ChiSig 

BHSig260 - Comprising 260 signers, the dataset includes 14,040 signature images.
https://github.com/DefUs3r/Automatic-Signature-Verification/tree/master

CEDAR -  widely recognized benchmark collection in offline signature verification, containing verified genuine signatures and skilled forgeries. 
https://www.kaggle.com/datasets/shreelakshmigp/cedardataset

manually collected - In addition to the standard datasets, we manually collected and added signatures from 55 new authors to further diversify and strengthen our database.

The project combines three different signature datasets to create a unified, rich master dataset featuring English, Hindi, Bengali, Hebrew and Chinese signatures.

### Master Dataset Statistics
| Source | Authors | Total Images |
| :--- | :---: | :---: |
| **English (Original)** | 109 | 3,356 |
| **BHSig260 (Hindi/Bengali)** | 260 | 14,016 |
| **ChiSig (Chinese)** | 500 | 3,989 |
| **Total** | **869** | **21,361** |

### Siamese Pairs (Train / Val / Test)
To train the Siamese Network, the data was strictly isolated (to prevent data leakage) and paired:
| Split | Number of Pairs |
| :--- | :---: |
| **Train** | 53,614 |
| **Validation** | 12,741 |
| **Test** | 12,612 |

**Total Pairs:** 78,967 (comprising 157,934 individual images).

---

## Model Architecture Comparison

To determine the most robust approach for offline signature verification, we conducted a direct comparative analysis between two architectures:

### 1. Baseline: Pre-trained ResNet18
*   Adapted to accept 1-channel (grayscale) images.
*   Output embedding dimension: 128 (with 0.5 Dropout).
*   **Limitation:** The significant depth (millions of parameters) caused severe **overfitting**. The model memorized the binary images, driving training loss to near zero while validation loss stagnated early.

### 2. Proposed Model: Custom Lightweight CNN
*   A tailored architecture consisting of 4 sequential blocks (Conv2d, BatchNorm, ReLU, MaxPool).
*   Final layers use a higher Dropout of 0.6 for enhanced regularization.
*   **Advantage:** The reduced parameter count forced the network to learn structural and stylistic features rather than memorizing samples. This eliminated overfitting and drastically improved generalization on unseen data.

---

## Preprocessing Pipeline in Action
Before inference, every signature undergoes a strict transformation pipeline using OpenCV to isolate the ink, remove printed lines, and align the signature perfectly:

<img width="794" height="816" alt="הורדה (2)" src="https://github.com/user-attachments/assets/e9d14f05-90e3-4ea3-9b67-5d32d5216b94" />

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

<img width="259" height="500" alt="מאגר" src="https://github.com/user-attachments/assets/aa2029f1-f293-4b26-8444-e82c1533bf7a" />

---

## Verification Results
The core of SecureSign is providing explainable, clear results for bank tellers and business branches. The system compares a scanned test signature against all saved database anchors, calculating a final Confidence Score.

<img width="730" height="430" alt="da7d4c3d0526703b614aac8e320ffeac" src="https://github.com/user-attachments/assets/8b796884-dbda-49b1-80d5-8eca2611f4ee" />


<img width="730" height="430" alt="48caaf69ac30a4ee0f0c3c8721a66b92" src="https://github.com/user-attachments/assets/2f3c208a-71fe-42af-a50a-040ace2aee40" />

---

## Analytics & Performance

### Model Learning Curve

<img width="594" height="294" alt="הורדה" src="https://github.com/user-attachments/assets/d5ffe563-a3b7-4590-b853-329a834fd9a1" />

### ROC and Confusion Matrix

<img width="794" height="344" alt="הורדה (1)" src="https://github.com/user-attachments/assets/1ba39fcb-2c32-425f-a005-cee6c03ff7ad" />

---


## Final Test Set Results

After training both models using an identical optimized loop (Automatic Mixed Precision + Online Hard Example Mining Contrastive Loss), the optimal threshold was determined using the ROC curve on a completely unseen test set.

| Metric | ResNet18 (Baseline) | Custom CNN (Selected) |
| :--- | :---: | :---: |
| **Optimal Threshold** | 0.4042 | **0.3999** |
| **Accuracy** | 81.22% | **84.32%** |
| **F1-Score** | 0.8157 | **0.8404** |
| **ROC AUC** | 0.8983 | **0.9231** |

### Conclusion
The **Custom Lightweight CNN** was selected as the final production model. It successfully balances high verification accuracy (84.32%), excellent generalization without overfitting, and fast computational efficiency, making it highly reliable for real-time bank verification.

---

## System Interfaces

### The Bank & Admin & Business Dashboards

<img width="446" height="358" alt="WhatsApp Image 2026-08-05 at 21 43 53" src="https://github.com/user-attachments/assets/63c91bf8-da70-417d-b59b-b564c9c0c035" />

<img width="339" height="315" alt="WhatsApp Image 2026-08-05 at 21 49 16" src="https://github.com/user-attachments/assets/0e23a26a-b1fa-4ffd-a5f6-12e4116d24a7" />

<img width="357" height="360" alt="WhatsApp Image 2026-08-05 at 22 02 05" src="https://github.com/user-attachments/assets/9f30c3f7-1d76-47c3-b464-01e7c5d6a05d" />



---

## Key Algorithms & Code Snippets

This section highlights the core algorithms, formulas, and logic driving the verification portal.

### 1. Unified Signature Preprocessing Pipeline
**[🔗 View Implementation in `utils.py`](./utils.py#L10-L60)**

**Role & Importance:** 
Raw signatures come with immense background noise, varying angles, and printed document lines. This pipeline is the system's "secret sauce" for standardizing data. It sequentially applies Inverse Otsu Binarization (isolating ink), morphological line removal (erasing horizontal artifacts), and moment-based deskewing. This ensures the CNN focuses strictly on biometric traits rather than paper quality.

### 2. Smart Anchor Extraction (Contour Detection)
**[🔗 View Implementation in `utils.py`](./utils.py#L65-L108)**

**Role & Importance:** 
A critical feature for bank tellers handling bulk enrollments. Using OpenCV's `findContours` and morphological closing, this algorithm automatically detects, groups, and crops multiple signatures written vertically on a single physical document, streamlining the database population process.

### 3. Custom Lightweight Siamese CNN
**[🔗 View Implementation in `utils.py`](./utils.py#L113-L160)**

**Role & Importance:** 
Our custom 4-block Convolutional Neural Network. Unlike deep pre-trained models (e.g., ResNet18) that severely overfit on simple binary images, this lightweight architecture is perfectly balanced. It enforces strict regularization (Dropout 0.6) to learn generalizable stylistic features rather than memorizing the training set.

### 4. Distance Calculation & Verification Logic
**[🔗 View Implementation in `app.py`](./app.py#L171-L178)**

**Role & Importance:** 
The core decision engine. Once the CNN extracts 128-dimensional embedding vectors for both the reference anchor ($x$) and the tested signature ($y$), the system calculates the Euclidean distance between them:

**Formula:** 
$d(x, y) = \sqrt{\sum_{i=1}^{128} (f(x)_i - f(y)_i)^2}$

If the average distance across all saved anchors is below our optimal threshold (**0.3999**), the signature is classified as genuine.

### 5. Confidence Score Mapping
**[🔗 View Implementation in `app.py`](./app.py#L42-L50)**

**Role & Importance:** 
Raw Euclidean distances are unintuitive for end-users (bank tellers). This mathematical function maps the unbounded distance into a user-friendly percentage (0% - 99.9%), clearly indicating the system's confidence level in its APPROVED/REJECTED decision.

### 6. Master Dataset Builder & Unification
**[🔗 View in Jupyter Notebook](./SecureSign.ipynb#master-dataset-builder-all-languages)**

**Role & Importance:** 
To train a robust model, we needed massive diversity. This section of our research notebook contains the complex pipeline that merges three distinct databases (CEDAR, BHSig260, and ChiSig). It dynamically parses complex naming conventions across languages, maps authors to unique IDs to prevent data leakage, and standardizes everything into a unified training structure.

### 7. Advanced Training Loop (AMP & Hard Example Mining)
**[🔗 View in Jupyter Notebook](./SecureSign.ipynb#advanced-training-loop-with-learning-rate-scheduler-cnn)**

**Role & Importance:** 
The core training engine of our system. To optimize training, we implemented **Automatic Mixed Precision (AMP)** using PyTorch's `GradScaler`, which drastically reduced VRAM usage and accelerated training. Furthermore, the loop utilizes an **Online Hard Example Mining (OHEM) Contrastive Loss**, dynamically forcing the network to penalize the hardest forgery examples in each batch rather than wasting computational power on easy, obvious pairs.

### 8. Final Test Evaluation & Metrics Dashboard
**[🔗 View in Jupyter Notebook](./SecureSign.ipynb#final-test-set-evaluation--metrics-dashboard)**

**Role & Importance:** 
Our robust evaluation script. It runs the trained model on tens of thousands of completely unseen pairs. It automatically calculates the Youden's J statistic from the ROC curve to find the optimal dynamic threshold, and generates a comprehensive Admin Dashboard featuring a Seaborn Confusion Matrix and the final Area Under the Curve (AUC) performance.

---

## How to Run Locally

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
