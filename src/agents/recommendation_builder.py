"""Assemble recommendations from tool facts plus (optional) model narrative, enforcing guardrails.

The model may choose among allowed actions and write narrative. Conditions, score, priority, escalation,
allowed actions, dates, event drafts, and validation always come from deterministic tools.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from src.tools.executor import ToolExecutor

MANDATORY_TOOLS = [
    "get_loan_context", "get_current_milestone", "check_milestone_completion", "check_followup_status",
    "check_pending_action", "check_previous_rejection", "get_assigned_party", "calculate_escalation_state",
    "calculate_loan_attention_score", "get_allowed_actions",
]
CONFIDENCE_ORDER = ["LOW", "MEDIUM", "HIGH"]
MEDIUM_CAP_CONDITIONS = {"DATA_EXCEPTION", "DUPLICATE_RISK", "VERIFICATION_FAILURE"}
CONTACT_ACTIONS = {"CONTACT_ATTORNEY", "CONTACT_SERVICING_VENDOR"}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def new_recommendation_id() -> str:
    return f"REC-{datetime.now(timezone.utc):%Y%m%d}-{uuid.uuid4().hex[:8].upper()}"


def ensure_mandatory(executor: ToolExecutor, loan_id: str) -> list[str]:
    failed = []
    for name in MANDATORY_TOOLS:
        if name not in executor.results:
            res = executor.call(name, {"loan_id": loan_id}, origin="guardrail")
            if not res["success"]:
                failed.append(f"{name}: {res['error']}")
    return failed


def _ev(source_type: str, identifier: str, description: str, value) -> dict:
    return {"source_type": source_type, "source_identifier": identifier, "description": description,
            "value": value, "observed_at": now_iso()}


def build_evidence(executor: ToolExecutor, state: dict) -> list[dict]:
    r = executor.results
    evidence = []
    for cond in state.get("raw_conditions", []):
        evidence.append(_ev("RULE", cond["rule_id"], f"Condition {cond['code']}", cond["detail"]))
    cm = r.get("get_current_milestone") or {}
    if cm.get("has_servicing_track"):
        evidence.append(_ev("EVENT", cm.get("event_id") or "", "Current milestone",
                            f"{cm.get('milestone_type')} ({cm.get('status')}) opened {cm.get('event_date')}"))
    fu = r.get("check_followup_status") or {}
    if fu.get("effective_followup_date"):
        evidence.append(_ev("TOOL", "check_followup_status", "Effective follow-up date",
                            f"{fu['effective_followup_date']} (days to follow-up {fu.get('days_to_followup')}, "
                            f"days overdue {fu.get('days_overdue')})"))
    sc = r.get("calculate_loan_attention_score") or {}
    if sc:
        evidence.append(_ev("TOOL", "calculate_loan_attention_score", "Attention score",
                            f"{sc.get('score')} ({sc.get('priority')})"))
    es = r.get("calculate_escalation_state") or {}
    if es:
        evidence.append(_ev("TOOL", "calculate_escalation_state", "Escalation state",
                            f"{es.get('escalation_state')} -> {es.get('required_role')}"))
    pa = r.get("check_pending_action") or {}
    if pa.get("has_pending"):
        evidence.append(_ev("ACTION", pa["pending_actions"][0]["action_id"], "Pending approved action",
                            pa["pending_actions"][0]["action_type"]))
    rj = r.get("check_previous_rejection") or {}
    if rj.get("rejected_actions_in_lookback"):
        evidence.append(_ev("DECISION", "check_previous_rejection", "Rejected inside lookback",
                            ", ".join(rj["rejected_actions_in_lookback"])))
    ap = r.get("get_assigned_party") or {}
    if ap and ap.get("required_party_type"):
        evidence.append(_ev("TOOL", "get_assigned_party", "Required party present",
                            f"{ap['required_party_type']}: {'yes' if ap.get('party_ok') else 'no'}"))
    if state.get("latest_verification_status"):
        evidence.append(_ev("ACTION", state.get("latest_action_id") or "", "Latest action verification",
                            state["latest_verification_status"]))
    return evidence


def deterministic_missing_information(state: dict, executor: ToolExecutor) -> list[str]:
    missing = []
    for cond in state.get("raw_conditions", []):
        rid = cond["rule_id"]
        if rid == "RULE-DATA-001":
            missing.append(f"Active milestone rule for {state.get('current_milestone')}")
        elif rid == "RULE-DATA-002":
            missing.append("Corrected milestone completion/event dates")
        elif rid == "RULE-DATA-003":
            missing.append("Active assigned party of the required type")
        elif rid == "RULE-DATA-004":
            missing.append("Active assigned servicing specialist")
        elif rid == "RULE-FOLLOWUP-002":
            missing.append("Follow-up date for the current milestone")
        elif rid == "RULE-VERIFICATION-001":
            missing.append("Confirmation from the servicing system that the approved event exists")
    return missing


def template_narrative(state: dict, action: str, draft: dict) -> dict:
    primary = state["primary_condition"]
    details = "; ".join(c["detail"] for c in state["raw_conditions"] if c["code"] == primary) or primary
    milestone = state.get("current_milestone") or "no active milestone"
    rationale = (f"Rule facts: {details}. Attention score {state['attention_score']} ({state['priority']}) driven by "
                 f"{state['top_drivers_text'] or 'no drivers'}. Escalation is {state['escalation_state']}. "
                 f"{action} is the first allowed action for {primary} under the synthetic action catalog.")
    if action == "NO_ACTION":
        note = f"Synthetic note: no new action proposed; {primary.lower().replace('_', ' ')} on {milestone}."
    else:
        fu = draft.get("followup_date")
        note = f"Synthetic note: {action} proposed for {milestone}" + (f"; follow-up {fu}." if fu else ".")
    outreach = ""
    if action in CONTACT_ACTIONS:
        outreach = (f"Hello {state.get('party_name') or 'assigned party'}, please share a status update on the "
                    f"{milestone} step for loan {state['loan_id']}. The current follow-up date is "
                    f"{state.get('effective_followup_date') or 'not set'}. Thank you.")
    return {"rationale": rationale, "suggested_note": note, "suggested_outreach": outreach}


def build_recommendation(executor: ToolExecutor, loan_id: str, state: dict, settings, agent_mode: str, run_id: str,
                         choice: dict | None = None, fallback_reason: str | None = None) -> dict:
    """Merge deterministic tool facts and optional model choice into a Recommendation dict."""
    failed = ensure_mandatory(executor, loan_id)
    r = executor.results
    uncertainty_notes: list[str] = []
    if fallback_reason:
        uncertainty_notes.append(f"LLM unavailable; deterministic analysis used ({fallback_reason}).")

    allowed_info = r.get("get_allowed_actions") or {"allowed_actions": ["NO_ACTION"], "default_action": "NO_ACTION"}
    allowed = allowed_info["allowed_actions"]
    default_action = allowed_info["default_action"]
    chosen = (choice or {}).get("recommended_action") or default_action
    chosen = str(chosen).strip().upper()
    overridden = False
    if chosen not in allowed:
        uncertainty_notes.append(f"Model proposed {chosen}, which is not allowed; replaced with deterministic "
                                 f"default {default_action}.")
        chosen, overridden = default_action, True

    status = "PENDING_REVIEW"
    if failed:
        status = "FAILED"
        chosen = "NO_ACTION"
        uncertainty_notes.append("Mandatory tool failure; no action proposed. Route to specialist review.")

    narrative_seed = template_narrative(state, chosen, {})
    note = (choice or {}).get("suggested_note") if choice and not overridden else None
    outreach = (choice or {}).get("suggested_outreach") if choice and not overridden else None
    if chosen == "ESCALATE_TO_SPECIALIST":
        draft = executor.call("prepare_escalation", {"loan_id": loan_id, "reason": note or None})
    else:
        draft = executor.call("prepare_followup_event", {"loan_id": loan_id, "action_type": chosen,
                                                         "note": note or narrative_seed["suggested_note"],
                                                         "outreach": outreach or narrative_seed["suggested_outreach"]})
    draft_data = draft["data"] or {}
    if draft_data.get("creates_event"):
        executor.call("check_existing_event", {"loan_id": loan_id, "event_type": draft_data["event_type"],
                                               "milestone_type": draft_data.get("milestone_type"),
                                               "action_type": chosen})
    validation = executor.call("validate_proposed_event", {
        "loan_id": loan_id, "action_type": chosen, "event_type": draft_data.get("event_type"),
        "followup_date": draft_data.get("followup_date"), "note": draft_data.get("event_note"),
    })
    validation_data = validation["data"] or {"valid": False, "errors": [{"code": "TOOL_ERROR",
                                                                         "message": validation["error"]}]}
    template = template_narrative(state, chosen, draft_data)

    # Confidence: model value bounded by deterministic caps.
    cap = "HIGH"
    if state["primary_condition"] in MEDIUM_CAP_CONDITIONS:
        cap = "MEDIUM"
    if fallback_reason or overridden or not validation_data.get("valid", False) or failed:
        cap = "LOW" if (overridden or failed or not validation_data.get("valid", False)) else "MEDIUM"
    model_conf = str((choice or {}).get("confidence") or "HIGH").upper()
    if model_conf not in CONFIDENCE_ORDER:
        model_conf = "MEDIUM"
    confidence = CONFIDENCE_ORDER[min(CONFIDENCE_ORDER.index(model_conf), CONFIDENCE_ORDER.index(cap))]
    if not validation_data.get("valid", False):
        codes = ", ".join(e["code"] for e in validation_data.get("errors", []))
        uncertainty_notes.append(f"Proposed event failed validation ({codes}); reviewer must edit or reject.")

    missing = deterministic_missing_information(state, executor)
    for item in (choice or {}).get("missing_information") or []:
        if item and item not in missing:
            missing.append(str(item)[:200])
    model_uncertainty = (choice or {}).get("uncertainty")
    uncertainty = " ".join(([model_uncertainty] if model_uncertainty and not overridden else []) + uncertainty_notes)

    sc = r.get("calculate_loan_attention_score") or {}
    es = r.get("calculate_escalation_state") or {}
    rec = {
        "recommendation_id": new_recommendation_id(),
        "loan_id": loan_id,
        "primary_condition": state["primary_condition"],
        "secondary_conditions": state["secondary_conditions"],
        "attention_score": int(sc.get("score", state["attention_score"])),
        "priority": sc.get("priority", state["priority"]),
        "score_drivers": sc.get("score_drivers", state["score_drivers"]),
        "recommended_action": chosen,
        "recommended_event_type": draft_data.get("event_type"),
        "recommended_followup_date": draft_data.get("followup_date"),
        "suggested_note": draft_data.get("event_note") or template["suggested_note"],
        "suggested_outreach": draft_data.get("outreach_text") or "",
        "rationale": ((choice or {}).get("rationale") if choice and not overridden else None) or template["rationale"],
        "evidence": build_evidence(executor, state),
        "confidence": confidence,
        "uncertainty": uncertainty or "None material; all facts came from deterministic tools.",
        "missing_information": missing,
        "tool_calls": executor.records,
        "created_at": now_iso(),
        "agent_version": f"{settings.agent_version}-{agent_mode}",
        "rule_version": settings.rule_version,
        "scoring_version": settings.scoring_version,
        "status": status,
        "requires_human_approval": True,
        "allowed_actions": allowed,
        "escalation_state": es.get("escalation_state", state["escalation_state"]),
        "state_fingerprint": state["state_fingerprint"],
        "proposed_event": draft_data,
        "validation": validation_data,
        "agent_mode": agent_mode,
        "run_id": run_id,
        "synthetic_data": True,
    }
    if (choice or {}).get("evidence_refs"):
        rec["evidence"].append(_ev("TOOL", "submit_recommendation", "Tools cited by the agent",
                                   ", ".join(map(str, choice["evidence_refs"]))[:300]))
    return rec
