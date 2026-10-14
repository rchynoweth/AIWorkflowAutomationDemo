"""Shared look and building blocks for the pages."""
from __future__ import annotations

import html
import json
import math
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml

PRIORITY_COLORS = {"CRITICAL": "#B42318", "HIGH": "#C4560C", "MEDIUM": "#A16207", "LOW": "#475467"}
STATE_COLORS = {"COMPLETED": "#6C8F7D", "CURRENT": "#175CD3", "OPEN": "#475467", "OVERDUE": "#B42318",
                "PROPOSED": "#6941C6", "SCHEDULED": "#027A48"}
STATE_LABELS = {"CURRENT": "Current milestone", "PROPOSED": "Proposed - needs your confirmation",
                "SCHEDULED": "From the app"}

CSS = """
<style>
.block-container {padding-top: 1.2rem; max-width: 1400px;}
.lsi-badge {display:inline-block; padding:2px 8px; border-radius:10px; font-size:0.78rem; font-weight:600;
            color:#fff; white-space:nowrap;}
.lsi-synthetic {background:#FEF0C7; color:#7A2E0E; border:1px solid #FEC84B; padding:3px 10px; border-radius:12px;
                font-size:0.78rem; font-weight:700;}
.lsi-card {border:1px solid rgba(128,128,128,0.25); border-radius:10px; padding:12px 14px;}
.lsi-card .label {font-size:0.78rem; color:#667085; text-transform:uppercase; letter-spacing:0.04em;}
.lsi-card .value {font-size:1.7rem; font-weight:700; line-height:1.2;}
.lsi-rule {border-left:4px solid #175CD3; background:rgba(23,92,211,0.06); padding:10px 14px; border-radius:6px;}
.lsi-tl {border-left:3px solid #D0D5DD; margin-left:8px; padding-left:16px;}
.lsi-tl-item {position:relative; margin-bottom:10px;}
.lsi-tl-dot {position:absolute; left:-24px; top:4px; width:13px; height:13px; border-radius:50%; border:2px solid #fff;}
.lsi-muted {color:#667085; font-size:0.85rem;}
.lsi-talk {border:1px dashed #C4560C; background:rgba(253,233,215,0.45); padding:8px 14px; border-radius:8px;
           margin:4px 0 12px 0; font-size:0.9rem;}
.lsi-talk ul {margin:4px 0 0 0;}
div[class*="st-key-aibox"] {border-left:4px solid #6941C6; background:rgba(105,65,198,0.06); padding:10px 16px;
                            border-radius:6px; gap:0.3rem;}
</style>
"""


def esc(text) -> str:
    return html.escape("" if text is None else str(text))


def nice(code) -> str:
    return str(code or "").replace("_", " ").title()


def badge(text: str, color: str | None = None) -> str:
    color = color or PRIORITY_COLORS.get(str(text).upper(), "#475467")
    return f'<span class="lsi-badge" style="background:{color}">{esc(text)}</span>'


def card(label: str, value, color: str | None = None) -> str:
    style = f' style="color:{color}"' if color else ""
    return f'<div class="lsi-card"><div class="label">{esc(label)}</div><div class="value"{style}>{value}</div></div>'


def ai_box(text: str, source: str, key: str) -> None:
    """Purple panel for AI-generated text (rendered as Markdown) with where it came from."""
    with st.container(key=f"aibox_{key}"):
        st.markdown(text)
        st.caption(source)


# ---- presenter notes --------------------------------------------------------------------------------------------
@st.cache_data
def _talk_track() -> dict:
    return yaml.safe_load((Path(__file__).parent / "demo_story.yml").read_text(encoding="utf-8")) or {}


def notes(page: str) -> None:
    """Talk track for the page (use case + Databricks), shown while Presenter notes is on."""
    if not st.session_state.get("presenter_notes", True):
        return
    page_notes = _talk_track().get(page, {})
    story = "".join(f"<li>{esc(line)}</li>" for line in page_notes.get("story", []))
    platform = "".join(f"<li>{esc(line)}</li>" for line in page_notes.get("databricks", []))
    st.markdown(f'<div class="lsi-talk"><b>Talk track</b><ul>{story}</ul><b>On Databricks</b><ul>{platform}</ul></div>',
                unsafe_allow_html=True)


# ---- loan list: click a loan ID to open it ----------------------------------------------------------------------
def open_loan(loan_id: str) -> None:
    st.session_state["loan_id"] = loan_id
    st.switch_page("pages/loan.py")


def loan_list(rows: list[dict], ai: dict, page_size: int = 15) -> None:
    if not rows:
        st.info("No loans match.")
        return
    pages = max(1, math.ceil(len(rows) / page_size))
    page = min(st.session_state.get("list_page", 1), pages)
    widths = [1.3, 0.9, 1.5, 0.6, 4.0, 1.6]
    for col, header in zip(st.columns(widths), ["Loan", "Priority", "Condition", "Score",
                                                 "AI summary (Databricks AI Functions)", "Agent draft (overnight)"]):
        col.markdown(f"<span class='lsi-muted'><b>{header}</b></span>", unsafe_allow_html=True)
    for row in rows[(page - 1) * page_size: page * page_size]:
        cols = st.columns(widths, vertical_alignment="center")
        if cols[0].button(row["loan_id"], key=f"open_{row['loan_id']}", type="tertiary"):
            open_loan(row["loan_id"])
        color = PRIORITY_COLORS.get(row["priority"])
        cols[1].markdown(f"<b style='color:{color}'>{nice(row['priority'])}</b>", unsafe_allow_html=True)
        cols[2].markdown(nice(row["primary_condition"]))
        cols[3].markdown(f"**{row['attention_score']}**")
        insight = ai["insights"].get(row["loan_id"])
        cols[4].markdown(f"<span class='lsi-muted'>{esc(insight['ai_summary'].replace('**', '')) if insight else '-'}"
                         "</span>", unsafe_allow_html=True)
        draft = ai["reviews"].get(row["loan_id"])
        cols[5].markdown(f"{nice(draft['recommended_action'])}<br><span class='lsi-muted'>follow-up "
                         f"{draft['proposed_followup_date']}</span>" if draft else "<span class='lsi-muted'>-</span>",
                         unsafe_allow_html=True)
    if pages > 1:
        left, mid, right = st.columns([1, 2, 1])
        if left.button("Previous", disabled=page <= 1, icon=":material/chevron_left:"):
            st.session_state["list_page"] = page - 1
            st.rerun()
        mid.markdown(f"<div style='text-align:center' class='lsi-muted'>Page {page} of {pages}</div>",
                     unsafe_allow_html=True)
        if right.button("Next", disabled=page >= pages, icon=":material/chevron_right:"):
            st.session_state["list_page"] = page + 1
            st.rerun()


# ---- servicing timeline -----------------------------------------------------------------------------------------
def timeline(events: list[dict]) -> None:
    """Newest first. Each event carries a display `state` (see STATE_COLORS)."""
    items = []
    for ev in events:
        state = ev["state"]
        dates = f"Event {esc(ev.get('event_date') or 'on confirmation')}"
        if ev.get("followup_date"):
            dates += f" - follow-up {esc(ev['followup_date'])}"
        if ev.get("completed_date"):
            dates += f" - completed {esc(ev['completed_date'])}"
        title = f"<b>{esc(nice(ev['event_type']))}</b>"
        if ev.get("milestone_type"):
            title += f" - {esc(nice(ev['milestone_type']))}"
        items.append(f'<div class="lsi-tl-item"><div class="lsi-tl-dot" style="background:{STATE_COLORS[state]}"></div>'
                     f'{title} {badge(STATE_LABELS.get(state, nice(state)), STATE_COLORS[state])}'
                     f'<div class="lsi-muted">{dates}</div><div style="font-size:0.86rem">{esc(ev.get("event_note"))}'
                     '</div></div>')
    st.markdown(f'<div class="lsi-tl">{"".join(items)}</div>', unsafe_allow_html=True)


# ---- the deployed agent's answer --------------------------------------------------------------------------------
def agent_answer(result: dict) -> None:
    """The tools the agent chose (with the rows they returned), then its answer."""
    steps = result.get("steps") or []
    if steps:
        chain = " -> ".join(s["tool"] for s in steps)
        st.markdown(f"<div class='lsi-muted'>Called {len(steps)} Unity Catalog tools in {result.get('seconds')} s: "
                    f"{esc(chain)}</div>", unsafe_allow_html=True)
        with st.expander("Tool calls and the rows they returned"):
            for step in steps:
                st.markdown(f"**{step['tool']}** `{step['arguments']}`")
                try:
                    st.dataframe(pd.DataFrame(json.loads(step["output"] or "{}").get("rows", [])), hide_index=True)
                except (ValueError, TypeError):
                    st.code(str(step["output"])[:1500])
    st.markdown(result.get("answer") or "")


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
    """Custom instructions sent with one request (custom_inputs) to steer the same deployed agent."""
    left, right = st.columns([1, 2])
    preset = left.selectbox("Custom instructions", list(PRESETS), key=f"{key}_preset",
                            help="Sent as custom_inputs; the agent appends them to its instructions for this call.")
    text = right.text_area("Instructions sent to the agent", value=PRESETS[preset], key=f"{key}_{preset}",
                           height=68, placeholder="Optional: add your own instructions for this request")
    return text.strip()
