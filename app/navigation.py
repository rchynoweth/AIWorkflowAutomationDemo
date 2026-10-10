"""Page registry, global header, and sidebar controls."""
from __future__ import annotations

import streamlit as st

from app.components.styles import esc
from app.state import ApiError, get_client
from src.config.settings import get_settings

PAGES: dict = {}

REVIEWERS = [
    ("SPEC-01", "Synthetic Specialist 01", "LOAN_SERVICING_SPECIALIST"),
    ("SPEC-04", "Synthetic Specialist 04", "SENIOR_SPECIALIST"),
    ("SPEC-06", "Synthetic Specialist 06", "SERVICING_MANAGER"),
]


def build_pages() -> dict:
    from app.pages import (agent_activity, evaluation, home, how_it_works, loan_360, portfolio, priority_queue,
                           story)

    PAGES.update({
        "story": st.Page(story.render, title="Demo Story", icon=":material/movie:", url_path="story", default=True),
        "how_it_works": st.Page(how_it_works.render, title="How It Works", icon=":material/schema:",
                                url_path="how-it-works"),
        "home": st.Page(home.render, title="Home", icon=":material/home:", url_path="home"),
        "priority_queue": st.Page(priority_queue.render, title="Priority Queue", icon=":material/priority_high:",
                                  url_path="priority-queue"),
        "loan_360": st.Page(loan_360.render, title="Loan 360", icon=":material/account_balance:", url_path="loan-360"),
        "portfolio": st.Page(portfolio.render, title="Portfolio", icon=":material/table_view:", url_path="portfolio"),
        "agent_activity": st.Page(agent_activity.render, title="Agent Activity", icon=":material/timeline:",
                                  url_path="agent-activity"),
        "evaluation": st.Page(evaluation.render, title="Evaluation", icon=":material/fact_check:",
                              url_path="evaluation"),
    })
    return {
        "Demo": [PAGES["story"], PAGES["how_it_works"]],
        "Operations": [PAGES["home"], PAGES["priority_queue"], PAGES["loan_360"], PAGES["portfolio"]],
        "Trust": [PAGES["agent_activity"], PAGES["evaluation"]],
    }


def header() -> dict:
    settings = get_settings()
    health = get_client().health()
    left, right = st.columns([3, 2])
    left.markdown(f'<p class="lsi-title">{esc(settings.app_name)}</p>'
                  f'<p class="lsi-subtitle">{esc(settings.subtitle)}</p>', unsafe_allow_html=True)
    right.markdown(f'<div style="text-align:right; margin-top:10px">'
                   f'<span class="lsi-synthetic">{esc(settings.synthetic_label)}</span>'
                   f'<div style="font-size:0.78rem; color:#667085; margin-top:4px">'
                   f'As of {esc(health["processing_date"])} · cycle {health["refresh_cycle"]}</div></div>',
                   unsafe_allow_html=True)
    if health.get("startup_warning"):
        st.warning(health["startup_warning"])
    if health.get("write_errors"):
        st.error("Recent persistence errors: " + " | ".join(health["write_errors"][-2:]))
    return health


def sidebar() -> None:
    client = get_client()
    with st.sidebar:
        st.toggle("🎤 Presenter notes", value=True, key="presenter_notes",
                  help="Show talk-track callouts on each page (from config/demo_story.yml).")
        labels = [f"{name} · {role.replace('_', ' ').title()}" for _, name, role in REVIEWERS]
        idx = st.selectbox("Acting as", range(len(REVIEWERS)), format_func=lambda i: labels[i], key="reviewer_idx")
        st.session_state["reviewer_id"], _, st.session_state["reviewer_role"] = REVIEWERS[idx]
        if st.button("Refresh source & verify", icon=":material/sync:", use_container_width=True):
            try:
                res = client.refresh()
                st.session_state["flash"] = (f"Refresh cycle {res['refresh_cycle']}: "
                                             f"{res['verification'] or 'no submitted actions to verify'}")
            except ApiError as exc:
                st.session_state["flash"] = f"Refresh failed: {exc.detail}"
            st.rerun()
        with st.expander("Demo controls"):
            st.caption("Clears decisions, actions, verification, activity, and simulated System-of-Record updates.")
            if st.button("Reset demo", icon=":material/restart_alt:", use_container_width=True):
                with st.spinner("Resetting demo state..."):
                    res = client.reset()
                st.session_state["flash"] = f"Demo reset ({res['baseline_recommendations']} baseline recommendations)."
                for key in ("selected_loan_id", "briefing", "story_chapter"):
                    st.session_state.pop(key, None)
                st.rerun()
            health = client.health()
            st.caption(f"Backend: {health['backend']} · Agent: {health['agent_mode']} "
                       f"({health.get('model_endpoint')})")
        st.caption("Synthetic data only. No production system is connected. Every consequential action requires "
                   "human approval.")


def flash() -> None:
    message = st.session_state.pop("flash", None)
    if message:
        st.toast(message)
