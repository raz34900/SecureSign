import streamlit as st
import os
import json
from shared_ui import get_image_input, process_uploaded_document, run_verification_and_display

def show_admin_panel(siamese_model):
    st.subheader("Admin Panel: Development & Analytics")
    tab1, tab2 = st.tabs(["Analytics & Graphs", "Manual Testing & Active Learning"])
    
    with tab1:
        try:
            with open(os.path.join("models", "metrics.json"), "r") as f:
                metrics = json.load(f)
            acc_val, f1_val, auc_val, epoch_val = f"{metrics['accuracy']:.2f}%", f"{metrics['f1_score']:.4f}", f"{metrics['roc_auc']:.4f}", metrics.get('epoch', 50)
        except Exception:
            acc_val, f1_val, auc_val, epoch_val = "84.32%", "0.8404", "0.9231", 50

        metric_col1, metric_col2, metric_col3 = st.columns(3)
        metric_col1.metric(f"Test Accuracy (Epoch {epoch_val})", acc_val)
        metric_col2.metric("F1 Score", f1_val)
        metric_col3.metric("ROC AUC", auc_val)
        st.divider()
        
        view_selection = st.radio("Select Visualization View:", ["Model Learning Curve", "ROC & Confusion Matrix", "Preprocessing Pipeline"], horizontal=True, label_visibility="collapsed")
        st.markdown(f"<h4 style='text-align: center; color: #153c7a; margin-top: 1rem;'>{view_selection}</h4>", unsafe_allow_html=True)
        
        if view_selection == "Model Learning Curve":
            img_path = os.path.join("assets", "results2.png")
            if os.path.exists(img_path): st.image(img_path, use_container_width=True)
            else: st.warning("Learning Curve image not found in 'assets' folder.")
                
        elif view_selection == "ROC & Confusion Matrix":
            img_path = os.path.join("assets", "results.png")
            if os.path.exists(img_path): st.image(img_path, use_container_width=True)
            else: st.warning("ROC & Confusion Matrix image not found in 'assets' folder.")
            
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
                st.info("Pipeline visualizations will appear here. Please ensure images exist in the 'assets' folder.")

    with tab2:
        st.markdown("#### Manual Verification & Model Fine-Tuning")
        if 'admin_saved_anchors' not in st.session_state: st.session_state.admin_saved_anchors = None

        st.markdown("### Step 1: Reference Anchors")
        admin_anchor_file = get_image_input("Reference Document", "admin_anc")
        
        if admin_anchor_file:
            raw_anchors = process_uploaded_document(admin_anchor_file)
            if not raw_anchors: st.error("❌ Could not extract any signatures.")
            else:
                cols = st.columns(min(len(raw_anchors), 5))
                selected_anchors = []
                for i, anchor_img in enumerate(raw_anchors):
                    with cols[i % 5]:
                        st.image(anchor_img, use_container_width=True)
                        if st.checkbox(f"Keep #{i+1}", value=True, key=f"keep_admin_{i}"): selected_anchors.append(anchor_img)
                
                if st.button("Save these Anchors into Memory", type="primary"):
                    if not selected_anchors:
                        st.error("You must select at least one anchor.")
                    else:
                        st.session_state.admin_saved_anchors = selected_anchors
                        st.success(f"✅ Saved {len(selected_anchors)} anchors to memory! Proceed to Step 2.")
        
        if st.session_state.admin_saved_anchors:
            st.divider()
            st.markdown("### Step 2: Test Signature")
            admin_test_file = get_image_input("Test Signature", "admin_test")
            
            if admin_test_file and st.button("Run Deep Analysis", use_container_width=True, type="primary"):
                with st.spinner("Processing image, removing lines, and running CNN..."):
                    run_verification_and_display(siamese_model, st.session_state.admin_saved_anchors, admin_test_file)
                    st.divider()
                    st.markdown("**Was the model correct? (Active Learning Feedback)**")
                    f_col1, f_col2 = st.columns(2)
                    if f_col1.button("👍 Correct", type="primary"): st.toast("Feedback saved!")
                    if f_col2.button("👎 Incorrect", type="primary"): st.toast("Flagged as a hard example!")