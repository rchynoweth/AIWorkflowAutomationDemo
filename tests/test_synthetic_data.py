"""The generator is deterministic and builds the 20 demo scenarios."""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "notebooks"))

from synthetic_data import SCENARIOS, generate_dataset  # noqa: E402

DAY = date(2026, 10, 12)


def test_same_input_same_data():
    first, second = generate_dataset(DAY, loan_count=200), generate_dataset(DAY, loan_count=200)
    for name, frame in first.tables().items():
        assert frame.equals(second.tables()[name]), name


def test_demo_scenarios_exist():
    loans = generate_dataset(DAY, loan_count=200).loans
    assert len(loans) == 200
    assert {f"LSI-SYN-{s[1]:06d}" for s in SCENARIOS} <= set(loans.loan_id)


def test_completed_title_review_needs_next_milestone():
    """LSI-SYN-000007: Title Review completed three days ago and Complaint Filed never opened (RULE-MILESTONE-003)."""
    events = generate_dataset(DAY, loan_count=50).loan_events
    milestones = events[(events.loan_id == "LSI-SYN-000007") & (events.event_type == "MILESTONE")]
    title = milestones[milestones.milestone_type == "TITLE_REVIEW"].iloc[0]
    assert title.status == "COMPLETED" and title.completed_date == "2026-10-09"
    assert "COMPLAINT_FILED" not in set(milestones.milestone_type)
