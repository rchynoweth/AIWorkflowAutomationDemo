"""Shared styles, color tokens, and badge helpers."""
from __future__ import annotations

import html

import streamlit as st

PRIORITY_COLORS = {"CRITICAL": "#B42318", "HIGH": "#C4560C", "MEDIUM": "#A16207", "LOW": "#475467"}
HEALTH_COLORS = {"Healthy": "#067647", "Watch": "#175CD3", "Action Required": "#B54708", "Critical": "#B42318"}
STATE_COLORS = {
    "COMPLETED": "#6C8F7D", "CURRENT": "#175CD3", "UPCOMING": "#0E7490", "SCHEDULED": "#475467",
    "DUE": "#B54708", "OVERDUE": "#B42318", "PROPOSED": "#6941C6", "SUBMITTED": "#3E4784",
    "FAILED": "#7A271A", "VERIFIED": "#067647", "HISTORY": "#98A2B3",
}
VERIFICATION_COLORS = {"VERIFIED": "#067647", "PENDING": "#3E4784", "NOT_FOUND": "#B42318", "MISMATCH": "#B54708",
                       "DUPLICATE": "#B54708", "FAILED": "#7A271A"}

CSS = """
<style>
.block-container {padding-top: 1.2rem; max-width: 1500px;}
.lsi-badge {display:inline-block; padding:2px 8px; border-radius:10px; font-size:0.78rem; font-weight:600;
            color:#fff; letter-spacing:0.02em; white-space:nowrap;}
.lsi-synthetic {background:#FEF0C7; color:#7A2E0E; border:1px solid #FEC84B; padding:3px 10px; border-radius:12px;
                font-size:0.78rem; font-weight:700;}
.lsi-title {font-size:1.7rem; font-weight:700; margin-bottom:0;}
.lsi-subtitle {color:#667085; margin-top:0; font-size:0.95rem;}
.lsi-card {border:1px solid rgba(128,128,128,0.25); border-radius:10px; padding:12px 14px; height:100%;}
.lsi-card .label {font-size:0.78rem; color:#667085; text-transform:uppercase; letter-spacing:0.04em;}
.lsi-card .value {font-size:1.7rem; font-weight:700; line-height:1.2;}
.lsi-ai {border-left:4px solid #6941C6; background:rgba(105,65,198,0.06); padding:10px 14px; border-radius:6px;}
.lsi-rule {border-left:4px solid #175CD3; background:rgba(23,92,211,0.06); padding:10px 14px; border-radius:6px;}
.lsi-tl {border-left:3px solid #D0D5DD; margin-left:8px; padding-left:16px;}
.lsi-tl-item {position:relative; margin-bottom:12px;}
.lsi-tl-dot {position:absolute; left:-24px; top:4px; width:13px; height:13px; border-radius:50%; border:2px solid #fff;}
.lsi-tl-meta {color:#667085; font-size:0.8rem;}
.lsi-flow {display:flex; flex-wrap:wrap; gap:6px; align-items:center; margin:6px 0 12px 0;}
.lsi-step {padding:4px 10px; border-radius:14px; font-size:0.8rem; border:1px solid rgba(128,128,128,0.35);}
.lsi-step.done {background:rgba(6,118,71,0.10); border-color:#067647;}
.lsi-step.miss {opacity:0.45;}
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def badge(text: str | None, color: str | None = None) -> str:
    if not text:
        return ""
    color = color or PRIORITY_COLORS.get(text) or HEALTH_COLORS.get(text) or STATE_COLORS.get(text) \
        or VERIFICATION_COLORS.get(text) or "#475467"
    return f'<span class="lsi-badge" style="background:{color}">{html.escape(str(text))}</span>'


def esc(text) -> str:
    return html.escape("" if text is None else str(text))
