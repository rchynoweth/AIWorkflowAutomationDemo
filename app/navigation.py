"""Pages, header, and sidebar."""
from __future__ import annotations

import streamlit as st

from app.client import ApiError, get_client
from app.ui import esc, nice
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


@st.cache_data(ttl=30, show_spinner=False)
def _workflow_status(_client) -> dict:
    return _client.backend()


def sidebar() -> None:
    client = get_client()
    with st.sidebar:
        st.toggle("Presenter notes", value=True, key="presenter_notes")
        st.markdown("#### Databricks workflow")
        try:
            status = _workflow_status(client)
        except ApiError:
            status = {}
        if status.get("available"):
            last = status["runs"][0] if status.get("runs") else None
            st.caption("lsi-pipeline" + (" - schedule paused" if status.get("schedule_paused") else ""))
            if last:
                st.markdown(f"Last run: **{nice(last['state'])}**<br><span style='font-size:0.8rem; color:#667085'>"
                            f"{last.get('start_time') or ''} UTC</span>", unsafe_allow_html=True)
                if last.get("run_page_url"):
                    st.link_button("Open run in Databricks", last["run_page_url"], use_container_width=True)
            if st.button("Run workflow now", icon=":material/play_arrow:", use_container_width=True):
                try:
                    run = client.run_pipeline()
                    st.toast(f"Started lsi-pipeline run {run['run_id']}")
                except ApiError as exc:
                    st.toast(f"Could not start: {exc.detail}")
                _workflow_status.clear()
        else:
            st.caption("Workflow status appears when the app runs in Databricks.")
        if st.button("Sync AI results", icon=":material/cloud_sync:", use_container_width=True,
                     type="primary" if status.get("newer_than_app") else "secondary",
                     help="Reload the Gold tables after the workflow has run"):
            with st.spinner("Reloading from Delta tables..."):
                client.reload()
            _workflow_status.clear()
            st.rerun()
        st.caption("Synthetic data only. The AI outputs are real, produced on Databricks.")
