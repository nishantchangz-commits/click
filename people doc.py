"""
People & Documents manager — a Streamlit UI over database.py.

Lets you:
- add people
- upload documents against each person, tagged by type (resume, photo,
  id_proof, certificate, other)
- view, download, replace, re-tag, or delete any document
- edit a person's name/notes, or delete a person (which removes all
  their files too)

Run with:
    streamlit run app.py
"""

import streamlit as st

from database import (
    DOCUMENT_TYPES,
    add_person,
    delete_document,
    delete_person,
    get_all_people,
    get_document_bytes,
    get_documents_for_person,
    init_db,
    replace_document_file,
    save_document,
    update_document_metadata,
    update_person,
)

init_db()

st.set_page_config(page_title="People & Documents", page_icon="🗂️", layout="wide")
st.title("🗂️ People & Documents Manager")


# ============================================================
# SIDEBAR — add a new person
# ============================================================

with st.sidebar:
    st.header("Add a person")
    new_name = st.text_input("Name")
    new_notes = st.text_area("Notes (optional)", height=80)
    if st.button("Add person", type="primary"):
        if new_name.strip():
            add_person(new_name.strip(), new_notes.strip())
            st.success(f"Added {new_name}.")
            st.rerun()
        else:
            st.warning("Enter a name first.")

    st.markdown("---")
    st.caption(
        "⚠️ If you're storing government ID documents (Aadhaar, PAN, "
        "passport, etc.), keep this app's storage folder and database "
        "file private — they are **not encrypted** by default. See the "
        "README for how to add encryption-at-rest if this will hold "
        "real people's documents."
    )


# ============================================================
# MAIN — pick a person, manage their documents
# ============================================================

people = get_all_people()

if not people:
    st.info("No people added yet. Use the sidebar to add your first person.")
    st.stop()

person_names = {f"{p.name} (id {p.person_id})": p for p in people}
selected_label = st.selectbox("Select a person", list(person_names.keys()))
person = person_names[selected_label]

col1, col2 = st.columns([3, 1])
with col1:
    st.subheader(person.name)
    if person.notes:
        st.caption(person.notes)
with col2:
    with st.expander("Edit / delete person"):
        edited_name = st.text_input("Name", value=person.name, key=f"name_{person.person_id}")
        edited_notes = st.text_area("Notes", value=person.notes, key=f"notes_{person.person_id}")
        if st.button("Save changes", key=f"save_{person.person_id}"):
            update_person(person.person_id, edited_name, edited_notes)
            st.success("Updated.")
            st.rerun()
        st.markdown("---")
        if st.button("🗑️ Delete this person and ALL their documents", key=f"delperson_{person.person_id}"):
            delete_person(person.person_id)
            st.success("Deleted.")
            st.rerun()

st.markdown("---")

# ------------------------------------------------------------
# Upload a new document for this person
# ------------------------------------------------------------

st.subheader("Upload a document")
upload_col1, upload_col2 = st.columns([2, 1])
with upload_col1:
    uploaded_file = st.file_uploader(
        "Choose a file", type=None, key=f"uploader_{person.person_id}"
    )
with upload_col2:
    doc_type = st.selectbox("Document type", DOCUMENT_TYPES, key=f"doctype_{person.person_id}")

doc_notes = st.text_input("Notes for this document (optional)", key=f"docnotes_{person.person_id}")

if st.button("Upload", key=f"upload_{person.person_id}"):
    if uploaded_file is not None:
        save_document(
            person_id=person.person_id,
            doc_type=doc_type,
            original_filename=uploaded_file.name,
            file_bytes=uploaded_file.getvalue(),
            notes=doc_notes,
        )
        st.success(f"Uploaded '{uploaded_file.name}' as {doc_type}.")
        st.rerun()
    else:
        st.warning("Choose a file first.")

st.markdown("---")

# ------------------------------------------------------------
# List, view, edit, replace, delete existing documents
# ------------------------------------------------------------

st.subheader("Documents on file")

documents = get_documents_for_person(person.person_id)

if not documents:
    st.caption("No documents uploaded yet.")

# Group documents by type for a tidier view
by_type: dict[str, list] = {}
for doc in documents:
    by_type.setdefault(doc.doc_type, []).append(doc)

for doc_type_group in DOCUMENT_TYPES:
    docs_of_type = by_type.get(doc_type_group, [])
    if not docs_of_type:
        continue

    st.markdown(f"**{doc_type_group.replace('_', ' ').title()}**")
    for doc in docs_of_type:
        with st.container(border=True):
            c1, c2, c3 = st.columns([3, 2, 2])

            with c1:
                st.write(f"📄 {doc.original_filename}")
                st.caption(f"Uploaded {doc.uploaded_at}" + (f" — {doc.notes}" if doc.notes else ""))
                st.download_button(
                    "Download",
                    data=get_document_bytes(doc),
                    file_name=doc.original_filename,
                    key=f"download_{doc.doc_id}",
                )

            with c2:
                with st.expander("Edit"):
                    new_type = st.selectbox(
                        "Type", DOCUMENT_TYPES, index=DOCUMENT_TYPES.index(doc.doc_type),
                        key=f"edittype_{doc.doc_id}",
                    )
                    new_notes = st.text_input("Notes", value=doc.notes, key=f"editnotes_{doc.doc_id}")
                    if st.button("Save", key=f"savemeta_{doc.doc_id}"):
                        update_document_metadata(doc.doc_id, new_type, new_notes)
                        st.success("Saved.")
                        st.rerun()

                    st.markdown("---")
                    replacement = st.file_uploader(
                        "Replace file", type=None, key=f"replace_{doc.doc_id}"
                    )
                    if replacement is not None and st.button("Upload replacement", key=f"doreplace_{doc.doc_id}"):
                        replace_document_file(doc.doc_id, replacement.name, replacement.getvalue())
                        st.success("File replaced.")
                        st.rerun()

            with c3:
                if st.button("🗑️ Delete document", key=f"deldoc_{doc.doc_id}"):
                    delete_document(doc.doc_id)
                    st.rerun()
