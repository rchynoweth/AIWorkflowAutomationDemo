"""Evaluation metric math, customer-neutrality scan, bronze lineage."""
import pandas as pd

from src.evaluation.evaluator import reviewer_metrics, verification_metrics
from src.ingestion.bronze import LINEAGE_COLUMNS, record_hash, to_bronze
from src.quality.neutrality import check_generated_names, scan, scan_text


def test_reviewer_metrics():
    m = reviewer_metrics([{"decision": d} for d in ["APPROVE", "APPROVE", "EDIT", "REJECT"]])
    assert m == {"decisions": 4, "acceptance_rate": 0.5, "edit_rate": 0.25, "rejection_rate": 0.25,
                 "deferral_rate": 0.0, "escalation_rate": 0.0}


def test_verification_metrics():
    m = verification_metrics([{"verification_status": s} for s in ["VERIFIED", "VERIFIED", "MISMATCH", "PENDING"]])
    assert m["verification_success_rate"] == round(2 / 3, 4)


def test_repository_is_customer_neutral():
    findings, scanned = scan()
    assert scanned > 50
    assert findings == [], findings[:5]
    assert check_generated_names() == []


def test_scanner_detects_risks(monkeypatch):
    monkeypatch.setenv("LSI_NEUTRALITY_DENYLIST", "acme lending")
    from src.quality.neutrality import _denylist
    text = "Contact jane@acme-lending.test or see https://intranet.acme.test at 123 Main Street, call 555-123-4567."
    cats = {f.category for f in scan_text("x.md", text + " Acme Lending", _denylist())}
    assert {"email", "url", "street_address", "phone", "denylist"} <= cats


def test_bronze_preserves_values_and_adds_lineage():
    raw = pd.DataFrame({"a": ["001", ""], "b": ["x", "y,z"]})
    b = to_bronze(raw, "f.csv", "BATCH-1", "2026-10-12T00:00:00")
    assert list(b["a"]) == ["001", ""]
    assert all(c in b.columns for c in LINEAGE_COLUMNS)
    assert list(b["source_row_number"]) == [1, 2]
    assert b["record_hash"][0] == record_hash(["001", "x"])
