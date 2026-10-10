"""Interactive portfolio-health segments."""
from __future__ import annotations

import streamlit as st

from app.components.styles import HEALTH_COLORS, esc


def render(summary: dict, key: str = "health_segment") -> str | None:
    segments = summary["health_segments"]
    total = max(1, sum(s["loan_count"] for s in segments))
    bar = "".join(
        f'<div title="{esc(s["health_segment"])}: {s["loan_count"]}" style="width:{100 * s["loan_count"] / total:.2f}%;'
        f'background:{HEALTH_COLORS[s["health_segment"]]}; height:14px"></div>' for s in segments)
    st.markdown(f'<div style="display:flex; border-radius:7px; overflow:hidden; margin:4px 0 10px 0">{bar}</div>',
                unsafe_allow_html=True)
    cols = st.columns(len(segments))
    selected = st.session_state.get(key)
    for col, seg in zip(cols, segments):
        name = seg["health_segment"]
        label = f"{name}: {seg['loan_count']:,} ({seg['share_of_active'] * 100:.1f}%)"
        if col.button(label, key=f"{key}_{name}", use_container_width=True,
                      type="primary" if selected == name else "secondary"):
            st.session_state[key] = None if selected == name else name
            st.rerun()
    return st.session_state.get(key)
