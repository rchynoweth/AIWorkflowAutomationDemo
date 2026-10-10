"""Chronological servicing-event timeline with state styling."""
from __future__ import annotations

import streamlit as st

from app.components.styles import STATE_COLORS, badge, esc


def render(events: list[dict]) -> None:
    if not events:
        st.info("No servicing events.")
        return
    legend = " ".join(badge(s) for s in ("COMPLETED", "CURRENT", "UPCOMING", "DUE", "OVERDUE", "PROPOSED",
                                          "SUBMITTED", "FAILED", "VERIFIED"))
    st.markdown(f"<div style='margin-bottom:8px'>{legend}</div>", unsafe_allow_html=True)
    items = []
    for ev in reversed(events):
        state = ev.get("display_state") or "HISTORY"
        color = STATE_COLORS.get(state, "#98A2B3")
        dashed = "border:2px dashed #6941C6; background:transparent;" if state == "PROPOSED" else f"background:{color};"
        dates = f"Event {esc(ev.get('event_date'))}"
        if ev.get("followup_date"):
            dates += f" · Follow-up {esc(ev['followup_date'])}"
        if ev.get("completed_date"):
            dates += f" · Completed {esc(ev['completed_date'])}"
        title = f"<b>{esc(ev.get('event_type'))}</b>"
        if ev.get("milestone_type"):
            title += f" · {esc(ev['milestone_type'])}"
        items.append(
            f'<div class="lsi-tl-item"><div class="lsi-tl-dot" style="{dashed}"></div>'
            f'{title} {badge(state)}<div class="lsi-tl-meta">{dates} · {esc(ev.get("status"))} · '
            f'{esc(ev.get("source"))} · {esc(ev.get("event_id"))}</div>'
            f'<div style="font-size:0.88rem">{esc(ev.get("event_note"))}</div></div>')
    st.markdown(f'<div class="lsi-tl">{"".join(items)}</div>', unsafe_allow_html=True)
