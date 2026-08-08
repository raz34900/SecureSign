import streamlit as st
import os
import torch
from utils import CustomSiameseCNN
from shared_ui import inject_css

# --- Import views ---
from views.admin_view import show_admin_panel
from views.business_view import show_business_panel 
from views.bank_view import show_bank_panel

st.set_page_config(page_title="SecureSign Portal", layout="wide")
inject_css()

DB_DIR = "mock_database"
os.makedirs(DB_DIR, exist_ok=True)

@st.cache_resource
def load_model():
    device = torch.device('cpu') 
    model = CustomSiameseCNN(embedding_dim=128).to(device)
    models_dir = "models"
    if os.path.exists(models_dir):
        pth_files = [f for f in os.listdir(models_dir) if f.endswith('.pth')]
        if pth_files:
            model_path = os.path.join(models_dir, pth_files[0])
            model.load_state_dict(torch.load(model_path, map_location=device, weights_only=True))
            model.eval()
            return model
    st.error("No .pth model file found in the 'models' folder.")
    return None

siamese_model = load_model()

# --- Auth State & Fix for delete_confirm ---
if 'logged_in' not in st.session_state: st.session_state.logged_in = False
if 'role' not in st.session_state: st.session_state.role = None
if 'username' not in st.session_state: st.session_state.username = None
if 'delete_confirm' not in st.session_state: st.session_state.delete_confirm = None

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
    else: st.error("Invalid username or password.")

def logout():
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()

# --- ROUTER ---
if not st.session_state.logged_in:
    st.title("SecureSign")
    st.markdown("<div class='subtitle'>Financial Signature Verification Portal</div>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        with st.form("login_form"):
            st.markdown("### System Login")
            user_in = st.text_input("Username:")
            pass_in = st.text_input("Password:", type="password")
            if st.form_submit_button("Login", type="primary"):
                if user_in and pass_in: login(user_in, pass_in)
                else: st.warning("Please fill in all fields.")
else:
    col1, col2 = st.columns([8, 2])
    with col1: st.success(f"Welcome, {st.session_state.username}")
    with col2:
        st.markdown("<div class='logout-btn'>", unsafe_allow_html=True)
        if st.button("Logout"): logout()
        st.markdown("</div>", unsafe_allow_html=True)
    st.divider()

    if st.session_state.role == "admin":
        show_admin_panel(siamese_model)
    elif st.session_state.role == "business":
        show_business_panel(siamese_model, DB_DIR)
    elif st.session_state.role == "bank":
        show_bank_panel(siamese_model, DB_DIR)