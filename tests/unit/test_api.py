"""REST API responses via FastAPI TestClient."""
import pytest
from fastapi.testclient import TestClient

from src.api import container
from src.api.main import app


@pytest.fixture()
def client(service):
    container.set_service(service)
    yield TestClient(app)
    container.set_service(None)


def test_health_and_summary(client):
    assert client.get("/api/health").json()["status"] == "ok"
    s = client.get("/api/portfolio/summary").json()
    assert s["active_loans"] > 1000 and s["synthetic_data"] is True
    assert {h["health_segment"] for h in s["health_segments"]} == {"Healthy", "Watch", "Action Required", "Critical"}


def test_queue_and_loans(client):
    q = client.get("/api/portfolio/priority-queue", params={"priority": "CRITICAL"}).json()
    assert q and all(r["priority"] == "CRITICAL" for r in q) and q[0]["why_prioritized"]
    loans = client.get("/api/portfolio/loans", params={"search": "LSI-SYN-000005"}).json()
    assert [r["loan_id"] for r in loans] == ["LSI-SYN-000005"]


def test_loan_endpoints(client):
    d = client.get("/api/loans/LSI-SYN-000005").json()
    assert d["state"]["attention_score"] == 54 and d["synthetic_data"]
    assert client.get("/api/loans/LSI-SYN-000005/events").json()
    assert client.get("/api/loans/NOPE").status_code == 404


def test_agent_decision_submit_refresh(client):
    a = client.post("/api/agent", json={"mode": "assess", "loan_id": "LSI-SYN-000005"}).json()
    assert a["requires_human_approval"] and a["score"] == 54 and a["tool_calls"]
    rid = a["recommendation"]["recommendation_id"]
    d = client.post(f"/api/recommendations/{rid}/decision", json={"decision": "APPROVE"}).json()
    action_id = d["action"]["action_id"]
    assert client.get("/api/actions/pending").json()
    assert client.post(f"/api/actions/{action_id}/submit").json()["status"] == "SUBMITTED"
    r = client.post("/api/refresh").json()
    assert r["verification"] == {"VERIFIED": 1}
    assert any(v["action_id"] == action_id and v["verification_status"] == "VERIFIED"
               for v in client.get("/api/actions/verification").json())
    assert client.post(f"/api/recommendations/{rid}/decision", json={"decision": "APPROVE"}).status_code == 409


def test_ask_briefing_and_evaluation(client):
    ask = client.post("/api/agent", json={"mode": "ask", "loan_id": "LSI-SYN-000006",
                                          "question": "What should happen next?"}).json()
    assert ask["answer"]
    b = client.post("/api/agent", json={"mode": "briefing"}).json()
    assert b["text"] and b["facts"]
    e = client.get("/api/evaluation/summary").json()
    assert e["rule_metrics"]["condition_accuracy"] == 1.0 and e["synthetic"]


def test_validation_errors(client):
    assert client.post("/api/agent", json={"mode": "assess"}).status_code == 422
    assert client.post("/api/recommendations/NOPE/decision", json={"decision": "APPROVE"}).status_code == 404


def test_batch_triage_and_reload(client):
    out = client.post("/api/agent/batch", json={"loan_ids": ["LSI-SYN-000006", "LSI-SYN-000007"]}).json()
    assert out["analyzed"] == 2 and all(r["recommended_action"] for r in out["results"])
    recs = client.get("/api/loans/LSI-SYN-000006/recommendations").json()
    assert recs[0]["status"] == "PENDING_REVIEW"
    reloaded = client.post("/api/reload").json()
    assert reloaded["recommendations"] >= 2
    assert client.get("/api/loans/LSI-SYN-000006/recommendations").json()[0]["recommendation_id"] == \
        recs[0]["recommendation_id"]


def test_queue_reports_recommendation_source(client):
    client.post("/api/agent/batch", json={"loan_ids": ["LSI-SYN-000006"]})
    row = next(r for r in client.get("/api/portfolio/priority-queue").json() if r["loan_id"] == "LSI-SYN-000006")
    assert row["recommendation_source"] == "deterministic"
