"""Allowed actions (config/allowed_actions.yml, RULE-ACTIONS-001, RULE-REVIEW-001)."""
from __future__ import annotations

from src.rules.facts import EngineContext, LoanFacts


def _dedupe(seq: list[str]) -> list[str]:
    out: list[str] = []
    for item in seq:
        if item and item not in out:
            out.append(item)
    return out


def compute_allowed_actions(facts: LoanFacts, cond: dict, escalation: dict, ctx: EngineContext) -> dict:
    cfg = ctx.settings.allowed_actions
    primary = cond["primary_condition"]
    removed: list[dict] = []

    base = list(cfg["by_condition"].get(primary, ["NO_ACTION"]))
    if primary == "VERIFICATION_FAILURE" and facts.latest_verification:
        override = cfg.get("verification_overrides", {}).get(facts.latest_verification["verification_status"])
        if override:
            base = list(override)
    overdue_action = (facts.rule or {}).get("overdue_action") or "CREATE_FOLLOWUP"
    if overdue_action == "NO_ACTION":
        overdue_action = "CREATE_FOLLOWUP"
    actions = _dedupe([overdue_action if a == "MILESTONE_OVERDUE_ACTION" else a for a in base])

    state = escalation["escalation_state"]
    if primary not in cfg.get("escalation_adjustment_exempt_conditions", []):
        adj = cfg.get("escalation_adjustments", {}).get(state, {})
        actions = _dedupe(list(adj.get("prepend", [])) + actions + list(adj.get("append", [])))

    # Contact actions need an active party of the required type.
    party = ctx.parties_by_id.get(facts.loan.get("assigned_attorney_vendor_id") or "")
    kept = []
    for action in actions:
        required = cfg["actions"].get(action, {}).get("requires_party_type")
        if required and not (party and party.get("active") and party.get("party_type") == required):
            removed.append({"action": action, "reason": f"No active assigned {required.lower()}", "rule_id": "RULE-DATA-003"})
            continue
        kept.append(action)
    actions = kept

    # RULE-REVIEW-001: prior rejection, unless escalated.
    if facts.prior_rejected_actions and state not in ("ESCALATE", "CRITICAL"):
        kept = []
        for action in actions:
            if action in facts.prior_rejected_actions and action != "NO_ACTION":
                removed.append({"action": action, "reason": "Rejected by a reviewer inside the lookback window",
                                "rule_id": "RULE-REVIEW-001"})
                continue
            kept.append(action)
        actions = kept

    if not actions:
        actions = ["REQUEST_INFORMATION"]
    return {"allowed_actions": actions, "default_action": actions[0], "removed_actions": removed,
            "rule_id": "RULE-ACTIONS-001", "actions_version": cfg["version"]}
