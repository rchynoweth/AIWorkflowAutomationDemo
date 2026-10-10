"""Deterministic servicing-condition detection (see docs/BUSINESS_RULES.md)."""
from __future__ import annotations

from datetime import timedelta

from src.rules.facts import EngineContext, LoanFacts
from src.verification.verifier import FAILURE_STATUSES, _as_ts


def _cond(code: str, rule_id: str, detail: str) -> dict:
    return {"code": code, "rule_id": rule_id, "detail": detail}


def detect_raw_conditions(facts: LoanFacts, ctx: EngineContext) -> list[dict]:
    th = ctx.thresholds
    raw: list[dict] = []
    P = ctx.processing_date

    # Verification and pending actions (apply with or without a servicing track).
    latest_v = facts.latest_verification
    if latest_v and latest_v["verification_status"] in FAILURE_STATUSES:
        raw.append(_cond("VERIFICATION_FAILURE", "RULE-VERIFICATION-001",
                         f"Action {latest_v['action_id']} verification {latest_v['verification_status']}: "
                         f"{latest_v['detail']}"))
    if facts.pending_action:
        raw.append(_cond("PENDING_ACTION", "RULE-PENDING-001",
                         f"Action {facts.pending_action['action_id']} ({facts.pending_action['action_type']}) "
                         "awaiting verification."))

    # Deferred recommendation awaiting review.
    latest_d = facts.latest_decision
    if latest_d and latest_d.get("decision") == "DEFER":
        decided = _as_ts(latest_d.get("decided_at"))
        if decided and decided.date() >= P - timedelta(days=int(th.get("deferral_lookback_days", 14))):
            raw.append(_cond("PENDING_REVIEW", "RULE-PENDING-003",
                             f"Recommendation {latest_d['recommendation_id']} deferred on {decided.date()}."))

    if not facts.has_track:
        if facts.dq_issues:
            raw.append(_cond("DATA_EXCEPTION", "RULE-DATA-005", "Invalid source values: " + ", ".join(facts.dq_issues)))
        return raw

    cm = facts.current_milestone
    mtype = cm.get("milestone_type") or "UNKNOWN"

    # Data exceptions
    if not facts.rule_found:
        raw.append(_cond("DATA_EXCEPTION", "RULE-DATA-001", f"No active milestone rule for {mtype}."))
    if facts.milestone_conflicts:
        raw.append(_cond("DATA_EXCEPTION", "RULE-DATA-002",
                         f"Conflicting dates on {mtype}: " + ", ".join(facts.milestone_conflicts)))
    if facts.required_party_type and not facts.party_ok:
        raw.append(_cond("DATA_EXCEPTION", "RULE-DATA-003",
                         f"{mtype} requires an active assigned {facts.required_party_type.lower()}; none assigned."))
    if not facts.specialist_ok:
        raw.append(_cond("DATA_EXCEPTION", "RULE-DATA-004", "No active assigned servicing specialist."))
    if facts.dq_issues:
        raw.append(_cond("DATA_EXCEPTION", "RULE-DATA-005", "Invalid source values: " + ", ".join(facts.dq_issues)))

    # Duplicates: two or more open follow-up-type events of the same type for the current milestone.
    by_type: dict[str, int] = {}
    for ev in facts.open_followups:
        by_type[ev["event_type"]] = by_type.get(ev["event_type"], 0) + 1
    dupes = {k: v for k, v in by_type.items() if v >= 2}
    if dupes:
        raw.append(_cond("DUPLICATE_RISK", "RULE-DUPLICATE-001",
                         ", ".join(f"{v} open {k} events" for k, v in dupes.items()) + f" for {mtype}."))

    rule = facts.rule or {}
    if facts.milestone_complete:
        if facts.next_milestone_type and not facts.next_milestone_exists:
            raw.append(_cond("COMPLETED_NEEDS_NEXT", "RULE-MILESTONE-003",
                             f"{mtype} completed; next milestone {facts.next_milestone_type} not opened."))
        elif facts.rule_found and not facts.next_milestone_type:
            raw.append(_cond("COMPLETED", "RULE-MILESTONE-004", f"Terminal milestone {mtype} complete."))
    else:
        lookahead = rule.get("lookahead_days")
        if lookahead is None:
            lookahead = int(th.get("default_lookahead_days", 7))
        if facts.effective_followup_date is None:
            if facts.rule_found and rule.get("requires_followup"):
                raw.append(_cond("MISSING_FOLLOWUP", "RULE-FOLLOWUP-002", f"{mtype} requires a follow-up date; none exists."))
        else:
            dtf = facts.days_to_followup
            if dtf < 0:
                raw.append(_cond("OVERDUE", "RULE-FOLLOWUP-003",
                                 f"{mtype} follow-up {facts.effective_followup_date} is {facts.days_overdue} days overdue."))
            elif dtf == 0:
                raw.append(_cond("DUE", "RULE-FOLLOWUP-004", f"{mtype} follow-up due today."))
            elif dtf <= int(lookahead):
                raw.append(_cond("UPCOMING", "RULE-FOLLOWUP-005",
                                 f"{mtype} follow-up in {dtf} days (look-ahead {lookahead})."))

    # Already actioned: actionable condition covered by a pending approved action.
    actionable = set(ctx.settings.business_rules.get("actionable_conditions", []))
    if facts.pending_action and any(c["code"] in actionable for c in raw):
        raw.append(_cond("ALREADY_ACTIONED", "RULE-PENDING-002",
                         f"Actionable condition covered by pending action {facts.pending_action['action_id']}."))
    return raw


def select_primary(raw: list[dict], precedence: list[str]) -> tuple[str, list[str]]:
    codes = []
    for c in raw:
        if c["code"] not in codes:
            codes.append(c["code"])
    if not codes:
        return "NO_ACTION", []
    ranked = sorted(codes, key=lambda c: precedence.index(c) if c in precedence else len(precedence))
    return ranked[0], ranked[1:]


def evaluate_conditions(facts: LoanFacts, ctx: EngineContext) -> dict:
    raw = detect_raw_conditions(facts, ctx)
    primary, secondary = select_primary(raw, ctx.settings.business_rules["condition_precedence"])
    rule_ids = sorted({c["rule_id"] for c in raw})
    if primary == "NO_ACTION" and not raw:
        detail = "On track." if facts.has_track else "No servicing track."
        raw_out = [_cond("NO_ACTION", "RULE-NOACTION-001", detail)]
        rule_ids = ["RULE-NOACTION-001"]
    else:
        raw_out = raw
    return {"raw_conditions": raw_out, "primary_condition": primary, "secondary_conditions": secondary,
            "condition_rule_ids": rule_ids}

