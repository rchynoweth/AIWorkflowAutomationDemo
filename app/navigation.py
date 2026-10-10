"""Page registry, global header, and sidebar controls."""
from __future__ import annotations

import streamlit as st

from app.components.styles import badge, esc
from app.state import ApiError, get_client
from src.config.settings import get_settings

PAGES: dict = {}

REVIEWERS = [
    ("SPEC-01", "Synthetic Specialist 01", "LOAN_SERVICING_SPECIALIST"),
    ("SPEC-04", "Synthetic Specialist 04", "SENIOR_SPECIALIST"),
    ("SPEC-06", "Synthetic Specialist 06", "SERVICING_MANAGER"),
]


def build_pages() -> list:
    from app.pages import agent_activity, evaluation, home, loan_360, portfolio, priority_queue

    PAGES.update({
        "home": st.Page(home.render, title="Home", icon=":material/home:", url_path="home", default=True),
        "portfolio": st.Page(portfolio.render, title="Portfolio", icon=":material/table_view:", url_path="portfolio"),
        "priority_queue": st.Page(priority_queue.render, title="Priority Queue", icon=":material/priority_high:",
                                  url_path="priority-queue"),
        "loan_360": st.Page(loan_360.render, title="Loan 360", icon=":material/account_balance:", url_path="loan-360"),
        "agent_activity": st.Page(agent_activity.render, title="Agent Activity", icon=":material/timeline:",
                                  url_path="agent-activity"),
        "evaluation": st.Page(evaluation.render, title="Evaluation", icon=":material/fact_check:",
                              url_path="evaluation"),
    })
    return list(PAGES.values())


def header() -> dict:
    settings = get_settings()
    client = get_client()
    health = client.health()
    left, right = st.columns([3, 2])
    with left:
        st.markdown(f'<p class="lsi-title">{esc(settings.app_name)}</p>'
                    f'<p class="lsi-subtitle">{esc(settings.subtitle)}</p>', unsafe_allow_html=True)
    with right:
        agent_label = "LLM" if health["agent_mode"] in ("auto", "llm") else "Deterministic"
        st.markdown(
            f'<div style="text-align:right; margin-top:8px">'
            f'<span class="lsi-synthetic">{esc(settings.synthetic_label)}</span><br>'
            f'<span style="font-size:0.8rem; color:#667085">Processing date <b>{esc(health["processing_date"])}</b>'
            f' · Refresh cycle <b>{health["refresh_cycle"]}</b> · Backend <b>{esc(health["backend"])}</b>'
            f' · Agent <b>{agent_label}</b></span></div>', unsafe_allow_html=True)
    if health.get("startup_warning"):
        st.warning(health["startup_warning"])
    if health.get("write_errors"):
        st.error("Recent persistence errors: " + " | ".join(health["write_errors"][-2:]))
    return health


def sidebar() -> None:
    client = get_client()
    with st.sidebar:
        st.markdown("### Reviewer")
        labels = [f"{name} · {role.replace('_', ' ').title()}" for _, name, role in REVIEWERS]
        idx = st.selectbox("Acting as (synthetic)", range(len(REVIEWERS)), format_func=lambda i: labels[i],
                           key="reviewer_idx")
        st.session_state["reviewer_id"], _, st.session_state["reviewer_role"] = REVIEWERS[idx]
        st.caption("Demo authorization model: identity is selected, not authenticated.")
        st.markdown("### Source cycle")
        if st.button("Refresh source & verify", icon=":material/sync:", use_container_width=True):
            try:
                res = client.refresh()
                st.session_state["flash"] = (f"Refresh cycle {res['refresh_cycle']}: verification "
                                             f"{res['verification'] or 'no submitted actions'}")
            except ApiError as exc:
                st.session_state["flash"] = f"Refresh failed: {exc.detail}"
            st.rerun()
        with st.expander("Demo controls"):
            st.caption("Clears recommendations, decisions, actions, verification, activity, and simulated "
                       "System-of-Record updates; regenerates baseline recommendations.")
            if st.button("Reset demo", icon=":material/restart_alt:", use_container_width=True):
                with st.spinner("Resetting demo state..."):
                    res = client.reset()
                st.session_state["flash"] = f"Demo reset. {res['baseline_recommendations']} baseline recommendations."
                st.session_state.pop("selected_loan_id", None)
                st.rerun()
        st.markdown("---")
        st.caption("All borrowers, loans, rules, thresholds, scores, and metrics are synthetic. "
                   "No production system is connected. Every consequential action requires human approval.")


def flash() -> None:
    message = st.session_state.pop("flash", None)
    if message:
        st.toast(message)


def priority_badge(p: str | None) -> str:
    return badge(p)
