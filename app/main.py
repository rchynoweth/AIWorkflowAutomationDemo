"""Loan Servicing Intelligence - the Databricks App (synthetic demonstration data)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # so pages can `from app import data, ui`

import streamlit as st  # noqa: E402

from app import ui  # noqa: E402

st.set_page_config(page_title="Loan Servicing Intelligence", page_icon=":material/account_balance:", layout="wide")
st.markdown(ui.CSS, unsafe_allow_html=True)

page = st.navigation([
    st.Page("pages/portfolio.py", title="Portfolio", icon=":material/table_view:", default=True),
    st.Page("pages/loan.py", title="Loan", icon=":material/account_balance:"),
    st.Page("pages/agent.py", title="The Agent", icon=":material/smart_toy:"),
    st.Page("pages/how_it_works.py", title="How It Works", icon=":material/schema:"),
])

left, right = st.columns([3, 2])
left.markdown("<div style='font-size:1.35rem; font-weight:700'>Loan Servicing Intelligence</div>"
              "<div class='lsi-muted'>Agent-powered portfolio monitoring and loan-servicing workflow automation</div>",
              unsafe_allow_html=True)
right.markdown("<div style='text-align:right; margin-top:10px'><span class='lsi-synthetic'>Synthetic Demonstration Data"
               "</span></div>", unsafe_allow_html=True)

with st.sidebar:
    st.toggle("Presenter notes", value=True, key="presenter_notes")
    st.caption("Synthetic data only. The AI outputs are real, produced on Databricks.")

page.run()
