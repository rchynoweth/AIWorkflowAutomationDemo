"""Deterministic loan facts derived from silver data (RULE-MILESTONE-001/002, RULE-FOLLOWUP-001, ...).

Facts are plain values; conditions, escalation, scoring, and allowed actions are computed from them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

from src.verification.verifier import FAILURE_STATUSES, _as_date, _as_ts, verify_action

PARTY_TYPE_FOR_ACTION = {"CONTACT_ATTORNEY": "ATTORNEY", "CONTACT_SERVICING_VENDOR": "VENDOR"}


@dataclass
class EngineContext:
    settings: Any
    processing_date: date
    rules_by_type: dict[str, dict]          # active rules only
    all_rules_by_type: dict[str, dict]
    parties_by_id: dict[str, dict]
    specialists_by_id: dict[str, dict]

    @property
    def thresholds(self) -> dict:
        return self.settings.thresholds

    @classmethod
    def build(cls, settings, silver, processing_date: date | None = None) -> "EngineContext":
        rules = silver.milestone_rules.to_dict("records")
        return cls(
            settings=settings,
            processing_date=processing_date or settings.processing_date,
            rules_by_type={r["milestone_type"]: _clean(r) for r in rules if r["active"]},
            all_rules_by_type={r["milestone_type"]: _clean(r) for r in rules},
            parties_by_id={p["party_id"]: p for p in silver.attorneys_vendors.to_dict("records")},
            specialists_by_id={s["specialist_id"]: s for s in silver.servicing_specialists.to_dict("records")},
        )


def _clean(record: dict) -> dict:
    out = {}
    for k, v in record.items():
        if isinstance(v, float) and pd.isna(v):
            out[k] = None
        elif v is pd.NA:
            out[k] = None
        elif hasattr(v, "item") and not isinstance(v, (str, bytes)):
            try:
                out[k] = v.item()
            except (ValueError, AttributeError):
                out[k] = v
        else:
            out[k] = v
    return out


@dataclass
class LoanFacts:
    loan: dict
    events: list[dict]
    milestone_events: list[dict] = field(default_factory=list)
    current_milestone: dict | None = None
    rule: dict | None = None
    rule_found: bool = False
    milestone_complete: bool = False
    milestone_conflicts: list[str] = field(default_factory=list)
    open_followups: list[dict] = field(default_factory=list)
    effective_followup_date: date | None = None
    effective_followup_event_id: str | None = None
    days_to_followup: int | None = None
    days_overdue: int = 0
    next_milestone_type: str | None = None
    next_milestone_exists: bool = False
    actions: list[dict] = field(default_factory=list)
    verifications: dict[str, dict] = field(default_factory=dict)
    latest_action: dict | None = None
    latest_verification: dict | None = None
    failed_action_count: int = 0
    pending_action: dict | None = None
    decisions: list[dict] = field(default_factory=list)
    prior_rejected_actions: list[str] = field(default_factory=list)
    latest_decision: dict | None = None
    required_party_type: str | None = None
    party_ok: bool = True
    specialist_ok: bool = True
    dq_issues: list[str] = field(default_factory=list)

    @property
    def loan_id(self) -> str:
        return self.loan["loan_id"]

    @property
    def has_track(self) -> bool:
        return self.current_milestone is not None

    @property
    def severity(self) -> int | None:
        return int(self.rule["severity"]) if self.rule and self.rule.get("severity") is not None else None


def _event_sort_key(ev: dict):
    created = _as_ts(ev.get("created_at"))
    return (_as_date(ev.get("event_date")) or date.min, created or datetime.min, ev["event_id"])


def _action_sort_key(action: dict):
    submitted = _as_ts(action.get("submitted_at")) or datetime.min
    origin = 0 if str(action.get("action_id", "")).startswith("ACT-HIST") else 1
    return (_as_date(action.get("event_date")) or date.min, origin, submitted)


def build_loan_facts(loan: dict, events: list[dict], actions: list[dict], decisions: list[dict],
                     ctx: EngineContext) -> LoanFacts:
    P = ctx.processing_date
    th = ctx.thresholds
    facts = LoanFacts(loan=loan, events=sorted(events, key=_event_sort_key))
    if loan.get("dq_issues"):
        facts.dq_issues.extend(str(loan["dq_issues"]).split(";"))

    # RULE-MILESTONE-001: current milestone
    milestones = [e for e in facts.events if e.get("event_type") == "MILESTONE" and e.get("status") != "CANCELLED"]
    facts.milestone_events = milestones
    if milestones:
        def rank(ev):
            seq = ev.get("milestone_sequence")
            seq = -1 if seq is None or (isinstance(seq, float) and pd.isna(seq)) else int(seq)
            return (seq,) + _event_sort_key(ev)
        current = max(milestones, key=rank)
        facts.current_milestone = current
        mtype = current.get("milestone_type") or ""
        facts.rule = ctx.rules_by_type.get(mtype)
        facts.rule_found = facts.rule is not None
        # RULE-MILESTONE-002 + RULE-DATA-002
        completed_date = _as_date(current.get("completed_date"))
        event_date = _as_date(current.get("event_date"))
        status = current.get("status")
        facts.milestone_complete = status == "COMPLETED" and completed_date is not None
        if completed_date and event_date and completed_date < event_date:
            facts.milestone_conflicts.append("COMPLETED_BEFORE_EVENT")
        if status == "COMPLETED" and completed_date is None:
            facts.milestone_conflicts.append("COMPLETED_WITHOUT_DATE")
        if status == "OPEN" and completed_date is not None:
            facts.milestone_conflicts.append("OPEN_WITH_COMPLETED_DATE")
        if current.get("dq_issues"):
            for issue in str(current["dq_issues"]).split(";"):
                if issue and issue not in facts.milestone_conflicts and not issue.startswith(
                        ("COMPLETED_BEFORE", "COMPLETED_WITHOUT", "OPEN_WITH")):
                    facts.dq_issues.append(issue)

        # RULE-FOLLOWUP-001: effective follow-up
        facts.open_followups = [
            e for e in facts.events
            if e.get("is_followup_type") and e.get("status") == "OPEN" and (e.get("milestone_type") or "") == mtype
        ]
        with_dates = [e for e in facts.open_followups if _as_date(e.get("followup_date"))]
        if with_dates:
            latest = max(with_dates, key=_event_sort_key)
            facts.effective_followup_date = _as_date(latest["followup_date"])
            facts.effective_followup_event_id = latest["event_id"]
        elif _as_date(current.get("followup_date")):
            facts.effective_followup_date = _as_date(current["followup_date"])
            facts.effective_followup_event_id = current["event_id"]
        if facts.effective_followup_date and not facts.milestone_complete:
            facts.days_to_followup = (facts.effective_followup_date - P).days
            facts.days_overdue = max(0, -facts.days_to_followup)

        # next milestone
        rule_any = facts.rule or {}
        facts.next_milestone_type = rule_any.get("next_milestone_type") or None
        if facts.next_milestone_type:
            facts.next_milestone_exists = any(
                (e.get("milestone_type") or "") == facts.next_milestone_type for e in facts.events)

        # RULE-DATA-003 / RULE-DATA-004: assigned parties
        if facts.rule:
            facts.required_party_type = PARTY_TYPE_FOR_ACTION.get(facts.rule.get("overdue_action"))
        if facts.required_party_type:
            party = ctx.parties_by_id.get(loan.get("assigned_attorney_vendor_id") or "")
            facts.party_ok = bool(party and party.get("active") and party.get("party_type") == facts.required_party_type)
        spec = ctx.specialists_by_id.get(loan.get("assigned_specialist_id") or "")
        facts.specialist_ok = bool(spec and spec.get("active"))

    # actions + verification
    facts.actions = sorted(actions, key=_action_sort_key)
    window = int(th.get("verification_window_days", 2))
    lookback_start = P - timedelta(days=int(th.get("failure_lookback_days", 30)))
    for action in facts.actions:
        facts.verifications[action["action_id"]] = verify_action(action, facts.events, P, window)
    recent = [a for a in facts.actions if (_as_date(a.get("event_date")) or date.min) >= lookback_start]
    if recent:
        facts.latest_action = recent[-1]
        facts.latest_verification = facts.verifications[facts.latest_action["action_id"]]
        if facts.latest_verification["verification_status"] == "PENDING":
            facts.pending_action = facts.latest_action
    facts.failed_action_count = sum(
        1 for a in recent if facts.verifications[a["action_id"]]["verification_status"] in FAILURE_STATUSES)

    # decisions
    facts.decisions = sorted(decisions, key=lambda d: _as_ts(d.get("decided_at")) or datetime.min)
    if facts.decisions:
        facts.latest_decision = facts.decisions[-1]
    rejection_start = P - timedelta(days=int(th.get("prior_rejection_lookback_days", 14)))
    facts.prior_rejected_actions = sorted({
        d["original_action"] for d in facts.decisions
        if d.get("decision") == "REJECT" and d.get("original_action")
        and ((_as_ts(d.get("decided_at")) or datetime.min).date() >= rejection_start)
    })
    return facts
