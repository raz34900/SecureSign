import streamlit as st
import os
from PIL import Image
from shared_ui import render_id_form, get_image_input, process_uploaded_document, save_anchors_to_db, run_verification_and_display

def show_bank_panel(siamese_model, db_dir):
    st.subheader("Bank Panel: Customer Management & Verification")
    tab1, tab2, tab3 = st.tabs(["Enroll / Update Customer", "Verify Customer Signature", "Search Existing Customers"])
    
    # --- TAB 1: ENROLL ---
    with tab1:
        st.markdown("#### Enroll New or Update Existing Customer")
        
        if 'bank_enroll_id' not in st.session_state: st.session_state.bank_enroll_id = None
        entered_id = render_id_form("bank_enr")
        if entered_id: st.session_state.bank_enroll_id = entered_id
            
        if st.session_state.bank_enroll_id:
            cust_dir = os.path.join(db_dir, st.session_state.bank_enroll_id)
            existing_count = len(os.listdir(cust_dir)) if os.path.exists(cust_dir) else 0
            
            if existing_count > 0:
                st.info(f"📁 Customer '{st.session_state.bank_enroll_id}' found. They currently have {existing_count} verified anchors.")
            else:
                st.success(f"✨ New Customer detected. Please proceed to capture their signature anchors.")
                
            st.divider()
            
            # Specimen Card Guide
            with st.expander("❓ How to prepare the specimen card"):
                st.write("For the system to extract signatures correctly, please ensure the customer signs multiple times on a single blank white page, **one signature below the other**, with clear vertical spacing between them.")
                st.markdown("<div style='text-align:center; padding: 15px; border: 2px dashed #8cc440; background-color: #f9f9f9; color: #333;'><b>Example Layout:</b><br><br><i>Signature 1</i><br><br><i>Signature 2</i><br><br><i>Signature 3</i><br><br>...</div>", unsafe_allow_html=True)
                st.caption("A minimum of 8 total signatures are required for a complete profile.")
            
            anchor_data = get_image_input("Specimen Document", "bank_enroll_img")
                
            if anchor_data:
                raw_anchors = process_uploaded_document(anchor_data)
                if not raw_anchors: 
                    st.error("❌ Could not extract any signatures. Please ensure vertical spacing between signatures.")
                else:
                    st.markdown("#### Review & Filter Extracted Signatures")
                    cols = st.columns(min(len(raw_anchors), 5))
                    selected_anchors = []
                    for i, anchor_img in enumerate(raw_anchors):
                        with cols[i % 5]:
                            st.image(anchor_img, use_container_width=True)
                            if st.checkbox(f"Keep #{i+1}", value=True, key=f"keep_t1_{i}"): selected_anchors.append(anchor_img)
                                
                    total_proposed = existing_count + len(selected_anchors)
                    st.write(f"**Existing Anchors:** {existing_count} | **Selected to Add:** {len(selected_anchors)} | **Total will be:** {total_proposed}")
                    
                    if st.button("Save Confirmed Signatures to Database", use_container_width=True, type="primary"):
                        if not selected_anchors: 
                            st.error("You must select at least one signature to save.")
                        elif total_proposed < 8 or total_proposed > 15: 
                            st.error(f"❌ Cannot save! A customer must have strictly between 8 and 15 anchors.")
                        else:
                            is_existing = os.path.exists(cust_dir)
                            save_anchors_to_db(cust_dir, selected_anchors)
                            msg = f"Existing customer '{st.session_state.bank_enroll_id}' updated" if is_existing else f"New customer '{st.session_state.bank_enroll_id}' saved securely"
                            st.success(f"✅ {msg} with {len(selected_anchors)} new anchors.")

    # --- TAB 2: VERIFY ---
    with tab2:
        st.markdown("#### Branch Verification (Detailed View)")
        
        if 'bank_ver_id' not in st.session_state: st.session_state.bank_ver_id = None
        v_entered_id = render_id_form("bank_ver")
        if v_entered_id: st.session_state.bank_ver_id = v_entered_id
            
        if st.session_state.bank_ver_id:
            cust_dir = os.path.join(db_dir, st.session_state.bank_ver_id)
            if not os.path.exists(cust_dir) or len(os.listdir(cust_dir)) < 8:
                st.error(f"❌ Customer ID '{st.session_state.bank_ver_id}' has an incomplete profile. Cannot verify.")
            else:
                ver_data = get_image_input("Signature", "bank_verify_img")
                if ver_data and st.button("Verify Customer", use_container_width=True, type="primary"):
                    with st.spinner("Fetching anchors from database and analyzing..."):
                        anchors_list = [Image.open(os.path.join(cust_dir, f)).convert('L') for f in os.listdir(cust_dir) if f.endswith(('.jpg', '.png'))]
                        run_verification_and_display(siamese_model, anchors_list, ver_data)

    # --- TAB 3: SEARCH / UPDATE ---
    with tab3:
        st.markdown("#### Search & Manage Customer Database")
        
        if 'bank_search_id' not in st.session_state: st.session_state.bank_search_id = None
        s_entered_id = render_id_form("bank_search")
        if s_entered_id: st.session_state.bank_search_id = s_entered_id
        
        if st.session_state.bank_search_id:
            search_id = st.session_state.bank_search_id
            cust_dir = os.path.join(db_dir, search_id)
            if os.path.exists(cust_dir) and len(os.listdir(cust_dir)) > 0:
                existing_files = [f for f in os.listdir(cust_dir) if f.endswith(('.jpg', '.png'))]
                st.success(f"✅ Found Customer: '{search_id}' | Total Verified Anchors: {len(existing_files)}")
                
                cols_per_row = 5
                for i in range(0, len(existing_files), cols_per_row):
                    cols = st.columns(cols_per_row)
                    for j in range(cols_per_row):
                        if i + j < len(existing_files):
                            f_name = existing_files[i + j]
                            img_path = os.path.join(cust_dir, f_name)
                            with cols[j]:
                                st.image(img_path, caption=f"Anchor {i+j+1}", use_container_width=True)
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
                                    if st.button("✖", key=f"del_{search_id}_{f_name}", help="Delete this signature", type="secondary"):
                                        st.session_state.delete_confirm = img_path
                                        st.rerun()
                    
                st.divider()
                st.markdown("##### Add More Signatures to this Profile")
                add_data = get_image_input("Document", "bank_append")
                    
                if add_data:
                    raw_add_anchors = process_uploaded_document(add_data)
                    if raw_add_anchors:
                        cols_add = st.columns(min(len(raw_add_anchors), 5))
                        selected_add = []
                        for i, anchor_img in enumerate(raw_add_anchors):
                            with cols_add[i % 5]:
                                st.image(anchor_img, use_container_width=True)
                                if st.checkbox(f"Keep #{i+1}", value=True, key=f"keep_t3_{i}"): selected_add.append(anchor_img)
                                    
                        total_future = len(existing_files) + len(selected_add)
                        if st.button("Append Signatures to Profile", key="btn_append_t3", type="primary"):
                            if not selected_add: st.error("You must select at least one signature to add.")
                            elif total_future > 15 or total_future < 8: st.error(f"❌ Cannot save! Total anchors must be between 8 and 15.")
                            else:
                                save_anchors_to_db(cust_dir, selected_add)
                                st.success(f"✅ Successfully added {len(selected_add)} anchors to '{search_id}'.")
                                st.session_state.delete_confirm = None
                                st.rerun()
            else:
                st.error(f"❌ Customer '{search_id}' not found in the database.")