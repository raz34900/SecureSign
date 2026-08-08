import streamlit as st
import os
from PIL import Image
from shared_ui import render_id_form, get_image_input, run_verification_and_display

def show_business_panel(siamese_model, db_dir):
    st.subheader("Business Panel: Signature Verification")
    st.info("🔒 **Security Protocol:** Please physically verify the customer's ID to match their face before proceeding.")
    
    if 'biz_cust_id' not in st.session_state: 
        st.session_state.biz_cust_id = None
        
    entered_id = render_id_form("biz")
    if entered_id:
        st.session_state.biz_cust_id = entered_id
        
    if st.session_state.biz_cust_id:
        cust_dir = os.path.join(db_dir, st.session_state.biz_cust_id)
        
        # Check if customer exists in the registry
        if not os.path.exists(cust_dir) or len(os.listdir(cust_dir)) < 8:
            st.warning(f"⚠️ Customer '{st.session_state.biz_cust_id}' is NOT enrolled in the SecureSign registry.")
            st.error("Automated verification unavailable. Proceed with manual verification (e.g., physical ID card check) at your own risk.")
        else:
            st.success(f"✅ Customer '{st.session_state.biz_cust_id}' is enrolled. Proceed to capture their signature.")
            st.divider()
            
            # The get_image_input function handles the UI tips and validation automatically
            sig_data = get_image_input("Signature", "biz_sig", is_business=True)
            
            if sig_data and st.button("Verify Signature", use_container_width=True, type="primary"):
                with st.spinner('Analyzing signature...'):
                    anchors_list = [Image.open(os.path.join(cust_dir, f)).convert('L') for f in os.listdir(cust_dir) if f.endswith(('.jpg', '.png'))]
                    
                    st.divider()
                    st.markdown("### Verification Result")
                    
                    # Ensure show_anchors is False for business panel privacy
                    is_genuine, confidence, test_img = run_verification_and_display(siamese_model, anchors_list, sig_data, show_anchors=False)
                    
                    res_col1, res_col2 = st.columns(2)
                    with res_col1:
                        st.image(test_img, caption="Original Scanned Signature", width=250)
                    with res_col2:
                        if is_genuine:
                            st.success("✅ APPROVED: Signature is Genuine.")
                            st.metric("Confidence Score", f"{confidence:.1f}%", "Pass", delta_color="normal")
                        else:
                            st.error("🚨 REJECTED: Suspected Forgery.")
                            st.metric("Confidence Score", f"{confidence:.1f}%", "Fail", delta_color="inverse")