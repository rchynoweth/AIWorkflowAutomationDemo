"""KPI cards (computed from GET /api/portfolio/summary)."""
from __future__ import annotations

import streamlit as st

from app.components.styles import esc

KPIS = [
    ("active_loans", "Active Loans", None),
    ("need_attention", "Need Attention", "#B54708"),
    ("upcoming", "Upcoming", "#0E7490"),
    ("overdue", "Overdue", "#B42318"),
    ("missing_followup", "Missing Follow-Up", "#B54708"),
    ("critical", "Critical", "#B42318"),
    ("recommendations_awaiting_approval", "Awaiting Approval", "#6941C6"),
    ("approved_today", "Approved Today", "#067647"),
    ("verification_failures", "Verification Failures", "#7A271A"),
]


def render(summary: dict) -> None:
    for row in (KPIS[:5], KPIS[5:]):
        cols = st.columns(len(row))
        for col, (key, label, color) in zip(cols, row):
            style = f' style="color:{color}"' if color else ""
            col.markdown(f'<div class="lsi-card"><div class="label">{esc(label)}</div>'
                         f'<div class="value"{style}>{summary.get(key, 0):,}</div></div>', unsafe_allow_html=True)
        st.write("")
