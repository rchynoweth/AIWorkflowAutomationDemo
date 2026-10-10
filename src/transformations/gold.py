"""Gold table assembly from a portfolio evaluation and operational state.

List/dict columns are JSON-encoded strings for portability across SQL clients.
"""
from __future__ import annotations

import json
from collections import Counter

import pandas as pd

from src.services.portfolio_engine import PortfolioEvaluation, milestone_state_rows

JSON_COLUMNS = ["raw_conditions", "secondary_conditions", "condition_rule_ids", "escalation_reasons",
                "allowed_actions", "removed_actions", "score_drivers", "prior_rejected_actions"]
HEALTH_ORDER = ["Healthy", "Watch", "Action Required", "Critical"]
PRIORITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}


def to_json(value) -> str:
    return json.dumps(value, default=str)


def encode_json_columns(df: pd.DataFrame, columns: list[str] | None = None) -> pd.DataFrame:
    out = df.copy()
    for col in columns or JSON_COLUMNS:
        if col in out.columns:
            out[col] = out[col].map(to_json)
    return out


def loan_state_frame(evaluation: PortfolioEvaluation) -> pd.DataFrame:
    return pd.DataFrame(list(evaluation.results.values()))


def portfolio_kpis(evaluation: PortfolioEvaluation, recommendations: list[dict] | None = None,
                   actions: list[dict] | None = None) -> dict:
    active = evaluation.active_results()
    conditions = Counter(r["primary_condition"] for r in active)
    raw = Counter(c["code"] for r in active for c in r["raw_conditions"])
    P = evaluation.processing_date.isoformat()
    recs = recommendations or []
    acts = actions or []
    return {
        "active_loans": len(active),
        "need_attention": sum(1 for r in active if r["needs_attention"]),
        "upcoming": raw.get("UPCOMING", 0),
        "due": raw.get("DUE", 0),
        "overdue": raw.get("OVERDUE", 0),
        "missing_followup": raw.get("MISSING_FOLLOWUP", 0),
        "critical": sum(1 for r in active if r["priority"] == "CRITICAL"),
        "data_exceptions": raw.get("DATA_EXCEPTION", 0),
        "duplicate_risk": raw.get("DUPLICATE_RISK", 0),
        "recommendations_awaiting_approval": sum(1 for r in recs if r.get("status") == "PENDING_REVIEW"),
        # ``actions`` are app-approved (operational) actions; their event_date is the business approval date.
        "approved_today": sum(1 for a in acts if str(a.get("event_date") or "")[:10] == P),
        "verification_failures": raw.get("VERIFICATION_FAILURE", 0),
        "pending_actions": raw.get("PENDING_ACTION", 0),
        "condition_counts": dict(conditions),
        "raw_condition_counts": dict(raw),
    }


def health_segments(evaluation: PortfolioEvaluation) -> list[dict]:
    active = evaluation.active_results()
    counts = Counter(r["health_segment"] for r in active)
    total = max(1, len(active))
    return [{"health_segment": s, "loan_count": counts.get(s, 0), "share_of_active": round(counts.get(s, 0) / total, 4)}
            for s in HEALTH_ORDER]


def briefing_facts(evaluation: PortfolioEvaluation, recommendations: list[dict] | None = None,
                   actions: list[dict] | None = None) -> list[dict]:
    """Deterministic facts: the only inputs to the portfolio briefing."""
    k = portfolio_kpis(evaluation, recommendations, actions)
    active = evaluation.active_results()
    attention = [r for r in active if r["needs_attention"]]
    facts = [("portfolio", "processing_date", evaluation.processing_date.isoformat())]
    for key in ("active_loans", "need_attention", "critical", "overdue", "due", "upcoming", "missing_followup",
                "data_exceptions", "duplicate_risk", "verification_failures", "pending_actions",
                "recommendations_awaiting_approval", "approved_today"):
        facts.append(("kpi", key, k[key]))
    for seg in health_segments(evaluation):
        facts.append(("health", seg["health_segment"], seg["loan_count"]))
    for prio, n in Counter(r["priority"] for r in active).items():
        facts.append(("priority", prio, n))
    for cond, n in Counter(r["primary_condition"] for r in attention).most_common(5):
        facts.append(("top_attention_condition", cond, n))
    for ms, n in Counter(r["current_milestone"] for r in attention if r["current_milestone"]).most_common(3):
        facts.append(("top_attention_milestone", ms, n))
    for pf, n in Counter(r["portfolio_id"] for r in attention).most_common(2):
        facts.append(("top_attention_portfolio", pf, n))
    for sp, n in Counter(r["specialist_name"] for r in attention if r["specialist_name"]).most_common(2):
        facts.append(("top_attention_specialist", sp, n))
    overdue = [r["days_overdue"] for r in active if any(c["code"] == "OVERDUE" for c in r["raw_conditions"])]
    if overdue:
        facts.append(("overdue", "overdue_30_plus", sum(1 for d in overdue if d >= 30)))
        facts.append(("overdue", "overdue_60_plus", sum(1 for d in overdue if d >= 60)))
        facts.append(("overdue", "max_days_overdue", max(overdue)))
    top = sorted(attention, key=lambda r: (-r["attention_score"], r["loan_id"]))[:3]
    for i, r in enumerate(top, 1):
        facts.append(("top_loan", f"rank_{i}", f"{r['loan_id']} {r['primary_condition']} score {r['attention_score']}"))
    return [{"fact_group": g, "fact_name": n, "fact_value": str(v),
             "processing_date": evaluation.processing_date.isoformat()} for g, n, v in facts]


def priority_queue_rows(evaluation: PortfolioEvaluation, recommendations: list[dict] | None = None,
                        review_status: dict[str, str] | None = None) -> list[dict]:
    latest_rec: dict[str, dict] = {}
    for rec in sorted(recommendations or [], key=lambda r: str(r.get("created_at"))):
        if rec.get("status") != "SUPERSEDED":
            latest_rec[rec["loan_id"]] = rec
    rows = []
    for r in evaluation.active_results():
        if not r["needs_attention"]:
            continue
        rec = latest_rec.get(r["loan_id"], {})
        rows.append({
            "priority": r["priority"],
            "loan_id": r["loan_id"],
            "borrower_display_name": r["borrower_display_name"],
            "primary_condition": r["primary_condition"],
            "secondary_conditions": r["secondary_conditions"],
            "escalation_state": r["escalation_state"],
            "severity": r["milestone_severity"],
            "current_milestone": r["current_milestone"],
            "effective_followup_date": r["effective_followup_date"],
            "days_overdue": r["days_overdue"],
            "attention_score": r["attention_score"],
            "score_drivers": r["score_drivers"],
            "top_drivers_text": r["top_drivers_text"],
            "recommended_action": rec.get("recommended_action") or r["default_action"],
            "recommendation_id": rec.get("recommendation_id"),
            "confidence": rec.get("confidence"),
            "specialist_name": r["specialist_name"],
            "review_status": (review_status or {}).get(r["loan_id"], "NOT_ANALYZED"),
            "why_prioritized": f"{r['primary_condition']}: " + "; ".join(
                c["detail"] for c in r["raw_conditions"] if c["code"] == r["primary_condition"]),
        })
    rows.sort(key=lambda x: (PRIORITY_ORDER[x["priority"]], -x["attention_score"], x["loan_id"]))
    for i, row in enumerate(rows, 1):
        row["queue_rank"] = i
    return rows


def verification_rows(evaluation: PortfolioEvaluation) -> list[dict]:
    P = evaluation.processing_date.isoformat()
    return [{**v, "evaluated_on": P} for v in evaluation.all_verifications()]


def build_gold_tables(evaluation: PortfolioEvaluation, recommendations: list[dict] | None = None,
                      actions: list[dict] | None = None, review_status: dict[str, str] | None = None) -> dict[str, pd.DataFrame]:
    state = loan_state_frame(evaluation)
    verif = pd.DataFrame(verification_rows(evaluation))
    if not verif.empty:
        verif["matched_event_ids"] = verif["matched_event_ids"].map(to_json)
        verif["differences"] = verif["differences"].map(to_json)
        for col in ("submitted_at", "action_event_date", "followup_date"):
            verif[col] = verif[col].astype(str)
    queue = pd.DataFrame(priority_queue_rows(evaluation, recommendations, review_status))
    if not queue.empty:
        queue = encode_json_columns(queue, ["secondary_conditions", "score_drivers"])
    return {
        "gold_loan_servicing_state": encode_json_columns(state),
        "gold_loan_milestone_state": pd.DataFrame(milestone_state_rows(evaluation)),
        "gold_attention_candidates": encode_json_columns(state[state["needs_attention"] & state["is_active"]]),
        "gold_priority_queue": queue,
        "gold_portfolio_health": pd.DataFrame(health_segments(evaluation)).assign(
            processing_date=evaluation.processing_date.isoformat()),
        "gold_portfolio_briefing_facts": pd.DataFrame(briefing_facts(evaluation, recommendations, actions)),
        "gold_action_verification": verif,
        "gold_pending_actions": verif[verif["verification_status"] == "PENDING"] if not verif.empty else verif,
    }
