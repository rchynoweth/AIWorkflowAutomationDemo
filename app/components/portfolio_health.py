"""Interactive portfolio-health segments."""
from __future__ import annotations

import streamlit as st

from app.components.styles import HEALTH_COLORS, esc


def render(summary: dict, key: str = "health_segment") -> str | None:
    segments = summary["health_segments"]
    total = max(1, sum(s["loan_count"] for s in segments))
    bar = "".join(
        f'<div title="{esc(s["health_segment"])}: {s["loan_count"]}" style="width:{100 * s["loan_count"] / total:.2f}%;'
        f'background:{HEALTH_COLORS[s["health_segment"]]}; height:12px"></div>' for s in segments)
    st.markdown("#### Portfolio health")
    st.markdown(f'<div style="display:flex; border-radius:6px; overflow:hidden; margin:2px 0 8px 0">{bar}</div>',
                unsafe_allow_html=True)
    labels = {s["health_segment"]: f"{s['health_segment']} · {s['loan_count']:,}" for s in segments}
    choice = st.segmented_control("Filter tasks by health", list(labels), format_func=lambda s: labels[s],
                                  key=key, label_visibility="collapsed")
    return choice
