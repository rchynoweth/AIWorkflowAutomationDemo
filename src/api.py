"""REST API (FastAPI) over LoanServicingService. See docs/API_SPECIFICATION.md."""
from __future__ import annotations

import logging
import threading

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.encoders import jsonable_encoder

from src import databricks
from src.agent import LlmError
from src.config import get_settings
from src.models import AgentChatRequest, ScheduleRequest, AgentRequest, BatchAgentRequest, DecisionRequest, EvaluationRequest
from src.service import InvalidState, LoanServicingService, NotFound, ValidationFailed
from src.storage import create_repository


# ====================================================================================================
# Process-wide service singleton shared by the API and the in-process Streamlit client
# ====================================================================================================

log = logging.getLogger(__name__)
_lock = threading.Lock()
_service: LoanServicingService | None = None
_error: str | None = None


def get_service() -> LoanServicingService:
    global _service, _error
    if _service is not None:
        return _service
    with _lock:
        if _service is None:
            settings = get_settings()
            try:
                service = LoanServicingService(settings, create_repository(settings)).load()
            except Exception as exc:  # noqa: BLE001
                if settings.backend == "databricks":
                    _error = f"Databricks backend unavailable ({type(exc).__name__}: {str(exc)[:200]}); using local."
                    log.exception("Falling back to local repository")
                    service = LoanServicingService(settings, create_repository(settings, "local")).load()
                else:
                    raise
            _service = service
    return _service


def startup_warning() -> str | None:
    return _error


def set_service(service: LoanServicingService | None) -> None:
    """Testing hook."""
    global _service
    _service = service


# ====================================================================================================
# Loan Servicing Intelligence Agent API (docs/API_SPECIFICATION.md). Synthetic demonstration
# ====================================================================================================

app = FastAPI(title="Loan Servicing Intelligence API",
              description="Agent-powered portfolio monitoring and loan-servicing workflow automation. "
                          "All data is synthetic.", version="0.1.0")


def svc() -> LoanServicingService:
    return get_service()


def _handle(fn, *args, **kwargs):
    try:
        return jsonable_encoder(fn(*args, **kwargs))
    except NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationFailed as exc:
        raise HTTPException(status_code=409, detail={"code": "VALIDATION_FAILED", "errors": exc.errors}) from exc
    except InvalidState as exc:
        raise HTTPException(status_code=409, detail={"code": "INVALID_STATE", "message": str(exc)}) from exc
    except LlmError as exc:
        raise HTTPException(status_code=503, detail="AGENT_UNAVAILABLE") from exc


# ---- operations ----------------------------------------------------------------------------
@app.get("/api/health")
def health(service: LoanServicingService = Depends(svc)):
    return {**service.health(), "startup_warning": startup_warning()}


@app.get("/api/config/versions")
def versions(service: LoanServicingService = Depends(svc)):
    return service.settings.versions()


@app.post("/api/reload")
def reload(service: LoanServicingService = Depends(svc)):
    return _handle(service.reload)


@app.get("/api/backend/status")
def backend(service: LoanServicingService = Depends(svc)):
    status = databricks.workflow_status()
    latest = databricks.latest_success_end(status)
    status["newer_than_app"] = bool(latest and service.loaded_at and latest > service.loaded_at)
    status["app_loaded_at"] = service.loaded_at
    return jsonable_encoder(status)


@app.get("/api/ai/backend")
def backend_ai(service: LoanServicingService = Depends(svc)):
    """AI created in Databricks: AI Functions summaries, agent reviews, and the portfolio briefing."""
    return jsonable_encoder(service.backend_ai)


@app.get("/api/backend/resources")
def resources(service: LoanServicingService = Depends(svc)):
    return jsonable_encoder(databricks.resource_inventory(service.settings))


@app.post("/api/backend/run-pipeline")
def run_pipeline():
    try:
        return databricks.run_pipeline_now()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Could not start workflow: {str(exc)[:200]}") from exc


@app.post("/api/demo/reset")
def reset(service: LoanServicingService = Depends(svc)):
    return _handle(service.reset_demo)


# ---- agent ---------------------------------------------------------------------------------
@app.post("/api/agent")
def agent(request: AgentRequest, service: LoanServicingService = Depends(svc)):
    if request.mode == "assess":
        if not request.loan_id:
            raise HTTPException(status_code=422, detail="loan_id is required for assess")
        return _handle(service.analyze_loan, request.loan_id, request.user_id, request.agent_mode)
    if request.mode == "ask":
        if not request.question:
            raise HTTPException(status_code=422, detail="question is required for ask")
        return _handle(service.ask, request.question, request.loan_id, request.user_id, request.agent_mode)
    return _handle(service.briefing, request.agent_mode)


@app.get("/api/agent/deployment")
def agent_deployment(service: LoanServicingService = Depends(svc)):
    return jsonable_encoder(databricks.deployment_status(service.settings))


@app.post("/api/agent/deployed/chat")
def agent_deployed_chat(request: AgentChatRequest):
    try:
        return databricks.chat(request.messages, request.instructions)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Deployed agent unavailable: {str(exc)[:300]}") from exc


@app.post("/api/agent/batch")
def agent_batch(request: BatchAgentRequest, service: LoanServicingService = Depends(svc)):
    return _handle(service.triage, request.loan_ids, request.limit, request.agent_mode)


@app.get("/api/agent/activity")
def activity(loan_id: str | None = None, run_id: str | None = None, limit: int = 300,
             service: LoanServicingService = Depends(svc)):
    return _handle(service.activity, loan_id, run_id, limit)


# ---- portfolio -----------------------------------------------------------------------------
@app.get("/api/portfolio/summary")
def portfolio_summary(service: LoanServicingService = Depends(svc)):
    return _handle(service.portfolio_summary)


@app.get("/api/portfolio/loans")
def portfolio_loans(state: str | None = None, portfolio: str | None = None, loan_status: str | None = None,
                    payment_status: str | None = None, foreclosure_status: str | None = None,
                    milestone: str | None = None, health: str | None = None, priority: str | None = None,
                    specialist: str | None = None, agent_status: str | None = None, condition: str | None = None,
                    search: str | None = None, limit: int = Query(2000, le=5000),
                    service: LoanServicingService = Depends(svc)):
    return _handle(service.portfolio_loans, state=state, portfolio=portfolio, loan_status=loan_status,
                   payment_status=payment_status, foreclosure_status=foreclosure_status, milestone=milestone,
                   health=health, priority=priority, specialist=specialist, agent_status=agent_status,
                   condition=condition, search=search, limit=limit)


@app.get("/api/portfolio/priority-queue")
def priority_queue(priority: str | None = None, condition: str | None = None, review_status: str | None = None,
                   specialist: str | None = None, limit: int = Query(200, le=2000),
                   service: LoanServicingService = Depends(svc)):
    return _handle(service.priority_queue, priority, condition, review_status, specialist, limit)


@app.get("/api/portfolio/briefing-facts")
def briefing_facts(service: LoanServicingService = Depends(svc)):
    return _handle(service.briefing_facts)


# ---- loans ---------------------------------------------------------------------------------
@app.get("/api/loans/{loan_id}")
def loan(loan_id: str, service: LoanServicingService = Depends(svc)):
    return _handle(service.loan_detail, loan_id)


@app.get("/api/loans/{loan_id}/events")
def loan_events(loan_id: str, include_payments: bool = False, service: LoanServicingService = Depends(svc)):
    return _handle(service.loan_events, loan_id, include_payments)


@app.get("/api/loans/{loan_id}/next-step")
def next_step(loan_id: str, action: str | None = None, service: LoanServicingService = Depends(svc)):
    return _handle(service.next_step, loan_id, action)


@app.post("/api/loans/{loan_id}/schedule")
def schedule(loan_id: str, request: ScheduleRequest, service: LoanServicingService = Depends(svc)):
    return _handle(service.schedule_next_step, loan_id, request.action_type, request.followup_date, request.note,
                   request.outreach, request.reviewer_id, request.reviewer_role, "loan view", request.send)


@app.get("/api/loans/{loan_id}/recommendations")
def loan_recommendations(loan_id: str, service: LoanServicingService = Depends(svc)):
    return _handle(service.loan_recommendations, loan_id)


@app.get("/api/loans/{loan_id}/activity")
def loan_activity(loan_id: str, service: LoanServicingService = Depends(svc)):
    return _handle(service.activity, loan_id)


# ---- recommendations and actions ---------------------------------------------------------
@app.get("/api/recommendations/awaiting-approval")
def awaiting(service: LoanServicingService = Depends(svc)):
    from src.tools import get_recommendations_awaiting_approval
    return _handle(get_recommendations_awaiting_approval, service.tool_ctx, 500)


@app.post("/api/recommendations/{recommendation_id}/decision")
def decision(recommendation_id: str, request: DecisionRequest, service: LoanServicingService = Depends(svc)):
    return _handle(service.decide, recommendation_id, request)


@app.get("/api/actions/pending")
def pending_actions(service: LoanServicingService = Depends(svc)):
    return _handle(service.pending_actions)


@app.get("/api/actions/verification")
def verification(service: LoanServicingService = Depends(svc)):
    return _handle(service.verification_results)


@app.get("/api/actions/{action_id}")
def get_action(action_id: str, service: LoanServicingService = Depends(svc)):
    return _handle(service.get_action, action_id)


@app.post("/api/actions/{action_id}/submit")
def submit_action(action_id: str, service: LoanServicingService = Depends(svc)):
    return _handle(service.submit_action, action_id)


@app.post("/api/refresh")
def refresh(service: LoanServicingService = Depends(svc)):
    return _handle(service.refresh)


# ---- evaluation ------------------------------------------------------------------------------
@app.get("/api/evaluation/summary")
def evaluation_summary(service: LoanServicingService = Depends(svc)):
    return _handle(service.evaluation_summary)


@app.post("/api/evaluation/run")
def evaluation_run(request: EvaluationRequest, service: LoanServicingService = Depends(svc)):
    return _handle(service.run_agent_evaluation, request.agent_mode)
