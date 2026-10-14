"""Shared UI building blocks for the Streamlit pages."""
from __future__ import annotations

import html
import math
from datetime import date
from functools import lru_cache

import pandas as pd
import streamlit as st
import yaml

from app.client import ApiError, get_client, open_loan, reviewer
from src.config import repo_root


# ====================================================================================================
# Shared styles, color tokens, and badge helpers
# ====================================================================================================

PRIORITY_COLORS = {"CRITICAL": "#B42318", "HIGH": "#C4560C", "MEDIUM": "#A16207", "LOW": "#475467"}
HEALTH_COLORS = {"Healthy": "#067647", "Watch": "#175CD3", "Action Required": "#B54708", "Critical": "#B42318"}
STATE_COLORS = {
    "COMPLETED": "#6C8F7D", "CURRENT": "#175CD3", "UPCOMING": "#0E7490", "SCHEDULED": "#475467",
    "DUE": "#B54708", "OVERDUE": "#B42318", "PROPOSED": "#6941C6", "APPROVED": "#027A48", "SUBMITTED": "#3E4784",
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
.lsi-title {font-size:1.35rem; font-weight:700; margin-bottom:0;}
.lsi-subtitle {color:#667085; margin-top:0; font-size:0.85rem;}
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
.lsi-talk {border:1px dashed #C4560C; background:rgba(253,233,215,0.45); padding:8px 14px; border-radius:8px;
           margin:4px 0 12px 0; font-size:0.9rem;}
.lsi-talk ul {margin:4px 0 0 0;}
.lsi-why {color:#475467; font-size:0.85rem;}
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


# ====================================================================================================
# Presenter talk-track notes (config/demo_story.yml), shown when presenter notes are on
# ====================================================================================================

@lru_cache(maxsize=1)
def story() -> dict:
    with open(repo_root() / "config" / "demo_story.yml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def presenter_on() -> bool:
    return st.session_state.get("presenter_notes", True)


def notes(page_key: str) -> None:
    """Small talk-track callout for a page."""
    if not presenter_on():
        return
    page = story().get("page_notes", {}).get(page_key, {})
    lines, platform = page.get("story", []), page.get("databricks", [])
    if lines or platform:
        items = "".join(f"<li>{esc(line)}</li>" for line in lines)
        plat = "".join(f"<li>{esc(line)}</li>" for line in platform)
        st.markdown(f'<div class="lsi-talk"><b>Talk track</b><ul>{items}</ul>'
                    + (f'<b>On Databricks</b><ul>{plat}</ul>' if plat else "") + "</div>", unsafe_allow_html=True)


def chapter_note(chapter: dict) -> None:
    story_lines = "".join(f"<li>{esc(s)}</li>" for s in chapter.get("say", []))
    platform = "".join(f"<li>{esc(s)}</li>" for s in chapter.get("databricks", []))
    platform_block = (f'<div style="margin-top:6px"><b>On Databricks</b><ul>{platform}</ul></div>'
                      if platform else "")
    st.markdown(f'<div class="lsi-talk"><b>The story</b><ul>{story_lines}</ul>{platform_block}'
                f'<div style="margin-top:4px"><b>Do:</b> {esc(chapter.get("click", ""))}</div></div>',
                unsafe_allow_html=True)


def active_chapter_banner(page_key: str) -> None:
    """If the presenter launched a chapter for this page, show its notes at the top."""
    if not presenter_on():
        return
    chapter_id = st.session_state.get("story_chapter")
    chapter = next((c for c in story()["story"]["chapters"] if c["id"] == chapter_id), None)
    if chapter and chapter["page"] == page_key:
        chapters = story()["story"]["chapters"]
        idx = chapters.index(chapter)
        with st.container(border=True):
            st.markdown(f"**Chapter {idx + 1} of {len(chapters)} · {chapter['title']}** — {chapter['goal']}")
            chapter_note(chapter)
            if idx + 1 < len(chapters):
                nxt = chapters[idx + 1]
                if st.button(f"Next chapter: {nxt['title']} →", key=f"next_{chapter_id}"):
                    go_to_chapter(nxt)


def go_to_chapter(chapter: dict) -> None:
    from app.navigation import PAGES

    st.session_state["story_chapter"] = chapter["id"]
    if chapter.get("loan_id"):
        st.session_state["selected_loan_id"] = chapter["loan_id"]
    st.switch_page(PAGES[chapter["page"]])


# ====================================================================================================
# KPI cards (computed from GET /api/portfolio/summary)
# ====================================================================================================

KPIS = [
    ("active_loans", "Active loans", None),
    ("need_attention", "Need attention", "#B54708"),
    ("critical", "Critical", "#B42318"),
    ("recommendations_awaiting_approval", "Awaiting approval", "#6941C6"),
    ("verification_failures", "Failed verification", "#7A271A"),
]


def kpi_cards(summary: dict) -> None:
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


# ====================================================================================================
# Interactive portfolio-health segments
# ====================================================================================================

def health_segments(summary: dict, key: str = "health_segment") -> str | None:
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


# ====================================================================================================
# Loan lists where clicking the loan ID opens Loan 360
# ====================================================================================================

STATUS_LABEL = {"NOT_ANALYZED": "Not analyzed", "AWAITING_APPROVAL": "Awaiting approval", "APPROVED": "Approved",
                "SUBMITTED": "Submitted", "REJECTED": "Rejected", "DEFERRED": "Deferred", "ESCALATED": "Escalated",
                "VERIFIED": "Verified", "VERIFICATION_FAILED": "Failed verification", "AGENT_FAILED": "Agent failed"}


def nice(code) -> str:
    return str(code or "").replace("_", " ").title()


def _cell(row: dict, col: str) -> str:
    if col == "priority":
        color = PRIORITY_COLORS.get(row["priority"], "#475467")
        return f'<span style="color:{color}; font-weight:700">{nice(row["priority"])}</span>'
    if col == "condition":
        return esc(nice(row["primary_condition"]))
    if col == "score":
        return f'<b>{row["attention_score"]}</b>'
    if col == "why":
        return f'<span class="lsi-why">{esc(row.get("top_drivers_text"))}</span>'
    if col == "suggests":
        source = "AI agent" if row.get("recommendation_source") == "llm" else "Rules baseline"
        action = nice(row.get("recommended_action"))
        return f'{esc(action)}<br><span class="lsi-why">{source}</span>' if action else "-"
    if col == "status":
        return esc(STATUS_LABEL.get(row.get("review_status"), nice(row.get("review_status"))))
    if col == "borrower":
        return esc(row.get("borrower_display_name"))
    if col == "state":
        return esc(row.get("property_state"))
    if col == "balance":
        return f"${float(row.get('current_balance') or 0):,.0f}"
    if col == "milestone":
        return esc(nice(row.get("current_milestone")) or "-")
    if col == "followup":
        return esc(row.get("effective_followup_date") or "-")
    if col == "health":
        color = HEALTH_COLORS.get(row.get("health_segment"), "#475467")
        return f'<span style="color:{color}">{esc(row.get("health_segment"))}</span>'
    if col == "agent_status":
        return esc(STATUS_LABEL.get(row.get("agent_status"), nice(row.get("agent_status"))))
    return esc(row.get(col))


HEADERS = {"priority": "Priority", "loan": "Loan", "borrower": "Borrower", "condition": "Condition", "score": "Score",
           "why": "Why it's here", "suggests": "Agent suggests", "status": "Status",
           "state": "State", "balance": "Balance", "milestone": "Milestone", "followup": "Next follow-up",
           "health": "Health", "agent_status": "Agent status"}
WIDTHS = {"priority": 1.0, "loan": 1.4, "borrower": 1.6, "condition": 1.5, "score": 0.7, "why": 3.6,
          "suggests": 1.8, "status": 1.3, "state": 0.6, "balance": 1.1,
          "milestone": 1.7, "followup": 1.2, "health": 1.3, "agent_status": 1.4}
COMPACT = ["priority", "loan", "condition", "score", "why", "suggests"]
STANDARD = ["priority", "loan", "borrower", "condition", "score", "why", "suggests", "status"]
PORTFOLIO = ["loan", "borrower", "state", "balance", "milestone", "followup", "health", "score", "priority",
             "agent_status"]


def loan_list(rows: list[dict], key: str, compact: bool = False, page_size: int = 12,
           columns: list[str] | None = None) -> None:
    if not rows:
        st.info("No loans match the current filters.")
        return
    columns = columns or (COMPACT if compact else STANDARD)
    pages = max(1, math.ceil(len(rows) / page_size))
    page = st.session_state.get(f"{key}_page", 1)
    page = min(max(page, 1), pages)
    widths = [WIDTHS[c] for c in columns]
    header = st.columns(widths)
    for col, name in zip(header, columns):
        col.markdown(f"<span style='color:#667085; font-size:0.8rem; font-weight:600'>{HEADERS[name]}</span>",
                     unsafe_allow_html=True)
    for i, row in enumerate(rows[(page - 1) * page_size: page * page_size]):
        cells = st.columns(widths, vertical_alignment="center")
        for col, name in zip(cells, columns):
            if name == "loan":
                if col.button(row["loan_id"], key=f"{key}_{row['loan_id']}_{i}", type="tertiary",
                              help="Open in Loan 360"):
                    open_loan(row["loan_id"])
            else:
                col.markdown(_cell(row, name), unsafe_allow_html=True)
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


# ====================================================================================================
# Chronological servicing-event timeline with state styling
# ====================================================================================================

def timeline(events: list[dict]) -> None:
    if not events:
        st.info("No servicing events.")
        return
    names = {"SUBMITTED": "SCHEDULED"}
    legend = " ".join(badge(names.get(s, s), STATE_COLORS[s]) for s in (
        "COMPLETED", "CURRENT", "UPCOMING", "DUE", "OVERDUE", "PROPOSED", "APPROVED", "SUBMITTED", "FAILED",
        "VERIFIED"))
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
        label = {"SUBMITTED": "SCHEDULED - AWAITING VERIFICATION", "PROPOSED": "PROPOSED - NEEDS YOUR CONFIRMATION",
                 "APPROVED": "APPROVED - NOT YET SENT"}.get(state, state)
        title = f"<b>{esc(ev.get('event_type'))}</b>"
        if ev.get("milestone_type"):
            title += f" · {esc(ev['milestone_type'])}"
        items.append(
            f'<div class="lsi-tl-item"><div class="lsi-tl-dot" style="{dashed}"></div>'
            f'{title} {badge(label, color)}<div class="lsi-tl-meta">{dates} · {esc(ev.get("status"))} · '
            f'{esc(ev.get("source"))} · {esc(ev.get("event_id"))}</div>'
            f'<div style="font-size:0.88rem">{esc(ev.get("event_note"))}</div></div>')
    st.markdown(f'<div class="lsi-tl">{"".join(items)}</div>', unsafe_allow_html=True)


# ====================================================================================================
# Agent activity trace: step chain and tool-call table (summaries only; no prompts or reasoning)
# ====================================================================================================

FLOW = [
    ("candidate_detected", "Candidate detected", ("candidate_detected",)),
    ("context", "Context retrieved", ("get_loan_context",)),
    ("milestone", "Milestone checked", ("get_current_milestone", "check_milestone_completion")),
    ("events", "Events retrieved", ("get_event_history", "check_followup_status")),
    ("duplicates", "Duplicates checked", ("check_existing_event",)),
    ("rule", "Rule retrieved", ("get_milestone_rule", "get_allowed_actions")),
    ("pending", "Pending action checked", ("check_pending_action",)),
    ("score", "Score calculated", ("calculate_loan_attention_score",)),
    ("allowed", "Allowed actions retrieved", ("get_allowed_actions", "calculate_escalation_state")),
    ("recommendation", "Recommendation generated", ("recommendation_generated",)),
    ("approval", "Awaiting approval", ("awaiting_approval",)),
]


def activity_flow(records: list[dict]) -> None:
    seen = {r.get("tool_name") or r.get("step") for r in records}
    parts = []
    for _, label, keys in FLOW:
        done = any(k in seen for k in keys)
        parts.append(f'<span class="lsi-step {"done" if done else "miss"}">{label}</span>')
    st.markdown('<div class="lsi-flow">' + " → ".join(parts) + "</div>", unsafe_allow_html=True)


def activity_table(records: list[dict], height: int = 400) -> None:
    if not records:
        st.info("No activity recorded yet.")
        return
    df = pd.DataFrame(records)
    cols = {"created_at": "Timestamp", "run_id": "Run", "loan_id": "Loan", "actor": "Actor", "step": "Step",
            "tool_name": "Tool", "input_summary": "Input (summary)", "output_summary": "Output (summary)",
            "duration_ms": "ms", "success": "OK"}
    df = df[[c for c in cols if c in df.columns]].rename(columns=cols)
    st.dataframe(df, hide_index=True, use_container_width=True, height=height)


# ====================================================================================================
# Agent proposal panel: recommendation, drafts, uncertainty; details in expanders
# ====================================================================================================

def agent_proposal(rec: dict | None, state: dict) -> None:
    if not rec:
        st.info("No agent proposal yet. Click **Run agent analysis** to let the agent investigate this loan.")
        return
    mode = "LLM agent" if rec.get("agent_mode") == "llm" else "Deterministic agent"
    status_color = {"PENDING_REVIEW": "#6941C6", "APPROVED": "#067647", "REJECTED": "#B42318"}.get(rec["status"])
    follow = (f" · follow-up <b>{esc(rec.get('recommended_followup_date'))}</b>"
              if rec.get("recommended_followup_date") else "")
    st.markdown(
        f'<div class="lsi-ai"><b>Agent proposal</b> <span style="color:#667085">({mode})</span> '
        f'{badge(nice(rec["status"]), status_color)}'
        f'<div style="font-size:1.25rem; margin:6px 0"><b>{esc(nice(rec["recommended_action"]))}</b>{follow} '
        f'&nbsp; {badge("Confidence " + rec["confidence"].title(), "#344054")}</div>'
        f'{esc(rec.get("rationale"))}</div>', unsafe_allow_html=True)

    left, right = st.columns(2)
    with left:
        st.markdown("**Draft servicing note**")
        st.caption(rec.get("suggested_note") or "—")
    with right:
        if rec.get("suggested_outreach"):
            st.markdown("**Draft outreach**")
            st.caption(rec["suggested_outreach"])
    st.markdown(f'<div class="lsi-why"><b>Uncertainty:</b> {esc(rec.get("uncertainty") or "—")}'
                f'<br><b>Missing information:</b> {esc(", ".join(rec.get("missing_information") or []) or "none")}'
                f'</div>', unsafe_allow_html=True)
    validation = rec.get("validation") or {}
    if validation and not validation.get("valid"):
        st.error("Validation: " + "; ".join(f"{e['code']}: {e['message']}" for e in validation.get("errors", [])))

    e1, e2, e3 = st.columns(3)
    with e1.popover(f"Evidence ({len(rec.get('evidence') or [])})", use_container_width=True):
        ev = pd.DataFrame(rec.get("evidence") or [])
        if not ev.empty:
            st.dataframe(ev[["source_type", "source_identifier", "description", "value"]], hide_index=True)
    with e2.popover(f"Tool calls ({len(rec.get('tool_calls') or [])})", use_container_width=True):
        tc = pd.DataFrame(rec.get("tool_calls") or [])
        if not tc.empty:
            st.dataframe(tc[[c for c in ("tool_name", "origin", "success", "duration_ms") if c in tc.columns]],
                         hide_index=True)
    with e3.popover("Allowed actions", use_container_width=True):
        st.write(", ".join(nice(a) for a in state["allowed_actions"]))
        st.caption("The agent can only choose from this list (RULE-ACTIONS-001).")


# ====================================================================================================
# Review controls: Approve, Edit, Reject, Defer, Escalate; then submit via adapter and verify
# ====================================================================================================

ROLES = ["SENIOR_SPECIALIST", "SERVICING_MANAGER"]


def _decide(rec: dict, decision: str, reason: str = "", comment: str = "", edits: dict | None = None) -> None:
    rid, role = reviewer()
    body = {"decision": decision, "reviewer_id": rid, "reviewer_role": role, "reason": reason, "comment": comment,
            "edits": edits}
    try:
        res = get_client().decide(rec["recommendation_id"], body)
        action = res.get("action")
        st.session_state["flash"] = f"{decision} recorded" + (f"; action {action['action_id']} created" if action else "")
        if action:
            st.session_state["last_action_id"] = action["action_id"]
    except ApiError as exc:
        detail = exc.detail
        if isinstance(detail, dict) and detail.get("errors"):
            st.session_state["review_error"] = "; ".join(f"{e['code']}: {e['message']}" for e in detail["errors"])
        else:
            st.session_state["review_error"] = str(detail)
    st.rerun()


def review_panel(rec: dict | None, state: dict) -> None:
    error = st.session_state.pop("review_error", None)
    if error:
        st.error(f"Not approved — revalidation failed: {error}")
    if not rec or rec.get("status") != "PENDING_REVIEW":
        return
    st.markdown("#### Your decision")
    st.caption("Nothing is sent until you approve. Approval re-checks the proposal before an outbound event is created.")
    tabs = st.tabs(["Approve", "Edit", "Reject", "Defer", "Escalate"])
    with tabs[0]:
        if st.button(f"Approve {rec['recommended_action']}", type="primary", key="approve",
                     disabled=rec.get("status") != "PENDING_REVIEW"):
            _decide(rec, "APPROVE", reason="Approved as recommended")
    with tabs[1]:
        with st.form("edit_form"):
            allowed = state["allowed_actions"]
            idx = allowed.index(rec["recommended_action"]) if rec["recommended_action"] in allowed else 0
            action = st.selectbox("Action (allowed only)", allowed, index=idx)
            default_fu = rec.get("recommended_followup_date")
            fu = st.date_input("Follow-up date", value=date.fromisoformat(default_fu) if default_fu else None)
            note = st.text_area("Note", value=rec.get("suggested_note") or "", max_chars=1000)
            outreach = st.text_area("Outreach draft", value=rec.get("suggested_outreach") or "")
            reason = st.text_input("Reason for edit", value="Adjusted by specialist")
            if st.form_submit_button("Approve with edits", type="primary"):
                _decide(rec, "EDIT", reason=reason, edits={
                    "action_type": action, "followup_date": fu.isoformat() if fu else None, "note": note,
                    "outreach": outreach})
    with tabs[2]:
        with st.form("reject_form"):
            reason = st.text_input("Reason (required)")
            if st.form_submit_button("Reject"):
                if not reason.strip():
                    st.session_state["review_error"] = "A reason is required to reject."
                    st.rerun()
                _decide(rec, "REJECT", reason=reason)
    with tabs[3]:
        with st.form("defer_form"):
            reason = st.text_input("Reason", value="Awaiting additional information")
            if st.form_submit_button("Defer"):
                _decide(rec, "DEFER", reason=reason)
    with tabs[4]:
        with st.form("escalate_form"):
            target = st.selectbox("Escalate to", ROLES, index=1 if state["escalation_state"] == "CRITICAL" else 0)
            reason = st.text_input("Reason", value=f"{state['primary_condition']} requires senior review")
            if st.form_submit_button("Escalate"):
                _decide(rec, "ESCALATE", reason=reason, edits={"escalation_target": target})


def approved_actions(detail: dict) -> None:
    """Outbound events for approved actions, adapter submission, and verification."""
    actions = detail.get("actions") or []
    if not actions:
        return
    client = get_client()
    st.markdown("#### Approved actions")
    for action in actions:
        full = client.action(action["action_id"])
        v = (full.get("verification") or {}).get("verification_status")
        st.markdown(f"**{action['action_id']}** · {action['action_type']} → {action['event_type']} "
                    f"(follow-up {action.get('followup_date') or '—'}) &nbsp; {badge(action['status'], '#344054')} "
                    f"&nbsp; verification {badge(v)}", unsafe_allow_html=True)
        c1, c2, c3 = st.columns([1, 1, 3])
        if action["status"] == "APPROVED":
            if c1.button("Submit via synthetic adapter", key=f"submit_{action['action_id']}", type="primary",
                         icon=":material/send:"):
                res = client.submit(action["action_id"])
                st.session_state["flash"] = (f"{res['status']}: {res['adapter_result'].get('message')}")
                st.rerun()
        if action["status"] in ("SUBMITTED", "VERIFICATION_FAILED", "FAILED"):
            if c2.button("Refresh source & verify", key=f"refresh_{action['action_id']}", icon=":material/sync:"):
                res = client.refresh()
                st.session_state["flash"] = f"Cycle {res['refresh_cycle']}: {res['verification'] or 'nothing to verify'}"
                st.rerun()
        if full.get("adapter_result"):
            c3.caption(f"Adapter: {full['adapter_result'].get('mode')} — {full['adapter_result'].get('message')}")
        diffs = (full.get("verification") or {}).get("differences")
        if diffs:
            st.warning("Differences: " + "; ".join(f"{d['field']}: approved {d['approved']} vs actual {d['actual']}"
                                                    for d in diffs))
        with st.expander("Outbound servicing event (synthetic, loan-servicing-system-compatible)"):
            st.json(full.get("outbound_payload") or {})


# ====================================================================================================
# Proposed event panel: confirm and schedule an agent-proposed event, with light edits (human in the loop)
# ====================================================================================================

def _confirm(rec: dict, followup: date | None, note: str, outreach: str, send_now: bool) -> None:
    client = get_client()
    rid, role = reviewer()
    original_fu = rec.get("recommended_followup_date")
    new_fu = followup.isoformat() if followup else None
    edited = (new_fu != original_fu or note.strip() != (rec.get("suggested_note") or "").strip()
              or outreach.strip() != (rec.get("suggested_outreach") or "").strip())
    body = {"decision": "EDIT" if edited else "APPROVE", "reviewer_id": rid, "reviewer_role": role,
            "reason": "Confirmed from timeline" + (" with edits" if edited else ""),
            "edits": {"followup_date": new_fu, "note": note, "outreach": outreach} if edited else None}
    try:
        result = client.decide(rec["recommendation_id"], body)
    except ApiError as exc:
        detail = exc.detail
        if isinstance(detail, dict) and detail.get("errors"):
            detail = "; ".join(f"{e['code']}: {e['message']}" for e in detail["errors"])
        st.session_state["proposal_error"] = f"Not scheduled - the proposal failed re-validation: {detail}"
        return
    action = result.get("action")
    if not action:
        st.session_state["flash"] = "Decision recorded (no event required)."
        return
    if send_now:
        submitted = client.submit(action["action_id"])
        if submitted["status"] == "SUBMITTED":
            st.session_state["flash"] = (f"Scheduled: {nice(action['event_type'])} on {action.get('followup_date')}"
                                         " - sent to the servicing system, awaiting verification.")
        else:
            st.session_state["flash"] = f"Servicing system rejected the event: {submitted.get('failure_reason')}"
    else:
        st.session_state["flash"] = "Approved - ready to send from the Agent & decision tab."


def _dismiss(rec: dict, reason: str) -> None:
    rid, role = reviewer()
    try:
        get_client().decide(rec["recommendation_id"], {"decision": "REJECT", "reviewer_id": rid,
                                                       "reviewer_role": role, "reason": reason})
        st.session_state["flash"] = "Proposal dismissed and recorded."
    except ApiError as exc:
        st.session_state["proposal_error"] = f"Could not dismiss: {exc.detail}"


def proposed_event_panel(rec: dict | None) -> None:
    error = st.session_state.pop("proposal_error", None)
    if error:
        st.error(error)
    if not rec or rec.get("status") != "PENDING_REVIEW":
        return
    event = rec.get("proposed_event") or {}
    if not event.get("creates_event"):
        return
    with st.container(border=True):
        source = "AI agent" if rec.get("agent_mode") == "llm" else "Rules baseline"
        st.markdown(f"**Proposed event** {badge('Proposed', '#6941C6')} "
                    f"<span style='color:#667085'>({source}, confidence {esc(rec.get('confidence', '').title())})"
                    f"</span><br><span style='font-size:1.1rem'><b>{esc(nice(rec['recommended_action']))}</b> - "
                    f"{esc(nice(event.get('event_type')))} for {esc(nice(event.get('milestone_type')) or 'the loan')}"
                    f"</span><br><span class='lsi-why'>{esc(rec.get('rationale'))}</span>", unsafe_allow_html=True)
        with st.form(f"proposal_{rec['recommendation_id']}", border=False):
            c1, c2 = st.columns([1, 3])
            default_fu = rec.get("recommended_followup_date")
            followup = c1.date_input("Follow-up date", value=date.fromisoformat(default_fu) if default_fu else None,
                                     min_value=date.fromisoformat(event["event_date"]))
            send_now = c1.checkbox("Send to servicing system now", value=True)
            note = c2.text_area("Servicing note", value=rec.get("suggested_note") or "", height=80, max_chars=1000)
            outreach = c2.text_area("Outreach message", value=rec.get("suggested_outreach") or "", height=80,
                                    disabled=not rec.get("suggested_outreach"))
            b1, b2, b3 = st.columns([1.3, 1, 2])
            confirm = b1.form_submit_button("Confirm and schedule", type="primary", icon=":material/event_available:")
            dismiss = b2.form_submit_button("Dismiss", icon=":material/close:")
            reason = b3.text_input("Reason (for dismiss)", value="Not needed", label_visibility="collapsed")
        st.caption("Your confirmation is recorded with your name and any edits. The proposal is re-checked before "
                   "anything is sent; nothing is scheduled without this step.")
        if confirm:
            _confirm(rec, followup, note, outreach or "", send_now)
            st.rerun()
        if dismiss:
            _dismiss(rec, reason or "Dismissed from timeline")
            st.rerun()
