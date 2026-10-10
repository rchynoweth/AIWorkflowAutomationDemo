"""KPI cards (computed from GET /api/portfolio/summary)."""
from __future__ import annotations

import streamlit as st

from app.components.styles import esc

KPIS = [
    ("active_loans", "Active loans", None),
    ("need_attention", "Need attention", "#B54708"),
    ("critical", "Critical", "#B42318"),
    ("recommendations_awaiting_approval", "Awaiting approval", "#6941C6"),
    ("verification_failures", "Failed verification", "#7A271A"),
]


def render(summary: dict) -> None:
    cols = st.columns(len(KPIS))
    for col, (key, label, color) in zip(cols, KPIS):
        style = f' style="color:{color}"' if color else ""
        col.markdown(f'<div class="lsi-card"><div class="label">{esc(label)}</div>'
                     f'<div class="value"{style}>{summary.get(key, 0):,}</div></div>', unsafe_allow_html=True)
    with st.expander("More metrics"):
        more = [("Upcoming", "upcoming"), ("Due today", "due"), ("Overdue", "overdue"),
                ("Missing follow-up", "missing_followup"), ("Data exceptions", "data_exceptions"),
                ("Approved today", "approved_today"), ("Awaiting verification", "pending_actions")]
        cols = st.columns(len(more))
        for col, (label, key) in zip(cols, more):
            col.metric(label, f"{summary.get(key, 0):,}")
