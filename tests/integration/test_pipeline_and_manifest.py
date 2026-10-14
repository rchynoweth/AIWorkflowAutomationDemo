"""Ingestion, Bronze->Silver, Silver->Gold, System-of-Record overlay, scenario manifest (100% rule accuracy)."""
import pandas as pd
import pytest

from src.evaluation import evaluate_rules, load_manifest
from src.medallion import apply_system_of_record_updates, build_gold_tables, overlay_operational

pytestmark = pytest.mark.integration


def test_bronze_tables(bronze):
    assert set(bronze) == {"bronze_loans", "bronze_loan_events", "bronze_milestone_rules",
                           "bronze_servicing_specialists", "bronze_attorneys_vendors",
                           "bronze_servicing_action_history", "bronze_reviewer_decisions"}
    assert bronze["bronze_loans"]["batch_id"].nunique() == 1
    assert bronze["bronze_loans"]["record_hash"].is_unique


def test_silver_typing_and_sequencing(silver):
    ev = silver.loan_events
    assert ev["event_id"].is_unique
    assert (ev.groupby("loan_id")["event_sequence"].min() == 1).all()
    assert ev.loc[ev["milestone_type"] == "TITLE_REVIEW", "milestone_sequence"].eq(4).all()
    assert ev.loc[ev["milestone_type"] == "LEGACY_REVIEW", "milestone_sequence"].eq(-1).all()  # inactive rule
    assert silver.loans["is_active"].sum() < len(silver.loans)
    assert len(silver.active_foreclosures) > 0
    assert silver.loans["specialist_name"].str.startswith("Synthetic Specialist").all()


def test_gold_tables(evaluation):
    gold = build_gold_tables(evaluation)
    for name in ("gold_loan_servicing_state", "gold_loan_milestone_state", "gold_attention_candidates",
                 "gold_priority_queue", "gold_portfolio_health", "gold_portfolio_briefing_facts",
                 "gold_action_verification", "gold_pending_actions"):
        assert name in gold and not gold[name].empty, name
    state = gold["gold_loan_servicing_state"]
    assert len(state) == 1500 and state["score_drivers"].str.startswith("[").all()
    queue = gold["gold_priority_queue"]
    assert list(queue["queue_rank"]) == list(range(1, len(queue) + 1))
    assert gold["gold_portfolio_health"]["loan_count"].sum() == len(evaluation.active_results())


def test_sor_overlay_upserts_by_event_id(silver, settings):
    target = silver.loan_events[silver.loan_events["loan_id"] == "LSI-SYN-000009"].iloc[-1]
    sor = pd.DataFrame([{
        "event_id": target["event_id"], "loan_id": "LSI-SYN-000009", "event_type": target["event_type"],
        "milestone_type": target["milestone_type"], "event_date": str(target["event_date"]),
        "followup_date": str(target["followup_date"] or ""), "completed_date": "2026-10-12", "status": "COMPLETED",
        "event_note": "closed", "source": "SERVICING_SYSTEM_EXPORT", "created_at": "2026-10-01T00:00:00",
        "updated_at": "2030-01-01T00:00:00", "synthetic_data": "true", "available_cycle": 1, "action_id": "A"}])
    hidden = apply_system_of_record_updates(silver, sor, cycle=0, settings=settings)
    assert len(hidden.loan_events) == len(silver.loan_events)
    visible = apply_system_of_record_updates(silver, sor, cycle=1, settings=settings)
    row = visible.loan_events.set_index("event_id").loc[target["event_id"]]
    assert row["status"] == "COMPLETED" and len(visible.loan_events) == len(silver.loan_events)


def test_overlay_operational_is_idempotent(silver):
    ops = pd.DataFrame([{"action_id": "ACT-NEW", "loan_id": "LSI-SYN-000005", "recommendation_id": "R",
                         "action_type": "CONTACT_ATTORNEY", "event_type": "CONTACT", "milestone_type": "TITLE_REVIEW",
                         "event_date": "2026-10-12", "followup_date": "2026-10-19", "status": "APPROVED",
                         "submitted_at": None, "verified_at": None, "failure_reason": None}])
    once = overlay_operational(silver, ops, None)
    twice = overlay_operational(once, ops, None)
    assert len(twice.servicing_action_history) == len(silver.servicing_action_history) + 1


def test_scenario_manifest_rules_are_100_percent(evaluation, settings):
    manifest = load_manifest(settings.path("generated_dir") / "demo_scenario_manifest.csv")
    result = evaluate_rules(manifest, evaluation)
    failures = [r for r in result["rows"] if not all(r[f"passed_{k}"] for k in
                                                     ("condition", "priority", "action", "verification"))]
    assert not failures, failures
    assert all(v == 1.0 for k, v in result["metrics"].items() if k.endswith("accuracy"))
