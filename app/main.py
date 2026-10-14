"""Loan Servicing Intelligence — Streamlit Databricks App entry point (synthetic demonstration)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

st.set_page_config(page_title="Loan Servicing Intelligence", page_icon=":material/account_balance:", layout="wide")

from app.ui import inject_css  # noqa: E402
from app.navigation import build_pages, header, sidebar  # noqa: E402

inject_css()
navigation = st.navigation(build_pages())
header()
sidebar()
navigation.run()
