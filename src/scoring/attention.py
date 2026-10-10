"""Deterministic, explainable attention scoring (config/attention_scoring.yml, RULE-SCORING-001).

The LLM may explain the score but never calculates it.
"""
from __future__ import annotations

from datetime import datetime, timezone

from src.rules.facts import EngineContext, LoanFacts


def priority_for(score: int, thresholds: dict) -> str:
    for name, minimum in sorted(thresholds.items(), key=lambda kv: kv[1], reverse=True):
        if score >= minimum:
            return name
    return "LOW"


def compute_attention_score(facts: LoanFacts, cond: dict, ctx: EngineContext) -> dict:
    cfg = ctx.settings.attention_scoring
    f = cfg["factors"]
    primary = cond["primary_condition"]
    drivers: list[dict] = []

    def add(factor: str, points: int, detail: str) -> None:
        if points:
            drivers.append({"factor": factor, "points": int(points), "detail": detail})

    add("primary_condition", cfg["condition_points"].get(primary, 0), primary)
    if facts.days_overdue:
        pts = min(f["days_overdue"]["max_points"], facts.days_overdue * f["days_overdue"]["points_per_unit"])
        add("days_overdue", pts, f"{facts.days_overdue} days overdue")
    if facts.has_track and primary not in cfg.get("severity_applies_to_conditions_except", []):
        severity = facts.severity if facts.severity is not None else cfg.get("default_missing_rule_severity", 3)
        mtype = facts.current_milestone.get("milestone_type")
        pts = min(f["milestone_severity"]["max_points"], severity * f["milestone_severity"]["points_per_unit"])
        add("milestone_severity", pts, f"{mtype} severity {severity}" + ("" if facts.rule_found else " (default)"))
    secondary = cond["secondary_conditions"]
    if secondary:
        pts = min(f["secondary_conditions"]["max_points"], len(secondary) * f["secondary_conditions"]["points_per_unit"])
        add("secondary_conditions", pts, ", ".join(secondary))
    if facts.failed_action_count:
        pts = min(f["failed_actions"]["max_points"], facts.failed_action_count * f["failed_actions"]["points_per_unit"])
        add("failed_actions", pts, f"{facts.failed_action_count} failed/unverified action(s)")
    if facts.required_party_type and not facts.party_ok:
        add("missing_assigned_party", f["missing_assigned_party"]["points"], f"No active {facts.required_party_type.lower()}")
    if facts.prior_rejected_actions:
        add("prior_rejection", f["prior_rejection"]["points"], "Rejected: " + ", ".join(facts.prior_rejected_actions))
    cdp = f["critical_date_proximity"]
    if (facts.has_track and not facts.milestone_complete and (facts.severity or 0) >= cdp["min_severity"]
            and facts.days_to_followup is not None and facts.days_to_followup <= cdp["max_days_to_followup"]
            and primary not in ("ALREADY_ACTIONED", "PENDING_ACTION")):
        add("critical_date_proximity", cdp["points"], f"Severity {facts.severity} milestone within {cdp['max_days_to_followup']} days")
    if primary == "ALREADY_ACTIONED":
        add("covered_by_pending_action", f["covered_by_pending_action"]["points"], "Covered by a pending approved action")

    score = max(0, min(cfg["max_score"], sum(d["points"] for d in drivers)))
    return {
        "score": int(score),
        "priority": priority_for(score, cfg["priority_thresholds"]),
        "score_drivers": drivers,
        "calculated_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds"),
        "scoring_version": cfg["version"],
    }


def drivers_text(drivers: list[dict], top: int = 3) -> str:
    ranked = sorted(drivers, key=lambda d: d["points"], reverse=True)[:top]
    return "; ".join(f"{d['detail']} ({d['points']:+d})" for d in ranked)
