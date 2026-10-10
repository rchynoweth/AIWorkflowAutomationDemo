"""API client and in-process API server bootstrap for the Streamlit app.

The UI never calls services directly: every read/write goes through the REST API. The API runs on a daemon
thread inside the app container; if it cannot bind, the client uses an in-process ASGI transport.
"""
from __future__ import annotations

import threading
import time
from typing import Any

import httpx
import streamlit as st

from src.config.settings import get_settings


class ApiError(Exception):
    def __init__(self, status: int, detail: Any):
        super().__init__(f"{status}: {detail}")
        self.status = status
        self.detail = detail


class ApiClient:
    def __init__(self, base_url: str | None, fallback_app=None):
        if base_url:
            self._client = httpx.Client(base_url=base_url, timeout=180.0)
            self.transport = "http"
        else:
            from fastapi.testclient import TestClient
            self._client = TestClient(fallback_app)
            self.transport = "in-process"

    def _req(self, method: str, path: str, **kwargs):
        resp = self._client.request(method, path, **kwargs)
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("detail")
            except Exception:  # noqa: BLE001
                detail = resp.text
            raise ApiError(resp.status_code, detail)
        return resp.json()

    def get(self, path: str, **params):
        return self._req("GET", path, params={k: v for k, v in params.items() if v not in (None, "", [])})

    def post(self, path: str, body: dict | None = None):
        return self._req("POST", path, json=body or {})

    # convenience wrappers
    def health(self):
        return self.get("/api/health")

    def summary(self):
        return self.get("/api/portfolio/summary")

    def loans(self, **filters):
        return self.get("/api/portfolio/loans", **filters)

    def queue(self, **filters):
        return self.get("/api/portfolio/priority-queue", **filters)

    def loan(self, loan_id: str):
        return self.get(f"/api/loans/{loan_id}")

    def events(self, loan_id: str, include_payments: bool = False):
        return self.get(f"/api/loans/{loan_id}/events", include_payments=str(include_payments).lower())

    def recommendations(self, loan_id: str):
        return self.get(f"/api/loans/{loan_id}/recommendations")

    def loan_activity(self, loan_id: str):
        return self.get(f"/api/loans/{loan_id}/activity")

    def agent(self, mode: str, loan_id: str | None = None, question: str | None = None, user_id: str = "SPEC-01"):
        return self.post("/api/agent", {"mode": mode, "loan_id": loan_id, "question": question, "user_id": user_id})

    def decide(self, recommendation_id: str, body: dict):
        return self.post(f"/api/recommendations/{recommendation_id}/decision", body)

    def action(self, action_id: str):
        return self.get(f"/api/actions/{action_id}")

    def submit(self, action_id: str):
        return self.post(f"/api/actions/{action_id}/submit")

    def refresh(self):
        return self.post("/api/refresh")

    def reset(self):
        return self.post("/api/demo/reset")

    def activity(self, **filters):
        return self.get("/api/agent/activity", **filters)

    def evaluation(self):
        return self.get("/api/evaluation/summary")

    def run_evaluation(self, agent_mode: str):
        return self.post("/api/evaluation/run", {"agent_mode": agent_mode})

    def verification(self):
        return self.get("/api/actions/verification")

    def pending(self):
        return self.get("/api/actions/pending")


@st.cache_resource(show_spinner="Starting Loan Servicing Intelligence (loading synthetic portfolio)...")
def get_client() -> ApiClient:
    from src.api.container import get_service
    from src.api.main import app

    get_service()  # warm the shared service before serving requests
    settings = get_settings()
    host, port = settings.application["api"]["host"], settings.api_port
    try:
        import uvicorn

        server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))
        thread = threading.Thread(target=server.run, daemon=True, name="lsi-api")
        thread.start()
        deadline = time.time() + 20
        while not server.started and thread.is_alive() and time.time() < deadline:
            time.sleep(0.1)
        if server.started:
            client = ApiClient(f"http://{host}:{port}")
            client.health()
            return client
    except Exception:  # noqa: BLE001 - fall back to the in-process transport
        pass
    return ApiClient(None, fallback_app=app)


def reviewer() -> tuple[str, str]:
    return (st.session_state.get("reviewer_id", "SPEC-01"),
            st.session_state.get("reviewer_role", "LOAN_SERVICING_SPECIALIST"))


def open_loan(loan_id: str) -> None:
    st.session_state["selected_loan_id"] = loan_id
    from app.navigation import PAGES
    st.switch_page(PAGES["loan_360"])
