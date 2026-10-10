"""Portfolio evaluation engine: facts -> conditions -> escalation -> score -> allowed actions.

Used identically by the pipeline (Gold build), the API/app (in-process), and tests.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from src.rules.allowed_actions import compute_allowed_actions
from src.rules.conditions import evaluate_conditions
from src.rules.escalation import compute_escalation
from src.rules.facts import EngineContext, LoanFacts, _clean, build_loan_facts
from src.scoring.attention import compute_attention_score, drivers_text
from src.transformations.silver import SilverDataset
from src.verification.verifier import _as_date


@dataclass
class PortfolioEvaluation:
    ctx: EngineContext
    silver: SilverDataset
    facts: dict[str, LoanFacts]
    results: dict[str, dict]
    duration_ms: float = 0.0
    loan_ids: list[str] = field(default_factory=list)

    @property
    def processing_date(self) -> date:
        return self.ctx.processing_date

    def get(self, loan_id: str) -> dict | None:
        return self.results.get(loan_id)

    def active_results(self) -> list[dict]:
        return [r for r in self.results.values() if r["is_active"]]

    def all_verifications(self) -> list[dict]:
        out = []
        for facts in self.facts.values():
            for action in facts.actions:
                v = facts.verifications[action["action_id"]]
                out.append({**v, "action_type": action.get("action_type"), "event_type": action.get("event_type"),
                            "action_status": action.get("status"), "submitted_at": action.get("submitted_at"),
                            "action_event_date": action.get("event_date"), "followup_date": action.get("followup_date")})
        return out


def state_fingerprint(facts: LoanFacts, primary: str, rule_version: str) -> str:
    parts = [
        primary,
        (facts.current_milestone or {}).get("event_id") or "",
        str(facts.effective_followup_date or ""),
        (facts.pending_action or {}).get("action_id") or "",
        (facts.latest_verification or {}).get("verification_status") or "",
        str(len(facts.open_followups)),
        rule_version,
    ]
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:12]


def evaluate_loan(facts: LoanFacts, ctx: EngineContext) -> dict:
    cond = evaluate_conditions(facts, ctx)
    esc = compute_escalation(facts, cond, ctx)
    score = compute_attention_score(facts, cond, ctx)
    allowed = compute_allowed_actions(facts, cond, esc, ctx)
    loan = facts.loan
    cm = facts.current_milestone or {}
    primary = cond["primary_condition"]
    return {
        "loan_id": facts.loan_id,
        "borrower_display_name": loan.get("borrower_display_name"),
        "property_state": loan.get("property_state"),
        "property_county": loan.get("property_county"),
        "portfolio_id": loan.get("portfolio_id"),
        "current_balance": loan.get("current_balance"),
        "payment_status": loan.get("payment_status"),
        "days_delinquent": loan.get("days_delinquent"),
        "loan_status": loan.get("loan_status"),
        "foreclosure_status": loan.get("foreclosure_status"),
        "is_active": bool(loan.get("is_active")),
        "assigned_specialist_id": loan.get("assigned_specialist_id"),
        "specialist_name": loan.get("specialist_name"),
        "assigned_party_id": loan.get("assigned_attorney_vendor_id") or None,
        "party_name": loan.get("party_name") or None,
        "party_type": loan.get("party_type") or None,
        "current_milestone": cm.get("milestone_type"),
        "milestone_sequence": cm.get("milestone_sequence"),
        "milestone_status": cm.get("status"),
        "milestone_event_id": cm.get("event_id"),
        "milestone_complete": facts.milestone_complete,
        "milestone_severity": facts.severity,
        "effective_followup_date": facts.effective_followup_date.isoformat() if facts.effective_followup_date else None,
        "days_to_followup": facts.days_to_followup,
        "days_overdue": facts.days_overdue,
        "raw_conditions": cond["raw_conditions"],
        "primary_condition": primary,
        "secondary_conditions": cond["secondary_conditions"],
        "condition_rule_ids": cond["condition_rule_ids"],
        **{k: esc[k] for k in ("escalation_state", "escalation_reasons", "required_role", "health_segment",
                               "needs_attention")},
        "allowed_actions": allowed["allowed_actions"],
        "default_action": allowed["default_action"],
        "removed_actions": allowed["removed_actions"],
        "attention_score": score["score"],
        "priority": score["priority"],
        "score_drivers": score["score_drivers"],
        "top_drivers_text": drivers_text(score["score_drivers"]),
        "pending_action_id": (facts.pending_action or {}).get("action_id"),
        "latest_action_id": (facts.latest_action or {}).get("action_id"),
        "latest_verification_status": (facts.latest_verification or {}).get("verification_status"),
        "failed_action_count": facts.failed_action_count,
        "prior_rejected_actions": facts.prior_rejected_actions,
        "state_fingerprint": state_fingerprint(facts, primary, ctx.settings.rule_version),
        "processing_date": ctx.processing_date.isoformat(),
        "rule_version": ctx.settings.rule_version,
        "scoring_version": score["scoring_version"],
        "calculated_at": score["calculated_at"],
    }


def _group(frame: pd.DataFrame, key: str = "loan_id") -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    if frame is None or frame.empty:
        return grouped
    for rec in frame.to_dict("records"):
        grouped.setdefault(rec[key], []).append(_clean(rec))
    return grouped


def evaluate_portfolio(silver: SilverDataset, settings, processing_date: date | None = None) -> PortfolioEvaluation:
    started = time.perf_counter()
    ctx = EngineContext.build(settings, silver, processing_date)
    events = _group(silver.loan_events)
    actions = _group(silver.servicing_action_history)
    decisions = _group(silver.reviewer_decisions)
    facts_by_loan: dict[str, LoanFacts] = {}
    results: dict[str, dict] = {}
    loan_ids = []
    for loan in silver.loans.to_dict("records"):
        loan = _clean(loan)
        lid = loan["loan_id"]
        loan_ids.append(lid)
        facts = build_loan_facts(loan, events.get(lid, []), actions.get(lid, []), decisions.get(lid, []), ctx)
        facts_by_loan[lid] = facts
        results[lid] = evaluate_loan(facts, ctx)
    return PortfolioEvaluation(ctx=ctx, silver=silver, facts=facts_by_loan, results=results,
                               duration_ms=(time.perf_counter() - started) * 1000, loan_ids=loan_ids)


def milestone_state_rows(evaluation: PortfolioEvaluation) -> list[dict]:
    rows = []
    for lid, facts in evaluation.facts.items():
        current_id = (facts.current_milestone or {}).get("event_id")
        for ev in facts.milestone_events:
            rows.append({
                "loan_id": lid,
                "milestone_type": ev.get("milestone_type"),
                "milestone_sequence": ev.get("milestone_sequence"),
                "event_id": ev["event_id"],
                "event_date": str(_as_date(ev.get("event_date")) or ""),
                "followup_date": str(_as_date(ev.get("followup_date")) or ""),
                "completed_date": str(_as_date(ev.get("completed_date")) or ""),
                "status": ev.get("status"),
                "is_current": ev["event_id"] == current_id,
                "is_complete": ev.get("status") == "COMPLETED" and _as_date(ev.get("completed_date")) is not None,
                "dq_issues": ev.get("dq_issues") or "",
            })
    return rows
