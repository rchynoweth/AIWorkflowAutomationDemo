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
    from app.pages import (agent, agent_activity, evaluation, home, how_it_works, loan_360, portfolio,
                           priority_queue, story)

    PAGES.update({
        "story": st.Page(story.render, title="Demo Story", icon=":material/movie:", url_path="story", default=True),
        "agent": st.Page(agent.render, title="Meet the Agent", icon=":material/smart_toy:", url_path="agent"),
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
        "Demo": [PAGES["story"], PAGES["agent"], PAGES["how_it_works"]],
        "Operations": [PAGES["home"], PAGES["portfolio"], PAGES["priority_queue"], PAGES["loan_360"]],
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
        st.toggle("Presenter notes", value=True, key="presenter_notes",
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
        _backend_panel(client)
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


def _backend_panel(client) -> None:
    """Live status of the Databricks backend workflow, with run-now and sync."""
    with st.expander("Databricks backend", icon=":material/settings_suggest:"):
        try:
            status = _cached_backend_status(client)
        except ApiError as exc:
            st.caption(f"Backend status unavailable: {exc.detail}")
            return
        monitor = next((w for w in status.get("workflows", []) if w.get("name") == "lsi-servicing-monitor"), None)
        if not status.get("available") or not monitor or not monitor.get("found"):
            st.caption("Servicing monitor workflow not found in this workspace.")
            return
        last = monitor["runs"][0] if monitor["runs"] else None
        schedule = "every 30 min" if monitor.get("schedule") else "manual"
        if monitor.get("schedule_paused"):
            schedule += " (paused)"
        st.caption(f"lsi-servicing-monitor - {schedule}")
        if last:
            st.markdown(f"Last run: **{nice_state(last['state'])}**<br>"
                        f"<span style='font-size:0.8rem; color:#667085'>{last.get('start_time') or ''} UTC</span>",
                        unsafe_allow_html=True)
            if last.get("run_page_url"):
                st.link_button("Open run in Databricks", last["run_page_url"], use_container_width=True)
        if st.button("Run workflow now", icon=":material/play_arrow:", use_container_width=True):
            try:
                run = client.run_monitor()
                st.session_state["flash"] = f"Started servicing monitor run {run['run_id']}"
                _cached_backend_status.clear()
            except ApiError as exc:
                st.session_state["flash"] = f"Could not start: {exc.detail}"
            st.rerun()
        if status.get("newer_than_app"):
            st.info("The workflow produced newer results.")
        if st.button("Sync results into the app", icon=":material/cloud_sync:", use_container_width=True,
                     type="primary" if status.get("newer_than_app") else "secondary"):
            with st.spinner("Reloading from Delta tables..."):
                res = client.reload()
            st.session_state["flash"] = f"Synced: {res['recommendations']} recommendations, cycle {res['refresh_cycle']}"
            st.session_state.pop("briefing", None)
            _cached_backend_status.clear()
            st.rerun()


@st.cache_data(ttl=30, show_spinner=False)
def _cached_backend_status(_client) -> dict:
    return _client.backend()


def nice_state(state: str | None) -> str:
    return (state or "").replace("_", " ").title()


def flash() -> None:
    message = st.session_state.pop("flash", None)
    if message:
        st.toast(message)
