from datetime import date

import pandas as pd

from src.data_generation.generator import (
    ACTION_COLUMNS, DECISION_COLUMNS, EVENT_COLUMNS, LOAN_COLUMNS, MANIFEST_COLUMNS, generate_dataset,
)


def test_generation_is_deterministic():
    a = generate_dataset(seed=7, processing_date=date(2026, 10, 12), loan_count=120)
    b = generate_dataset(seed=7, processing_date=date(2026, 10, 12), loan_count=120)
    for name in a.tables():
        pd.testing.assert_frame_equal(a.tables()[name], b.tables()[name])


def test_different_seed_changes_background_only():
    a = generate_dataset(seed=1, processing_date=date(2026, 10, 12), loan_count=60)
    b = generate_dataset(seed=2, processing_date=date(2026, 10, 12), loan_count=60)
    assert list(a.demo_scenario_manifest["loan_id"]) == list(b.demo_scenario_manifest["loan_id"])
    assert not a.loans.equals(b.loans)


def test_schemas_match_specification():
    d = generate_dataset(loan_count=40)
    assert list(d.loans.columns) == LOAN_COLUMNS
    assert list(d.loan_events.columns) == EVENT_COLUMNS
    assert list(d.servicing_action_history.columns) == ACTION_COLUMNS
    assert list(d.reviewer_decisions.columns) == DECISION_COLUMNS
    assert list(d.demo_scenario_manifest.columns) == MANIFEST_COLUMNS


def test_committed_files_scale_and_labels():
    loans = pd.read_csv("data/generated/loans.csv", dtype=str)
    events = pd.read_csv("data/generated/loan_events.csv", dtype=str)
    assert len(loans) == 1500
    assert len(events) > 20_000
    assert (loans["synthetic_data"] == "true").all()
    assert (events["synthetic_data"] == "true").all()
    assert loans["borrower_display_name"].str.match(r"^Synthetic Borrower \d{4}$").all()
    assert loans["property_address"].str.startswith("Synthetic Address").all()


def test_manifest_has_twenty_scenarios_with_unique_loans():
    m = pd.read_csv("data/generated/demo_scenario_manifest.csv", dtype=str)
    assert len(m) == 20
    assert m["loan_id"].is_unique
    required = {"HEALTHY_NO_ACTION", "UPCOMING", "DUE_TODAY", "ONE_DAY_OVERDUE", "MATERIALLY_OVERDUE",
                "SEVERELY_OVERDUE", "COMPLETED_NEEDS_NEXT", "MISSING_FOLLOWUP", "DUPLICATE_RISK", "CONFLICTING_DATES",
                "MISSING_RULE", "MISSING_ASSIGNED_PARTY", "PRIOR_REJECTION", "APPROVED_ACTION_PENDING",
                "SUCCESSFUL_VERIFICATION", "FAILED_VERIFICATION", "MISMATCHED_VERIFICATION", "MULTIPLE_UNRESOLVED",
                "URGENT_COVERED_BY_PENDING"}
    assert required <= set(m["scenario_type"])


def test_committed_files_match_generator():
    d = generate_dataset()
    committed = pd.read_csv("data/generated/loans.csv", dtype=str, keep_default_na=False)
    pd.testing.assert_frame_equal(d.loans.reset_index(drop=True), committed, check_dtype=False)
