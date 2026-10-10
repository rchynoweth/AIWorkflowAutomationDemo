"""Date logic: days to follow-up and follow-up date calculation (RULE-FOLLOWUP-006)."""
from __future__ import annotations

from datetime import date, timedelta

from src.rules.facts import EngineContext, LoanFacts


def days_between(start: date, end: date) -> int:
    return (end - start).days


def roll_to_business_day(day: date) -> date:
    while day.weekday() >= 5:  # Saturday=5, Sunday=6
        day += timedelta(days=1)
    return day


def followup_days_for(action_type: str, facts: LoanFacts, ctx: EngineContext, original_action: dict | None = None) -> tuple[int, str]:
    """Return (days, basis) for the proposed follow-up of ``action_type``."""
    spec = ctx.settings.allowed_actions["actions"].get(action_type, {})
    setting = spec.get("followup_days")
    if setting == "milestone_default":
        days = (facts.rule or {}).get("default_followup_days") or 14
        return int(days), f"{(facts.current_milestone or {}).get('milestone_type')} default_followup_days"
    if setting == "next_milestone_default":
        nxt = ctx.rules_by_type.get(facts.next_milestone_type or "", {})
        return int(nxt.get("default_followup_days") or 14), f"{facts.next_milestone_type} default_followup_days"
    if setting is None:
        return 0, "no follow-up"
    return int(setting), f"{action_type} followup_days"


def calculate_followup_date(action_type: str, facts: LoanFacts, ctx: EngineContext) -> dict:
    days, basis = followup_days_for(action_type, facts, ctx)
    if days <= 0:
        return {"followup_date": None, "days": 0, "basis": basis, "rolled": False, "rule_id": "RULE-FOLLOWUP-006"}
    raw = ctx.processing_date + timedelta(days=days)
    rolled = roll_to_business_day(raw) if ctx.thresholds.get("business_days_only", True) else raw
    return {"followup_date": rolled.isoformat(), "days": days, "basis": basis, "rolled": rolled != raw,
            "rule_id": "RULE-FOLLOWUP-006"}
