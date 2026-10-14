"""Headless render check of every page via Streamlit AppTest (local backend, deterministic agent)."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("LSI_AGENT_MODE", "deterministic")
os.environ.setdefault("LSI_REPOSITORY_BACKEND", "local")

from streamlit.testing.v1 import AppTest  # noqa: E402

failures = 0
for page in ["story", "agent", "how_it_works", "home", "portfolio", "priority_queue", "loan_360", "agent_activity", "evaluation"]:
    script = f"""
import sys; sys.path.insert(0, r"{ROOT}")
import streamlit as st
from app.ui import inject_css
from app.navigation import build_pages, header, PAGES, sidebar
inject_css(); build_pages(); header(); sidebar()
st.session_state.setdefault("selected_loan_id", "LSI-SYN-000005")
import app.pages.{page} as p
p.render()
"""
    at = AppTest.from_string(script, default_timeout=240)
    at.run()
    errs = [e.value for e in at.exception]
    status = "OK" if not errs else "ERROR"
    failures += bool(errs)
    print(f"{page:16s} {status} markdown={len(at.markdown)} dataframes={len(at.dataframe)}")
    for e in errs:
        print("   ", str(e)[:1500])
sys.exit(1 if failures else 0)
