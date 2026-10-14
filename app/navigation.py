"""Pages, header, and sidebar."""
from __future__ import annotations

import streamlit as st

from app.ui import esc
from src.config import get_settings

PAGES: dict = {}


def build_pages() -> list:
    from app.pages import agent, how_it_works, loan, portfolio

    PAGES.update({
        "portfolio": st.Page(portfolio.render, title="Portfolio", icon=":material/table_view:", url_path="portfolio",
                             default=True),
        "loan": st.Page(loan.render, title="Loan", icon=":material/account_balance:", url_path="loan"),
        "agent": st.Page(agent.render, title="The Agent", icon=":material/smart_toy:", url_path="agent"),
        "how_it_works": st.Page(how_it_works.render, title="How It Works", icon=":material/schema:",
                                url_path="how-it-works"),
    })
    return list(PAGES.values())


def header() -> None:
    settings = get_settings()
    left, right = st.columns([3, 2])
    left.markdown(f'<p class="lsi-title">{esc(settings.app_name)}</p>'
                  f'<p class="lsi-subtitle">{esc(settings.subtitle)}</p>', unsafe_allow_html=True)
    right.markdown(f'<div style="text-align:right; margin-top:10px">'
                   f'<span class="lsi-synthetic">{esc(settings.synthetic_label)}</span></div>',
                   unsafe_allow_html=True)


def sidebar() -> None:
    with st.sidebar:
        st.toggle("Presenter notes", value=True, key="presenter_notes")
        st.caption("Synthetic data only. The AI outputs are real, produced on Databricks.")
