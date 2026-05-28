"""
Streamlit Cloud entry point.
Redirects to webapp/app.py
"""
import sys
import os
import traceback

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    from webapp.app import main
    main()
except Exception as e:
    try:
        import streamlit as st
        st.error(f"**App startup error:**\n\n```\n{traceback.format_exc()}\n```")
    except Exception:
        raise
