"""
streamlit_upload.py - UI integration for the database upload feature.

render_upload_section() goes in the sidebar. Two checkboxes:
  1. "Incarc un fisier ZIP"            -> enables zip mode (accepts .zip)
  2. "ZIP-ul contine si exemple..."    -> only enabled when checkbox 1 is on;
                                          tells the handler to load examples.jsonl

get_active_vanna() / get_active_engine() route chat queries to the uploaded DB.
is_upload_active() lets streamlit_app.py skip T-SQL conversion for uploads
(uploaded SQLite/PostgreSQL databases use their native syntax).

Import paths use no 'app.' prefix to match the Docker working directory (/app).
"""

from datetime import datetime
import streamlit as st
from upload.upload_handler import (
    handle_upload,
    cleanup_session,
    cleanup_expired_sessions,
    MAX_FILE_SIZE_MB,
    SESSION_TIMEOUT_MINUTES,
)


def render_upload_section():
    """Render the upload UI. Call this from the sidebar in streamlit_app.py."""
    st.header("Incarca o baza de date proprie")

    session = st.session_state.get("upload_session")
    if session:
        msg = (
            f"Baza de date activa: {session.table_count} tabele, "
            f"{session.column_count} coloane"
        )
        if session.example_count:
            msg += f", {session.example_count} exemple"
        st.success(msg)
        st.caption(f"Sesiunea expira in {_format_remaining(session)}")
        if st.button("Reseteaza (revino la baza sintetica)"):
            cleanup_session(session.session_id)
            st.session_state.upload_session = None
            st.session_state.active_vanna = None
            st.rerun()
        st.info("Pune intrebari in chat-ul principal - sistemul foloseste baza incarcata.")
        return

    # --- Checkbox 1: ZIP mode ---
    zip_mode = st.checkbox(
        "Incarc un fisier ZIP",
        key="upload_zip_mode",
        help="ZIP cu structura: database.sqlite (sau .db/.sqlite3/.sql) "
             "si optional examples.jsonl",
    )

    # --- Checkbox 2: examples (only enabled when zip_mode is on) ---
    load_examples = st.checkbox(
        "ZIP-ul contine si exemple (examples.jsonl) pentru acuratete sporita",
        key="upload_load_examples",
        value=False,
        disabled=not zip_mode,
        help="Exemple intrebare-SQL (few-shot) cresc acuratetea generarii. "
             "Fisier examples.jsonl, o pereche per linie: "
             '{"question": "...", "sql": "..."}',
    )

    if zip_mode:
        accepted = ["zip"]
        caption = (
            f"Incarca un ZIP cu database.sqlite (sau .db/.sqlite3/.sql) "
            f"si optional examples.jsonl. Maxim {MAX_FILE_SIZE_MB} MB."
        )
    else:
        accepted = ["sql", "db", "sqlite", "sqlite3"]
        caption = (
            f"Incarca un fisier SQL (.sql) sau SQLite (.db, .sqlite). "
            f"Maxim {MAX_FILE_SIZE_MB} MB. Sesiune: {SESSION_TIMEOUT_MINUTES} min."
        )
    st.caption(caption)

    uploaded_file = st.file_uploader(
        "Alege fisierul",
        type=accepted,
        key=f"db_uploader_{'zip' if zip_mode else 'plain'}",
    )

    if uploaded_file is not None:
        file_bytes = uploaded_file.read()
        with st.spinner(f"Procesare {uploaded_file.name}..."):
            session, error = handle_upload(
                file_bytes,
                uploaded_file.name,
                load_examples=(zip_mode and load_examples),
            )
        if error:
            st.error(f"Eroare: {error}")
        else:
            st.session_state.upload_session = session
            st.session_state.active_vanna = session.vanna_instance
            ok = f"Procesat: {session.table_count} tabele, {session.column_count} coloane"
            if session.example_count:
                ok += f", {session.example_count} exemple incarcate"
            elif zip_mode and load_examples:
                ok += " (atentie: examples.jsonl nu a fost gasit in ZIP)"
            st.success(ok)
            st.rerun()


def _format_remaining(session) -> str:
    remaining = session.expires_at - datetime.now()
    minutes = int(remaining.total_seconds() / 60)
    return f"{minutes} min" if minutes > 0 else "expirata"


def is_upload_active() -> bool:
    """True when a non-expired uploaded database is in use.

    streamlit_app.py uses this to decide whether to apply the T-SQL
    conversion (only for the default SQL Server bank DB, never for uploads).
    """
    session = st.session_state.get("upload_session")
    return bool(session and not session.is_expired())


def get_active_vanna(default_vanna):
    """Return the upload Vanna if a non-expired session exists, else the default."""
    cleanup_expired_sessions()
    session = st.session_state.get("upload_session")
    if session and not session.is_expired():
        return st.session_state.active_vanna
    if session and session.is_expired():
        cleanup_session(session.session_id)
        st.session_state.upload_session = None
        st.session_state.active_vanna = None
        st.warning("Sesiunea de incarcare a expirat. Sistemul foloseste baza sintetica.")
    return default_vanna


def get_active_engine(default_engine):
    """Return the uploaded DB engine if a session is active, else the default."""
    session = st.session_state.get("upload_session")
    if session and not session.is_expired():
        vn = st.session_state.get("active_vanna")
        if vn is not None and hasattr(vn, "connect_to_engine"):
            return vn.connect_to_engine
    return default_engine