"""Shared UI building blocks for the Streamlit pages."""
from __future__ import annotations

import html
import json
import math
from functools import lru_cache

import pandas as pd
import streamlit as st
import yaml

from app.client import open_loan
from src.config import repo_root

PRIORITY_COLORS = {"CRITICAL": "#B42318", "HIGH": "#C4560C", "MEDIUM": "#A16207", "LOW": "#475467"}
HEALTH_COLORS = {"Healthy": "#067647", "Watch": "#175CD3", "Action Required": "#B54708", "Critical": "#B42318"}
STATE_COLORS = {"COMPLETED": "#6C8F7D", "CURRENT": "#175CD3", "UPCOMING": "#0E7490", "SCHEDULED": "#475467",
                "DUE": "#B54708", "OVERDUE": "#B42318", "PROPOSED": "#6941C6", "APPROVED": "#027A48",
                "SUBMITTED": "#3E4784", "FAILED": "#7A271A", "VERIFIED": "#067647", "HISTORY": "#98A2B3"}

CSS = """
<style>
.block-container {padding-top: 1.2rem; max-width: 1400px;}
.lsi-badge {display:inline-block; padding:2px 8px; border-radius:10px; font-size:0.78rem; font-weight:600;
            color:#fff; white-space:nowrap;}
.lsi-synthetic {background:#FEF0C7; color:#7A2E0E; border:1px solid #FEC84B; padding:3px 10px; border-radius:12px;
                font-size:0.78rem; font-weight:700;}
.lsi-title {font-size:1.35rem; font-weight:700; margin-bottom:0;}
.lsi-subtitle {color:#667085; margin-top:0; font-size:0.85rem;}
.lsi-card {border:1px solid rgba(128,128,128,0.25); border-radius:10px; padding:12px 14px;}
.lsi-card .label {font-size:0.78rem; color:#667085; text-transform:uppercase; letter-spacing:0.04em;}
.lsi-card .value {font-size:1.7rem; font-weight:700; line-height:1.2;}
.lsi-ai {border-left:4px solid #6941C6; background:rgba(105,65,198,0.06); padding:10px 14px; border-radius:6px;}
.lsi-rule {border-left:4px solid #175CD3; background:rgba(23,92,211,0.06); padding:10px 14px; border-radius:6px;}
.lsi-src {color:#667085; font-size:0.8rem; margin-top:4px;}
.lsi-tl {border-left:3px solid #D0D5DD; margin-left:8px; padding-left:16px;}
.lsi-tl-item {position:relative; margin-bottom:10px;}
.lsi-tl-dot {position:absolute; left:-24px; top:4px; width:13px; height:13px; border-radius:50%; border:2px solid #fff;}
.lsi-tl-meta {color:#667085; font-size:0.8rem;}
.lsi-talk {border:1px dashed #C4560C; background:rgba(253,233,215,0.45); padding:8px 14px; border-radius:8px;
           margin:4px 0 12px 0; font-size:0.9rem;}
.lsi-talk ul {margin:4px 0 0 0;}
.lsi-why {color:#475467; font-size:0.85rem;}
div[class*="st-key-aibox"] {border-left:4px solid #6941C6; background:rgba(105,65,198,0.06); padding:10px 16px;
                            border-radius:6px; gap:0.3rem;}
div[class*="st-key-aibox"] p, div[class*="st-key-aibox"] li {font-size:0.95rem;}
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def esc(text) -> str:
    return html.escape("" if text is None else str(text))


def nice(code) -> str:
    return str(code or "").replace("_", " ").title()


def badge(text: str | None, color: str | None = None) -> str:
    if not text:
        return ""
    color = color or PRIORITY_COLORS.get(str(text).upper()) or STATE_COLORS.get(text) or "#475467"
    return f'<span class="lsi-badge" style="background:{color}">{esc(text)}</span>'


def card(label: str, value, color: str | None = None) -> str:
    style = f' style="color:{color}"' if color else ""
    return f'<div class="lsi-card"><div class="label">{esc(label)}</div><div class="value"{style}>{value}</div></div>'


def ai_box(text: str, source: str, key: str) -> None:
    """Purple panel for AI-generated content. The text is rendered as Markdown (bold, bullets), with its source."""
    with st.container(key=f"aibox_{key}"):
        st.markdown(text)
        st.caption(source)


def recommended_action(text: str) -> str | None:
    """The ACTION from an agent answer's 'Recommended action: ACTION' line, if present."""
    for line in (text or "").splitlines():
        cleaned = line.replace("*", "").replace("`", "").strip()
        if cleaned.lower().startswith("recommended action:"):
            word = cleaned.split(":", 1)[1].strip().split(" ")[0].strip(".").upper()
            return word or None
    return None


def strip_recommended_line(text: str) -> str:
    """Remove the 'Recommended action:' line (shown separately as a heading)."""
    return "\n".join(line for line in (text or "").splitlines()
                     if not line.replace("*", "").strip().lower().startswith("recommended action:")).strip()


def strip_title(text: str) -> str:
    """Drop a leading title line the model sometimes adds (for example '**Morning Briefing - <date>**')."""
    lines = (text or "").strip().splitlines()
    while lines and (lines[0].startswith("#") or (lines[0].startswith("**") and lines[0].rstrip().endswith("**")
                                                  and len(lines[0]) < 90)):
        lines = lines[1:]
    return "\n".join(lines).strip()


# ---- presenter notes ------------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _talk_track() -> dict:
    with open(repo_root() / "config" / "demo_story.yml", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def notes(page_key: str) -> None:
    """Talk-track callout (servicing story + Databricks), shown when presenter notes are on."""
    if not st.session_state.get("presenter_notes", True):
        return
    page = _talk_track().get("page_notes", {}).get(page_key, {})
    story = "".join(f"<li>{esc(line)}</li>" for line in page.get("story", []))
    platform = "".join(f"<li>{esc(line)}</li>" for line in page.get("databricks", []))
    if story or platform:
        st.markdown(f'<div class="lsi-talk"><b>Talk track</b><ul>{story}</ul>'
                    + (f"<b>On Databricks</b><ul>{platform}</ul>" if platform else "") + "</div>",
                    unsafe_allow_html=True)


# ---- loan list: click a loan ID to open it --------------------------------------------------------
COLUMNS = {  # key: (header, width)
    "loan": ("Loan", 1.3), "borrower": ("Borrower", 1.5), "condition": ("Condition", 1.4), "score": ("Score", 0.6),
    "priority": ("Priority", 0.9), "ai": ("AI summary (Databricks AI Functions)", 4.0),
    "agent": ("Agent review", 1.6),
}


def _cell(row: dict, col: str, ai: dict) -> str:
    if col == "borrower":
        return esc(row.get("borrower_display_name"))
    if col == "condition":
        return esc(nice(row.get("primary_condition")))
    if col == "score":
        return f"<b>{row.get('attention_score')}</b>"
    if col == "priority":
        color = PRIORITY_COLORS.get(row.get("priority"), "#475467")
        return f'<span style="color:{color}; font-weight:700">{esc(nice(row.get("priority")))}</span>'
    if col == "ai":
        insight = ai.get("insights", {}).get(row["loan_id"])
        return f"<span class='lsi-why'>{esc(insight['ai_summary'].replace('**', ''))}</span>" if insight else "<span class='lsi-why'>-</span>"
    if col == "agent":
        review = ai.get("reviews", {}).get(row["loan_id"])
        if not review:
            return "<span class='lsi-why'>-</span>"
        return f"{esc(nice(review.get('recommended_action')) or 'Reviewed')}<br>" \
               f"<span class='lsi-why'>{review.get('tool_call_count')} tool calls</span>"
    return esc(row.get(col))


def loan_list(rows: list[dict], ai: dict, key: str, columns: list[str], page_size: int = 15) -> None:
    if not rows:
        st.info("No loans match.")
        return
    pages = max(1, math.ceil(len(rows) / page_size))
    page = min(max(st.session_state.get(f"{key}_page", 1), 1), pages)
    widths = [COLUMNS[c][1] for c in columns]
    for col, name in zip(st.columns(widths), columns):
        col.markdown(f"<span style='color:#667085; font-size:0.8rem; font-weight:600'>{COLUMNS[name][0]}</span>",
                     unsafe_allow_html=True)
    for i, row in enumerate(rows[(page - 1) * page_size: page * page_size]):
        for col, name in zip(st.columns(widths, vertical_alignment="center"), columns):
            if name == "loan":
                if col.button(row["loan_id"], key=f"{key}_{row['loan_id']}_{i}", type="tertiary"):
                    open_loan(row["loan_id"])
            else:
                col.markdown(_cell(row, name, ai), unsafe_allow_html=True)
    if pages > 1:
        left, mid, right = st.columns([1, 2, 1])
        if left.button("Previous", key=f"{key}_prev", disabled=page <= 1, icon=":material/chevron_left:"):
            st.session_state[f"{key}_page"] = page - 1
            st.rerun()
        mid.markdown(f"<div style='text-align:center; color:#667085'>Page {page} of {pages}</div>",
                     unsafe_allow_html=True)
        if right.button("Next", key=f"{key}_next", disabled=page >= pages, icon=":material/chevron_right:"):
            st.session_state[f"{key}_page"] = page + 1
            st.rerun()


TIMELINE_LABELS = {"PROPOSED": "Proposed - needs confirmation", "APPROVED": "Approved - not yet sent",
                   "SUBMITTED": "Scheduled - awaiting verification", "VERIFIED": "Verified",
                   "FAILED": "Failed", "CURRENT": "Current milestone"}


# ---- event timeline ---------------------------------------------------------------------------------
def timeline(events: list[dict]) -> None:
    if not events:
        st.info("No servicing events.")
        return
    items = []
    for ev in reversed(events):
        state = ev.get("display_state") or "HISTORY"
        dates = f"Event {esc(ev.get('event_date'))}"
        if ev.get("followup_date"):
            dates += f" - follow-up {esc(ev['followup_date'])}"
        if ev.get("completed_date"):
            dates += f" - completed {esc(ev['completed_date'])}"
        title = f"<b>{esc(nice(ev.get('event_type')))}</b>"
        if ev.get("milestone_type"):
            title += f" - {esc(nice(ev['milestone_type']))}"
        items.append(f'<div class="lsi-tl-item"><div class="lsi-tl-dot" style="background:'
                     f'{STATE_COLORS.get(state, "#98A2B3")}"></div>{title} {badge(TIMELINE_LABELS.get(state, nice(state)), STATE_COLORS.get(state))}'
                     f'<div class="lsi-tl-meta">{dates}</div>'
                     f'<div style="font-size:0.86rem">{esc(ev.get("event_note"))}</div></div>')
    st.markdown(f'<div class="lsi-tl">{"".join(items)}</div>', unsafe_allow_html=True)


# ---- deployed agent response ------------------------------------------------------------------------
def agent_response(result: dict) -> None:
    """Answer from the deployed agent plus the tools it chose and what they returned."""
    steps = result.get("steps") or []
    if steps:
        chain = " -> ".join(s["tool"] for s in steps)
        st.markdown(f"<div class='lsi-why'>The agent called {len(steps)} Unity Catalog tools in "
                    f"{result.get('seconds')} s: {esc(chain)}</div>", unsafe_allow_html=True)
        with st.expander("Tool calls and the rows they returned"):
            for step in steps:
                st.markdown(f"**{step['tool']}** `{step['arguments']}`")
                try:
                    rows = json.loads(step["output"] or "{}").get("rows", [])
                    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
                except (ValueError, TypeError):
                    st.code(str(step["output"])[:1500])
    st.markdown(result.get("answer") or "")


# ---- custom instructions for the on-demand agent ----------------------------------------------------
PRESETS = {
    "None - standard analysis": "",
    "Draft an email to the assigned attorney or vendor":
        "Finish with a short, polite email (at most 120 words) to the assigned attorney or vendor asking for a "
        "status update. Sign it 'Loan Servicing Team'.",
    "Summarize for a manager": "Answer as three bullets a servicing manager can read in ten seconds.",
    "Focus on missing information": "Focus on what information is missing or inconsistent and how to get it.",
    "Explain for a new team member": "Explain it simply for someone new to loan servicing, defining any terms.",
}


def instructions_box(key: str) -> str:
    """Preset or free-text instructions that augment the deployed agent for one request (custom_inputs)."""
    left, right = st.columns([1, 2])
    preset = left.selectbox("Custom instructions", list(PRESETS), key=f"{key}_preset",
                            help="Sent with the request as custom_inputs; the agent appends them to its instructions.")
    text = right.text_area("Instructions sent to the agent", value=PRESETS[preset], key=f"{key}_text_{preset}",
                           height=68, placeholder="Optional: add your own instructions for this request")
    return text.strip()
