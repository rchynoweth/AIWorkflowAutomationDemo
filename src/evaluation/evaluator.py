"""Rule, agent, reviewer, and verification evaluation against the scenario manifest (docs/EVALUATION_PLAN.md).

All metrics are computed on synthetic data.
"""
from __future__ import annotations

import uuid
from collections import Counter
from datetime import datetime, timezone

import pandas as pd

from src.verification.verifier import FAILURE_STATUSES

CREATING_ACTIONS_EXCLUDE = {"NO_ACTION"}


def load_manifest(path) -> list[dict]:
    return pd.read_csv(path, dtype=str, keep_default_na=False).to_dict("records")


def _actual_verification(result: dict) -> str:
    return result.get("latest_verification_status") or "NOT_APPLICABLE"


def evaluate_rules(manifest: list[dict], evaluation) -> dict:
    rows = []
    for m in manifest:
        r = evaluation.get(m["loan_id"]) or {}
        actual = {
            "condition": r.get("primary_condition"), "priority": r.get("priority"),
            "action": r.get("default_action"), "verification": _actual_verification(r) if r else None,
        }
        expected = {"condition": m["expected_condition"], "priority": m["expected_priority"],
                    "action": m["expected_action"], "verification": m["expected_verification_status"]}
        rows.append({"scenario_id": m["scenario_id"], "loan_id": m["loan_id"], "scenario_type": m["scenario_type"],
                     **{f"expected_{k}": v for k, v in expected.items()},
                     **{f"actual_{k}": v for k, v in actual.items()},
                     **{f"passed_{k}": expected[k] == actual[k] for k in expected},
                     "attention_score": r.get("attention_score")})
    n = max(1, len(rows))
    metrics = {f"{k}_accuracy": round(sum(r[f"passed_{k}"] for r in rows) / n, 4)
               for k in ("condition", "priority", "action", "verification")}
    metrics["scenarios"] = len(rows)
    return {"metrics": metrics, "rows": rows}


def evaluate_agent(manifest: list[dict], recommendations: dict[str, dict], evaluation) -> dict:
    rows = []
    tool_calls = tool_failures = fallbacks = 0
    for m in manifest:
        rec = recommendations.get(m["loan_id"])
        if rec is None:
            continue
        state = evaluation.get(m["loan_id"]) or {}
        calls = rec.get("tool_calls") or []
        tool_calls += len(calls)
        tool_failures += sum(1 for c in calls if not c.get("success"))
        fallbacks += int("fallback" in str(rec.get("uncertainty", "")).lower() or "LLM unavailable" in str(rec.get("uncertainty", "")))
        expected_action = m["expected_action"]
        actual = rec.get("recommended_action")
        rows.append({
            "scenario_id": m["scenario_id"], "loan_id": m["loan_id"], "expected_action": expected_action,
            "actual_action": actual, "action_agreement": actual == expected_action,
            "allowed_compliance": actual in (rec.get("allowed_actions") or []),
            "score_integrity": int(rec.get("attention_score", -1)) == int(state.get("attention_score", -2)),
            "evidence_items": len(rec.get("evidence") or []),
            "false_positive": expected_action == "NO_ACTION" and actual not in CREATING_ACTIONS_EXCLUDE,
            "false_negative": expected_action != "NO_ACTION" and actual == "NO_ACTION",
            "confidence": rec.get("confidence"), "agent_mode": rec.get("agent_mode"), "tool_calls": len(calls),
        })
    n = max(1, len(rows))
    metrics = {
        "evaluated": len(rows),
        "action_agreement": round(sum(r["action_agreement"] for r in rows) / n, 4),
        "allowed_action_compliance": round(sum(r["allowed_compliance"] for r in rows) / n, 4),
        "score_integrity": round(sum(r["score_integrity"] for r in rows) / n, 4),
        "evidence_coverage": round(sum(r["evidence_items"] >= 3 for r in rows) / n, 4),
        "false_positive_rate": round(sum(r["false_positive"] for r in rows) / n, 4),
        "false_negative_rate": round(sum(r["false_negative"] for r in rows) / n, 4),
        "tool_failure_rate": round(tool_failures / max(1, tool_calls), 4),
        "fallback_rate": round(fallbacks / n, 4),
        "mean_tool_calls": round(tool_calls / n, 2),
    }
    return {"metrics": metrics, "rows": rows}


def reviewer_metrics(decisions: list[dict]) -> dict:
    counts = Counter((d.get("decision") or "").upper() for d in decisions)
    total = max(1, sum(counts.values()))
    return {
        "decisions": sum(counts.values()),
        "acceptance_rate": round(counts.get("APPROVE", 0) / total, 4),
        "edit_rate": round(counts.get("EDIT", 0) / total, 4),
        "rejection_rate": round(counts.get("REJECT", 0) / total, 4),
        "deferral_rate": round(counts.get("DEFER", 0) / total, 4),
        "escalation_rate": round(counts.get("ESCALATE", 0) / total, 4),
    }


def verification_metrics(verifications: list[dict]) -> dict:
    counts = Counter(v["verification_status"] for v in verifications)
    resolved = counts.get("VERIFIED", 0) + sum(counts.get(s, 0) for s in FAILURE_STATUSES)
    return {"distribution": dict(counts),
            "verification_success_rate": round(counts.get("VERIFIED", 0) / max(1, resolved), 4)}


def evaluation_rows(rule_eval: dict, agent_eval: dict, processing_date: str) -> list[dict]:
    """Row-level results for gold_agent_evaluation."""
    eval_id = f"EVAL-{datetime.now(timezone.utc):%Y%m%d%H%M%S}-{uuid.uuid4().hex[:4]}"
    rows = []
    for r in rule_eval["rows"]:
        for k in ("condition", "priority", "action", "verification"):
            rows.append({"evaluation_id": eval_id, "scenario_id": r["scenario_id"], "loan_id": r["loan_id"],
                         "check_type": "RULE", "metric": k, "expected": r[f"expected_{k}"],
                         "actual": str(r[f"actual_{k}"]), "passed": bool(r[f"passed_{k}"]),
                         "processing_date": processing_date})
    for r in agent_eval["rows"]:
        for k in ("action_agreement", "allowed_compliance", "score_integrity"):
            rows.append({"evaluation_id": eval_id, "scenario_id": r["scenario_id"], "loan_id": r["loan_id"],
                         "check_type": "AGENT", "metric": k, "expected": "true", "actual": str(r[k]).lower(),
                         "passed": bool(r[k]), "processing_date": processing_date})
    return rows
