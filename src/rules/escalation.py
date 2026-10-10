"""Deterministic escalation (config/escalation_rules.yml, RULE-ESCALATION-001..010)."""
from __future__ import annotations

from src.rules.facts import EngineContext, LoanFacts


def _matches(when: dict, facts: LoanFacts, cond: dict) -> bool:
    primary = cond["primary_condition"]
    codes = {c["code"] for c in cond["raw_conditions"]}
    severity = facts.severity or 0
    checks = {
        "min_days_overdue": lambda v: facts.days_overdue >= v,
        "min_severity": lambda v: severity >= v,
        "max_days_to_followup": lambda v: facts.days_to_followup is not None and facts.days_to_followup <= v,
        "milestone_incomplete": lambda v: (not facts.milestone_complete) == bool(v) and facts.has_track,
        "min_failed_actions": lambda v: facts.failed_action_count >= v,
        "any_condition": lambda v: bool(codes & set(v)),
        "primary_condition_in": lambda v: primary in v,
        "primary_condition_not_in": lambda v: primary not in v,
        "missing_assigned_party": lambda v: (bool(facts.required_party_type) and not facts.party_ok) == bool(v),
        "prior_rejection": lambda v: bool(facts.prior_rejected_actions) == bool(v),
    }
    for key, value in when.items():
        if key not in checks:
            raise ValueError(f"Unknown escalation condition key: {key}")
        if not checks[key](value):
            return False
    return True


def compute_escalation(facts: LoanFacts, cond: dict, ctx: EngineContext) -> dict:
    cfg = ctx.settings.escalation_rules
    order = cfg["states_order"]
    state = "NONE"
    reasons = []
    for rule in cfg["rules"]:
        if _matches(rule.get("when", {}), facts, cond):
            reasons.append({"rule_id": rule["id"], "state": rule["state"], "reason": rule["reason"]})
            if order.index(rule["state"]) > order.index(state):
                state = rule["state"]
    return {
        "escalation_state": state,
        "escalation_reasons": reasons,
        "required_role": cfg["required_roles"][state],
        "health_segment": cfg["health_segments"][state],
        "needs_attention": state in ("FOLLOW_UP", "ESCALATE", "CRITICAL"),
    }
