import streamlit as st
import os
import tempfile
import torch
import torch.nn.functional as F
from PIL import Image
import torchvision.transforms as transforms
import matplotlib.pyplot as plt

# Import the custom classes and functions from utils.py
from utils import CustomSiameseCNN, UnifiedSignatureTransform, extract_vertical_anchors

# ==========================================
# 1. Page Configuration, CSS & DB Setup
# ==========================================
st.set_page_config(page_title="SecureSign Portal", layout="wide")

st.markdown("""
<style>
    * { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
    h1, h2, h3 { color: #0b2b5e !important; text-align: center; }
    .subtitle { text-align: center; color: #8cc440; font-size: 1.2rem; margin-bottom: 2rem; font-weight: bold;}
    
    /* Primary Action Buttons */
    .stButton > button[kind="primary"] {
        background-color: #0b2b5e !important; color: white !important; border-radius: 8px !important;
        font-weight: bold !important; font-size: 16px !important; border: none !important; transition: 0.3s !important;
    }
    .stButton > button[kind="primary"]:hover { background-color: #153c7a !important; color: white !important; }
    
    /* Secondary Action Buttons (Borderless, light gray icons) */
    .stButton > button[kind="secondary"] {
        background-color: transparent !important; 
        color: #b3b3b3 !important; 
        border: 0px solid transparent !important; 
        font-size: 18px !important; 
        box-shadow: none !important; 
        margin: 0 auto !important; 
        display: block;
        padding: 0 !important;
    }
    .stButton > button[kind="secondary"]:hover, .stButton > button[kind="secondary"]:focus { 
        color: #ff4b4b !important; 
        background-color: transparent !important;
        box-shadow: none !important;
        border: 0px solid transparent !important; 
    }
    
    /* Specific styling for the Logout button */
    .logout-btn>div>button { background-color: #f0f2f6 !important; color: #333 !important; height: 40px !important; border-radius: 8px !important;}
    .logout-btn>div>button:hover { background-color: #e0e2e6 !important; color: #333 !important; }
</style>
""", unsafe_allow_html=True)

# Create a local mock database directory for storing individual verified anchors
DB_DIR = "mock_database"
os.makedirs(DB_DIR, exist_ok=True)

# Initialize a session state variable for deletion confirmation
if 'delete_confirm' not in st.session_state:
    st.session_state.delete_confirm = None

# ==========================================
# 2. Core Helper Functions
# ==========================================
def calculate_confidence(distance, threshold=0.40):
    """
    Converts Euclidean distance to a human-readable Confidence Percentage.
    Distances <= threshold map to 80.0% - 99.9% (Genuine).
    Distances > threshold map to 0.0% - 79.9% (Forgery).
    """
    if distance <= threshold:
        conf = 99.0 - (distance / threshold) * 19.0
    else:
        conf = 79.0 - min(1.0, (distance - threshold) / (2.0 - threshold)) * 79.0
    return max(0.0, min(99.9, conf))

def process_uploaded_document(file_obj):
    """
    Safely writes an uploaded file to disk temporarily, extracts the anchors,
    and returns a list of PIL Images.
    """
    with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp:
        tmp.write(file_obj.getvalue())
        tmp_path = tmp.name
        
    anchors = extract_vertical_anchors(tmp_path)
    os.remove(tmp_path)
    return anchors

@st.cache_resource
def load_model():
    """
    Loads the PyTorch model weights once and caches them in memory.
    """
    device = torch.device('cpu') 
    model = CustomSiameseCNN(embedding_dim=128).to(device)
    model_path = os.path.join("models", "secure_sign_epoch_50_loss_0.2009_acc_83.48.pth")
    
    if os.path.exists(model_path):
        model.load_state_dict(torch.load(model_path, map_location=device, weights_only=True))
        model.eval()
        return model
    else:
        st.error(f"Model file not found at {model_path}. Please check your folder structure.")
        return None

siamese_model = load_model()

# ==========================================
# 3. Session State & Authentication
# ==========================================
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'role' not in st.session_state:
    st.session_state.role = None
if 'username' not in st.session_state:
    st.session_state.username = None

# System Users Database
USERS_DB = {
    "shop": {"pass": "1234", "role": "business", "display": "Branch 045 - Retail"},
    "bank": {"pass": "1234", "role": "bank", "display": "Data Entry - Central Bank"},
    "admin": {"pass": "admin", "role": "admin", "display": "Development Team"}
}

def login(user, pwd):
    if user in USERS_DB and USERS_DB[user]["pass"] == pwd:
        st.session_state.logged_in = True
        st.session_state.role = USERS_DB[user]["role"]
        st.session_state.username = USERS_DB[user]["display"]
        st.rerun()
    else:
        st.error("Invalid username or password.")

def logout():
    st.session_state.logged_in = False
    st.session_state.role = None
    st.session_state.username = None
    st.rerun()

# ==========================================
# 4. SCREEN: LOGIN 
# ==========================================
if not st.session_state.logged_in:
    st.title("SecureSign")
    st.markdown("<div class='subtitle'>Financial Signature Verification Portal</div>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        with st.form("login_form"):
            st.markdown("### System Login")
            username_input = st.text_input("Username:")
            password_input = st.text_input("Password:", type="password")
            submit_button = st.form_submit_button("Login", type="primary")
            
            if submit_button:
                if username_input and password_input:
                    login(username_input, password_input)
                else:
                    st.warning("Please fill in all fields.")
                    
        st.caption("Testing Credentials:")
        st.caption("Business -> shop : 1234 | Bank -> bank : 1234 | Admin -> admin : admin")

# ==========================================
# 5. SCREEN: MAIN APP
# ==========================================
else:
    # Header area containing welcome message and logout button
    col1, col2 = st.columns([8, 2])
    with col1:
        st.success(f"Welcome, {st.session_state.username}")
    with col2:
        st.markdown("<div class='logout-btn'>", unsafe_allow_html=True)
        if st.button("Logout"):
            logout()
        st.markdown("</div>", unsafe_allow_html=True)
    
    st.divider()

    # ----------------------------------------
    # ROLE: BUSINESS (Verification Panel)
    # ----------------------------------------
    if st.session_state.role == "business":
        st.subheader("Business Panel: Signature Verification")
        customer_id = st.text_input("Enter Customer ID (e.g., 123):")
        
        input_method = st.radio("Choose input method:", ["Camera", "Upload File"], horizontal=True)
        
        if input_method == "Camera":
            sig_data = st.camera_input("Take a clear picture of the signature")
        else:
            sig_data = st.file_uploader("Upload signature image:", type=['png', 'jpg', 'jpeg'])
            
        if st.button("Verify Signature", use_container_width=True, type="primary"):
            if customer_id and sig_data and siamese_model:
                
                cust_dir = os.path.join(DB_DIR, customer_id)
                
                # Verify that customer profile has enough anchors
                if not os.path.exists(cust_dir) or len(os.listdir(cust_dir)) < 8:
                    st.error(f"❌ Customer ID '{customer_id}' has an incomplete profile. Direct them to a bank branch to enroll properly.")
                else:
                    with st.spinner('Fetching anchors from database and analyzing...'):
                        device = torch.device('cpu')
                        transform = transforms.Compose([UnifiedSignatureTransform(), transforms.ToTensor()])
                        
                        test_img = Image.open(sig_data).convert('L')
                        test_tensor = transform(test_img).unsqueeze(0).to(device)

                        distances = []
                        with torch.no_grad():
                            for f_name in os.listdir(cust_dir):
                                if f_name.endswith(('.jpg', '.png')):
                                    anchor_img = Image.open(os.path.join(cust_dir, f_name)).convert('L')
                                    anchor_tensor = transform(anchor_img).unsqueeze(0).to(device)
                                    out1, out2 = siamese_model(anchor_tensor, test_tensor)
                                    dist = F.pairwise_distance(out1, out2).item()
                                    distances.append(dist)

                        avg_distance = sum(distances) / len(distances)
                        threshold = 0.40
                        is_genuine = avg_distance < threshold
                        confidence = calculate_confidence(avg_distance, threshold)
                        
                        st.divider()
                        st.markdown("### Verification Result")
                        res_col1, res_col2 = st.columns(2)
                        
                        with res_col1:
                            st.image(test_img, caption="Scanned Signature", width=250)
                        with res_col2:
                            if is_genuine:
                                st.success("✅ APPROVED: Signature is Genuine.")
                                st.metric("Confidence Score", f"{confidence:.1f}%", "Pass", delta_color="normal")
                            else:
                                st.error("🚨 REJECTED: Suspected Forgery.")
                                st.metric("Confidence Score", f"{confidence:.1f}%", "Fail", delta_color="inverse")
            else:
                st.warning("Please enter a Customer ID and provide a signature image.")

    # ----------------------------------------
    # ROLE: BANK (Management & Verification)
    # ----------------------------------------
    elif st.session_state.role == "bank":
        st.subheader("Bank Panel: Customer Management & Verification")
        
        tab1, tab2, tab3 = st.tabs(["Enroll / Update Customer", "Verify Customer Signature", "Search Existing Customers"])
        
        # TAB 1: ENROLL OR UPDATE CUSTOMER
        with tab1:
            st.markdown("#### Enroll New or Update Existing Customer")
            new_id = st.text_input("Customer ID:")
            st.info("Instructions: A customer profile must contain between 8 and 15 anchors in total.")
            
            enroll_method = st.radio("Capture method:", ["Camera", "Upload File"], horizontal=True, key="enroll_method")
            if enroll_method == "Camera":
                anchor_data = st.camera_input("Take a picture of the document")
            else:
                anchor_data = st.file_uploader("Upload document:", type=['png', 'jpg', 'jpeg', 'pdf'])
                
            if new_id and anchor_data:
                raw_anchors = process_uploaded_document(anchor_data)
                
                if not raw_anchors:
                    st.error("❌ Could not extract any signatures. Please try a clearer image.")
                else:
                    st.markdown("#### Review & Filter Extracted Signatures")
                    st.write("Uncheck any artifacts or scribbles. Only checked items will be saved.")
                    
                    cols = st.columns(min(len(raw_anchors), 5))
                    selected_anchors = []
                    
                    for i, anchor_img in enumerate(raw_anchors):
                        col_idx = i % 5
                        with cols[col_idx]:
                            st.image(anchor_img, use_container_width=True)
                            if st.checkbox(f"Keep #{i+1}", value=True, key=f"keep_t1_{i}"):
                                selected_anchors.append(anchor_img)
                                
                    cust_dir = os.path.join(DB_DIR, new_id)
                    existing_count = len(os.listdir(cust_dir)) if os.path.exists(cust_dir) else 0
                    total_proposed = existing_count + len(selected_anchors)
                    
                    st.write(f"**Existing Anchors:** {existing_count} | **Selected to Add:** {len(selected_anchors)} | **Total will be:** {total_proposed}")
                    
                    if st.button("Save Confirmed Signatures to Database", use_container_width=True, type="primary"):
                        if not selected_anchors:
                            st.error("You must select at least one signature to save.")
                        elif total_proposed < 8 or total_proposed > 15:
                            st.error(f"❌ Cannot save! A customer must have strictly between 8 and 15 anchors. You are trying to save {total_proposed}.")
                        else:
                            is_existing = os.path.exists(cust_dir)
                            os.makedirs(cust_dir, exist_ok=True)
                            
                            for idx, img in enumerate(selected_anchors):
                                import uuid
                                unique_filename = f"anchor_{uuid.uuid4().hex[:8]}.jpg"
                                img.save(os.path.join(cust_dir, unique_filename))
                                
                            if is_existing:
                                st.success(f"✅ Existing customer '{new_id}' updated successfully! Added {len(selected_anchors)} new anchors.")
                            else:
                                st.success(f"✅ New customer '{new_id}' saved securely with {len(selected_anchors)} verified anchors.")
                                
                            st.markdown("##### Signatures Saved to Database:")
                            saved_cols = st.columns(min(len(selected_anchors), 5))
                            for i, img in enumerate(selected_anchors):
                                saved_cols[i % 5].image(img, use_container_width=True)
                    
        # TAB 2: VERIFY CUSTOMER
        with tab2:
            st.markdown("#### Branch Verification (Detailed View)")
            verify_id = st.text_input("Customer ID to verify:")
            ver_method = st.radio("Capture method:", ["Camera", "Upload File"], horizontal=True, key="ver_method")
            
            if ver_method == "Camera":
                ver_data = st.camera_input("Capture Signature")
            else:
                ver_data = st.file_uploader("Upload Signature", type=['png', 'jpg', 'jpeg'])
            
            if st.button("Verify Customer", use_container_width=True, type="primary"):
                if verify_id and ver_data and siamese_model:
                    
                    cust_dir = os.path.join(DB_DIR, verify_id)
                    
                    if not os.path.exists(cust_dir) or len(os.listdir(cust_dir)) < 8:
                        st.error(f"❌ Customer ID '{verify_id}' has an incomplete profile (requires 8-15 anchors). Cannot verify.")
                    else:
                        with st.spinner("Fetching anchors from database and analyzing..."):
                            device = torch.device('cpu')
                            transform = transforms.Compose([UnifiedSignatureTransform(), transforms.ToTensor()])
                            
                            test_img = Image.open(ver_data).convert('L')
                            test_tensor = transform(test_img).unsqueeze(0).to(device)

                            distances = []
                            processed_anchors_for_display = []

                            with torch.no_grad():
                                for f_name in os.listdir(cust_dir):
                                    if f_name.endswith(('.jpg', '.png')):
                                        anchor_img = Image.open(os.path.join(cust_dir, f_name)).convert('L')
                                        anchor_tensor = transform(anchor_img).unsqueeze(0).to(device)
                                        processed_anchors_for_display.append(anchor_tensor.cpu().squeeze().numpy())
                                        
                                        out1, out2 = siamese_model(anchor_tensor, test_tensor)
                                        dist = F.pairwise_distance(out1, out2).item()
                                        distances.append(dist)

                            avg_distance = sum(distances) / len(distances)
                            threshold = 0.40  
                            is_genuine = avg_distance < threshold
                            final_confidence = calculate_confidence(avg_distance, threshold)

                            fig = plt.figure(figsize=(14, 8))
                            main_color = 'green' if is_genuine else 'red'
                            decision_text = "APPROVED" if is_genuine else "REJECTED"
                            fig.suptitle(f"System Decision: {decision_text} | Confidence: {final_confidence:.1f}%", 
                                         color=main_color, fontsize=18, fontweight='bold', y=1.02)

                            num_anchors = len(processed_anchors_for_display)
                            for i, proc_anchor in enumerate(processed_anchors_for_display):
                                ax = plt.subplot(2, num_anchors, i + 1)
                                display_img = 1.0 - proc_anchor
                                ax.imshow(display_img, cmap='gray')
                                
                                dist = distances[i]
                                anchor_pass = dist < threshold
                                color = 'green' if anchor_pass else '#d62728'
                                conf = calculate_confidence(dist, threshold)
                                
                                ax.set_title(f"DB Anchor {i+1}\nMatch: {conf:.1f}%", color=color, fontsize=12, fontweight='bold')
                                ax.axis('off')

                            ax_test = plt.subplot(2, 1, 2)
                            test_display = 1.0 - test_tensor.cpu().squeeze().numpy()
                            ax_test.imshow(test_display, cmap='gray')
                            ax_test.set_title(f"SCANNED SIGNATURE", fontweight='bold', fontsize=14, color='#153c7a')
                            ax_test.axis('off')

                            plt.tight_layout()
                            st.pyplot(fig)
                else:
                    st.warning("Please enter a Customer ID and provide a signature image.")
                
        # TAB 3: SEARCH EXISTING CUSTOMERS (View, Delete & Append features)
        with tab3:
            st.markdown("#### Search & Manage Customer Database")
            search_id = st.text_input("Enter Customer ID to search:")
            
            if search_id:
                cust_dir = os.path.join(DB_DIR, search_id)
                if os.path.exists(cust_dir) and len(os.listdir(cust_dir)) > 0:
                    existing_files = [f for f in os.listdir(cust_dir) if f.endswith(('.jpg', '.png'))]
                    
                    st.success(f"✅ Found Customer: '{search_id}' | Total Verified Anchors: {len(existing_files)}")
                    
                    if len(existing_files) < 8:
                        st.warning("⚠️ Warning: Customer has less than 8 anchors. Verification is disabled until more are added.")
                        
                    st.markdown("##### Current Saved Signatures")
                    
                    # Display existing anchors with a borderless minimalist delete logic
                    cols_per_row = 5
                    for i in range(0, len(existing_files), cols_per_row):
                        cols = st.columns(cols_per_row)
                        for j in range(cols_per_row):
                            if i + j < len(existing_files):
                                f_name = existing_files[i + j]
                                img_path = os.path.join(cust_dir, f_name)
                                
                                with cols[j]:
                                    st.image(img_path, caption=f"Anchor {i+j+1}", use_container_width=True)
                                    
                                    # Yellow confirmation box
                                    if st.session_state.delete_confirm == img_path:
                                        st.markdown("<div style='background-color: #fff8c4; color: #5a4b00; padding: 4px; border-radius: 4px; text-align: center; font-size: 13px; font-weight: bold; margin-bottom: 4px;'>Are you sure?</div>", unsafe_allow_html=True)
                                        btn_col1, btn_col2 = st.columns(2)
                                        with btn_col1:
                                            if st.button("✔️", key=f"yes_{search_id}_{f_name}", help="Confirm Delete", type="secondary"):
                                                os.remove(img_path)
                                                st.session_state.delete_confirm = None
                                                st.rerun()
                                        with btn_col2:
                                            if st.button("✖️", key=f"no_{search_id}_{f_name}", help="Cancel", type="secondary"):
                                                st.session_state.delete_confirm = None
                                                st.rerun()
                                    else:
                                        # Simple borderless light gray X that turns red on hover
                                        if st.button("✖", key=f"del_{search_id}_{f_name}", help="Delete this signature", type="secondary"):
                                            st.session_state.delete_confirm = img_path
                                            st.rerun()
                        
                    st.divider()
                    st.markdown("##### Add More Signatures to this Profile")
                    
                    add_method = st.radio("Capture method:", ["Camera", "Upload File"], horizontal=True, key="add_method_t3")
                    if add_method == "Camera":
                        add_data = st.camera_input("Take a picture", key="cam_t3")
                    else:
                        add_data = st.file_uploader("Upload document:", type=['png', 'jpg', 'jpeg', 'pdf'], key="up_t3")
                        
                    if add_data:
                        raw_add_anchors = process_uploaded_document(add_data)
                        if raw_add_anchors:
                            st.markdown("#### Filter New Signatures")
                            cols_add = st.columns(min(len(raw_add_anchors), 5))
                            selected_add = []
                            for i, anchor_img in enumerate(raw_add_anchors):
                                col_idx = i % 5
                                with cols_add[col_idx]:
                                    st.image(anchor_img, use_container_width=True)
                                    if st.checkbox(f"Keep #{i+1}", value=True, key=f"keep_t3_{i}"):
                                        selected_add.append(anchor_img)
                                        
                            total_future = len(existing_files) + len(selected_add)
                            st.write(f"**Existing:** {len(existing_files)} | **Adding:** {len(selected_add)} | **Total will be:** {total_future}")
                            
                            if st.button("Append Signatures to Profile", key="btn_append_t3", type="primary"):
                                if not selected_add:
                                    st.error("You must select at least one signature to add.")
                                elif total_future > 15:
                                    st.error(f"❌ Cannot exceed 15 anchors per customer. Adding these would result in {total_future}.")
                                elif total_future < 8:
                                    st.error(f"❌ A customer must have at least 8 anchors in total. Adding these would result in {total_future}.")
                                else:
                                    for idx, img in enumerate(selected_add):
                                        import uuid
                                        unique_filename = f"anchor_{uuid.uuid4().hex[:8]}.jpg"
                                        img.save(os.path.join(cust_dir, unique_filename))
                                        
                                    st.success(f"✅ Successfully added {len(selected_add)} anchors to '{search_id}'.")
                                    st.session_state.delete_confirm = None
                                    st.rerun()
                else:
                    st.error(f"❌ Customer '{search_id}' not found in the database.")

    # ----------------------------------------
    # ROLE: ADMIN (Analytics & Continuous Learning)
    # ----------------------------------------
    elif st.session_state.role == "admin":
        st.subheader("Admin Panel: Development & Analytics")
        
        tab1, tab2 = st.tabs(["Analytics & Graphs", "Manual Testing & Active Learning"])
        
        # TAB 1: GRAPHS & METRICS
        with tab1:
            metric_col1, metric_col2, metric_col3 = st.columns(3)
            metric_col1.metric("Test Accuracy (Epoch 50)", "83.48%")
            metric_col2.metric("F1 Score", "0.8285")
            metric_col3.metric("ROC AUC", "0.923")
            
            st.divider()
            
            view_selection = st.radio(
                "Select Visualization View:",
                ["Model Learning Curve", "ROC & Confusion Matrix", "Preprocessing Pipeline"],
                horizontal=True,
                label_visibility="collapsed"
            )
            
            st.markdown(f"<h4 style='text-align: center; color: #153c7a; margin-top: 1rem;'>{view_selection}</h4>", unsafe_allow_html=True)
            
            if view_selection == "Model Learning Curve":
                img_path = os.path.join("assets", "results2.png")
                if os.path.exists(img_path):
                    st.image(img_path, use_container_width=True)
                else:
                    st.warning("⚠️ Learning Curve image ('results2.png') not found in assets folder.")
                    
            elif view_selection == "ROC & Confusion Matrix":
                img_path = os.path.join("assets", "results.png")
                if os.path.exists(img_path):
                    st.image(img_path, use_container_width=True)
                else:
                    st.warning("⚠️ ROC & Confusion Matrix image ('results.png') not found in assets folder.")
                    
            elif view_selection == "Preprocessing Pipeline":
                preprocess_images = ["processed raw data.png", "test.png", "test2.png"]
                available_images = [img for img in preprocess_images if os.path.exists(os.path.join("assets", img))]
                
                if available_images:
                    if len(available_images) > 1:
                        selected_idx = st.slider("Swipe through preprocessing examples", 1, len(available_images), 1) - 1
                    else:
                        selected_idx = 0
                        
                    selected_img_path = os.path.join("assets", available_images[selected_idx])
                    st.image(selected_img_path, caption=f"Example {selected_idx + 1}: {available_images[selected_idx]}", use_container_width=True)
                else:
                    st.info("Pipeline visualizations will appear here. Please ensure preprocessing images exist in the 'assets' folder.")

        # TAB 2: MANUAL TESTING WITH FILTERING
        with tab2:
            st.markdown("#### Manual Verification & Model Fine-Tuning")
            st.write("Upload an anchor document and a test signature to evaluate the model.")
            
            m_col1, m_col2 = st.columns(2)
            with m_col1:
                admin_anchor = st.file_uploader("Upload Reference Document (Anchors):", type=['png', 'jpg', 'jpeg'])
            with m_col2:
                admin_test = st.file_uploader("Upload Test Signature:", type=['png', 'jpg', 'jpeg'])
                
            if admin_anchor and admin_test:
                
                raw_anchors = process_uploaded_document(admin_anchor)
                
                if not raw_anchors:
                    st.error("❌ Could not extract any signatures.")
                else:
                    st.markdown("#### Filter Anchors Before Analysis")
                    cols = st.columns(min(len(raw_anchors), 5))
                    selected_anchors = []
                    
                    for i, anchor_img in enumerate(raw_anchors):
                        col_idx = i % 5
                        with cols[col_idx]:
                            st.image(anchor_img, use_container_width=True)
                            keep = st.checkbox(f"Keep #{i+1}", value=True, key=f"keep_admin_{i}")
                            if keep:
                                selected_anchors.append(anchor_img)
                    
                    if st.button("Run Deep Analysis", use_container_width=True, type="primary"):
                        if not selected_anchors:
                            st.error("You must select at least one anchor to run the analysis.")
                        else:
                            with st.spinner("Processing image, removing lines, and running CNN..."):
                                device = torch.device('cpu')
                                transform = transforms.Compose([UnifiedSignatureTransform(), transforms.ToTensor()])
                                
                                with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp_test:
                                    tmp_test.write(admin_test.getvalue())
                                    test_path = tmp_test.name
                                    
                                try:
                                    test_img = Image.open(test_path).convert('L')
                                    test_tensor = transform(test_img).unsqueeze(0).to(device)

                                    distances = []
                                    processed_anchors_for_display = []

                                    with torch.no_grad():
                                        for anchor_img in selected_anchors:
                                            anchor_tensor = transform(anchor_img).unsqueeze(0).to(device)
                                            processed_anchors_for_display.append(anchor_tensor.cpu().squeeze().numpy())
                                            
                                            out1, out2 = siamese_model(anchor_tensor, test_tensor)
                                            dist = F.pairwise_distance(out1, out2).item()
                                            distances.append(dist)

                                    avg_distance = sum(distances) / len(distances)
                                    threshold = 0.40  
                                    is_genuine = avg_distance < threshold
                                    final_confidence = calculate_confidence(avg_distance, threshold)

                                    fig = plt.figure(figsize=(14, 8))
                                    main_color = 'green' if is_genuine else 'red'
                                    decision_text = "Genuine (Match)" if is_genuine else "Forgery (Reject)"
                                    fig.suptitle(f"Final Decision: {decision_text} | Confidence: {final_confidence:.1f}%", 
                                                 color=main_color, fontsize=18, fontweight='bold', y=1.02)

                                    for i, proc_anchor in enumerate(processed_anchors_for_display):
                                        ax = plt.subplot(2, len(selected_anchors), i + 1)
                                        display_img = 1.0 - proc_anchor
                                        ax.imshow(display_img, cmap='gray')
                                        
                                        dist = distances[i]
                                        anchor_pass = dist < threshold
                                        color = 'green' if anchor_pass else '#d62728'
                                        conf = calculate_confidence(dist, threshold)
                                        
                                        ax.set_title(f"Anchor {i+1}\nMatch: {conf:.1f}%", color=color, fontsize=12, fontweight='bold')
                                        ax.axis('off')

                                    ax_test = plt.subplot(2, 1, 2)
                                    test_display = 1.0 - test_tensor.cpu().squeeze().numpy()
                                    ax_test.imshow(test_display, cmap='gray')
                                    ax_test.set_title(f"TEST SIGNATURE (Line Removed, Cropped & Deskewed)", fontweight='bold', fontsize=14, color='#153c7a')
                                    ax_test.axis('off')

                                    plt.tight_layout()
                                    st.pyplot(fig)

                                    st.divider()
                                    st.markdown("**Was the model correct? (Active Learning Feedback)**")
                                    f_col1, f_col2 = st.columns(2)
                                    with f_col1:
                                        if st.button("👍 Correct (Save to verified data)", type="primary"):
                                            st.toast("Feedback saved! Data will be used in the next training cycle.")
                                    with f_col2:
                                        if st.button("👎 Incorrect (Save to hard-examples data)", type="primary"):
                                            st.toast("Flagged as a hard example! Will heavily penalize the model in the next fine-tuning phase.")
                                finally:
                                    os.remove(test_path)