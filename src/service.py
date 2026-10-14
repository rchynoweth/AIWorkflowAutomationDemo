"""LoanServicingService: the application facade (analysis, review, actions, adapter, refresh, evaluation)."""
from __future__ import annotations

import contextlib
import json
import logging
import os
import shutil
import threading
import time
import uuid
from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta, timezone

from src import evaluation, medallion
from src.agent import create_agent, RunContext
from src.medallion import apply_system_of_record_updates, overlay_operational
from src.rules import (
    _as_date,
    evaluate_portfolio,
    FAILURE_STATUSES,
    PortfolioEvaluation,
    prepare_event,
    reference_token,
    validate_proposed_event,
)
from src.storage import OperationalState
from src.tools import ToolContext


# ====================================================================================================
# Activity logging and optional MLflow tracing. Never records prompts, credentials, or chain-of-thought
# ====================================================================================================

log = logging.getLogger("lsi.activity")


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="milliseconds")


def new_run_id(prefix: str = "RUN") -> str:
    return f"{prefix}-{datetime.now(timezone.utc):%Y%m%d}-{uuid.uuid4().hex[:6]}"


class ActivityBuffer:
    """Collects activity records for a run; the service persists them in one batch."""

    def __init__(self, actor: str = "agent"):
        self.actor = actor
        self.records: list[dict] = []

    def __call__(self, record: dict) -> None:
        rec = {
            "activity_id": f"ACTV-{uuid.uuid4().hex[:12]}",
            "run_id": record.get("run_id"),
            "loan_id": record.get("loan_id"),
            "step": record.get("step") or "tool_call",
            "tool_name": record.get("tool_name"),
            "input_summary": record.get("input_summary", ""),
            "output_summary": record.get("output_summary", ""),
            "duration_ms": record.get("duration_ms", 0.0),
            "success": record.get("success", True),
            "error": record.get("error"),
            "actor": record.get("actor") or self.actor,
            "created_at": record.get("called_at") or utcnow(),
        }
        self.records.append(rec)
        log.info("activity run=%s loan=%s step=%s tool=%s ok=%s ms=%s", rec["run_id"], rec["loan_id"], rec["step"],
                 rec["tool_name"], rec["success"], rec["duration_ms"])


@contextlib.contextmanager
def trace_span(name: str, attributes: dict | None = None):
    """MLflow span when LSI_MLFLOW_TRACING=true and mlflow is importable; otherwise a no-op."""
    if os.environ.get("LSI_MLFLOW_TRACING", "").lower() not in ("1", "true", "yes"):
        yield None
        return
    try:
        import mlflow  # type: ignore
    except Exception:  # noqa: BLE001
        yield None
        return
    try:
        span_cm = mlflow.start_span(name=name)
    except Exception:  # noqa: BLE001
        yield None
        return
    with span_cm as span:
        try:
            if attributes:
                span.set_attributes({k: str(v) for k, v in attributes.items()})
        except Exception:  # noqa: BLE001
            pass
        yield span


# ====================================================================================================
# Loan-servicing System of Record adapters
# ====================================================================================================

MODES = ("SUCCESS", "FAIL", "MISMATCH", "DUPLICATE", "DELAYED")


def _now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


class LoanServicingSystemAdapter(ABC):
    name = "abstract"

    @abstractmethod
    def submit(self, outbound_event: dict, action: dict, cycle: int, open_events: list[dict],
               processing_date: date) -> dict:
        """Return {accepted, mode, system_reference, message, sor_events}."""


class SyntheticServicingSystemAdapter(LoanServicingSystemAdapter):
    name = "synthetic"

    def __init__(self, demo_config: dict, followup_event_types: list[str]):
        cfg = (demo_config or {}).get("adapter", {})
        self.default_mode = cfg.get("default_mode", "SUCCESS")
        self.loan_modes = {k.upper(): v.upper() for k, v in (cfg.get("loan_modes") or {}).items()}
        self.mismatch_shift_days = int(cfg.get("mismatch_shift_days", 7))
        self.delayed_cycles = int(cfg.get("delayed_cycles", 2))
        self.followup_event_types = set(followup_event_types)

    def mode_for(self, loan_id: str) -> str:
        mode = self.loan_modes.get(loan_id.upper(), self.default_mode)
        return mode if mode in MODES else "SUCCESS"

    def _event_row(self, outbound: dict, action: dict, available_cycle: int, followup: str | None,
                   created_at: str) -> dict:
        return {
            "event_id": f"EVT-SOR-{uuid.uuid4().hex[:10].upper()}",
            "loan_id": outbound["loan_id"],
            "event_type": outbound["event_type"],
            "milestone_type": outbound.get("milestone_type") or "",
            "event_date": outbound["event_date"],
            "followup_date": followup or "",
            "completed_date": "",
            "status": "OPEN",
            "event_note": f"{(outbound.get('event_note') or 'Synthetic event created by servicing system.')[:900]} "
                          f"{reference_token(action['action_id'])}",
            "source": "SERVICING_SYSTEM_ADAPTER",
            "created_at": created_at,
            "updated_at": created_at,
            "synthetic_data": "true",
            "available_cycle": available_cycle,
            "action_id": action["action_id"],
        }

    def submit(self, outbound_event: dict, action: dict, cycle: int, open_events: list[dict],
               processing_date: date) -> dict:
        mode = self.mode_for(outbound_event["loan_id"])
        reference = f"SYN-SOR-{uuid.uuid4().hex[:8].upper()}"
        if mode == "FAIL":
            return {"accepted": False, "mode": mode, "system_reference": None,
                    "message": "Synthetic adapter configured failure: servicing system rejected the event.",
                    "sor_events": []}
        now = _now()
        available = cycle + 1 + (self.delayed_cycles if mode == "DELAYED" else 0)
        followup = outbound_event.get("followup_date")
        if mode == "MISMATCH" and followup:
            followup = (date.fromisoformat(followup) + timedelta(days=self.mismatch_shift_days)).isoformat()
        rows = [self._event_row(outbound_event, action, available, followup, now)]
        if mode == "DUPLICATE":
            rows.append(self._event_row(outbound_event, action, available, followup, now))
        elif outbound_event["event_type"] in self.followup_event_types:
            # The simulated System of Record closes prior open follow-up-type events for the milestone.
            for ev in open_events:
                if (ev.get("is_followup_type") and ev.get("status") == "OPEN"
                        and (ev.get("milestone_type") or "") == (outbound_event.get("milestone_type") or "")):
                    rows.append({
                        "event_id": ev["event_id"], "loan_id": ev["loan_id"], "event_type": ev["event_type"],
                        "milestone_type": ev.get("milestone_type") or "",
                        "event_date": str(ev.get("event_date") or ""), "followup_date": str(ev.get("followup_date") or ""),
                        "completed_date": processing_date.isoformat(), "status": "COMPLETED",
                        "event_note": ev.get("event_note") or "", "source": ev.get("source") or "SERVICING_SYSTEM_EXPORT",
                        "created_at": str(ev.get("created_at") or now), "updated_at": now, "synthetic_data": "true",
                        "available_cycle": available, "action_id": action["action_id"],
                    })
        message = {"SUCCESS": "Event accepted by the synthetic servicing system.",
                   "MISMATCH": "Event accepted (synthetic mismatch configured).",
                   "DUPLICATE": "Event accepted (synthetic duplicate configured).",
                   "DELAYED": f"Event accepted; visible after {self.delayed_cycles + 1} refresh cycles."}[mode]
        return {"accepted": True, "mode": mode, "system_reference": reference, "message": message, "sor_events": rows}


# ====================================================================================================
# Approved-action creation (with revalidation) and submission through the System-of-Record adapter
# ====================================================================================================

class ValidationFailed(Exception):
    def __init__(self, errors: list[dict], validation: dict):
        super().__init__("VALIDATION_FAILED")
        self.errors = errors
        self.validation = validation


class InvalidState(Exception):
    pass


def new_action_id() -> str:
    return f"ACT-{datetime.now(timezone.utc):%Y%m%d}-{uuid.uuid4().hex[:8].upper()}"


def original_failed_action(facts) -> dict | None:
    for a in reversed(facts.actions):
        if facts.verifications[a["action_id"]]["verification_status"] in FAILURE_STATUSES:
            return a
    return None


def revalidate(evaluation, rec: dict, action_type: str, followup_date: str | None, note: str | None,
               outreach: str | None, escalation_target: str | None, event_type: str | None = None,
               allow_escalation: bool = False) -> tuple[dict, dict]:
    """Rebuild the outbound draft from current facts and validate it (RULE-VALIDATION-001)."""
    loan_id = rec["loan_id"]
    facts = evaluation.facts[loan_id]
    state = dict(evaluation.results[loan_id])
    if allow_escalation and "ESCALATE_TO_SPECIALIST" not in state["allowed_actions"]:
        state["allowed_actions"] = state["allowed_actions"] + ["ESCALATE_TO_SPECIALIST"]
    original = original_failed_action(facts) if action_type == "RETRY_FAILED_ACTION" else None
    draft = prepare_event(action_type, facts, evaluation.ctx, followup_date, note, outreach, escalation_target, original)
    if event_type and draft.get("creates_event") and action_type == "RETRY_FAILED_ACTION":
        draft["event_type"] = event_type
    validation = validate_proposed_event(draft, facts, state, evaluation.ctx, rec.get("state_fingerprint"),
                                         rec.get("rule_version"))
    return draft, validation


def build_action(rec: dict, decision: dict, draft: dict, reviewer_id: str, adapter_mode: str) -> dict:
    action_id = new_action_id()
    payload = {**draft, "status": "APPROVED_FOR_SUBMISSION", "action_id": action_id,
               "recommendation_id": rec["recommendation_id"], "decision_id": decision["decision_id"],
               "approved_by": reviewer_id}
    return {
        "action_id": action_id,
        "loan_id": rec["loan_id"],
        "recommendation_id": rec["recommendation_id"],
        "decision_id": decision["decision_id"],
        "action_type": draft["action_type"],
        "event_type": draft["event_type"],
        "milestone_type": draft.get("milestone_type") or "",
        "event_date": draft["event_date"],
        "followup_date": draft.get("followup_date"),
        "note": draft.get("event_note"),
        "outreach": draft.get("outreach_text"),
        "status": "APPROVED",
        "outbound_payload": payload,
        "adapter_mode": adapter_mode,
        "adapter_result": {},
        "approved_by": reviewer_id,
        "approved_at": utcnow(),
        "submitted_at": None,
        "verified_at": None,
        "failure_reason": None,
        "retry_of_action_id": draft.get("retry_of_action_id"),
        "synthetic_data": True,
    }


def write_outbound_file(directory, action: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{action['action_id']}.json").write_text(json.dumps(action["outbound_payload"], indent=2, default=str),
                                                          encoding="utf-8")


def submit(action: dict, adapter, evaluation, cycle: int) -> tuple[dict, list[dict]]:
    """Submit an APPROVED action through the adapter. Returns (updated_action, sor_rows)."""
    if action.get("status") != "APPROVED":
        raise InvalidState(f"Action {action['action_id']} is {action.get('status')}, not APPROVED")
    facts = evaluation.facts[action["loan_id"]]
    result = adapter.submit(action["outbound_payload"], action, cycle, facts.events, evaluation.processing_date)
    updated = dict(action)
    updated["submitted_at"] = utcnow()
    updated["adapter_mode"] = result["mode"]
    updated["adapter_result"] = {k: v for k, v in result.items() if k != "sor_events"}
    if result["accepted"]:
        updated["status"] = "SUBMITTED"
    else:
        updated["status"] = "FAILED"
        updated["failure_reason"] = result["message"]
    return updated, result["sor_events"]


# ====================================================================================================
# Human review decisions: APPROVE, EDIT, REJECT, DEFER, ESCALATE
# ====================================================================================================

def new_decision_id() -> str:
    return f"DEC-{datetime.now(timezone.utc):%Y%m%d}-{uuid.uuid4().hex[:8].upper()}"


def resolve_decision(rec: dict, request, evaluation) -> tuple[dict, dict | None, dict | None]:
    """Return (decision_record, draft_or_None, validation_or_None). Raises ValidationFailed / InvalidState."""
    if rec.get("status") != "PENDING_REVIEW":
        raise InvalidState(f"Recommendation {rec['recommendation_id']} is {rec.get('status')}")
    decision = request.decision
    edits = request.edits.model_dump(exclude_none=True) if request.edits else {}
    action_type = rec["recommended_action"]
    followup = rec.get("recommended_followup_date")
    note = rec.get("suggested_note")
    outreach = rec.get("suggested_outreach")
    target = None
    if decision == "EDIT":
        action_type = (edits.get("action_type") or action_type).upper()
        if edits.get("action_type") and edits["action_type"].upper() != rec["recommended_action"]:
            followup = None  # recalculate for the new action unless the reviewer set one
        followup = edits.get("followup_date") or followup
        note = edits.get("note", note)
        outreach = edits.get("outreach", outreach)
        target = edits.get("escalation_target")
    elif decision == "ESCALATE":
        action_type = "ESCALATE_TO_SPECIALIST"
        followup = edits.get("followup_date")
        target = edits.get("escalation_target") or (
            "SERVICING_MANAGER" if rec.get("escalation_state") == "CRITICAL" else "SENIOR_SPECIALIST")
        note = edits.get("note") or f"Escalated by reviewer: {request.reason or rec['primary_condition']}"

    record = {
        "decision_id": new_decision_id(),
        "recommendation_id": rec["recommendation_id"],
        "loan_id": rec["loan_id"],
        "reviewer_id": request.reviewer_id,
        "reviewer_role": request.reviewer_role,
        "decision": decision,
        "original_action": rec["recommended_action"],
        "final_action": action_type if decision in ("APPROVE", "EDIT", "ESCALATE") else None,
        "original_followup_date": rec.get("recommended_followup_date"),
        "final_followup_date": followup if decision in ("APPROVE", "EDIT", "ESCALATE") else None,
        "original_note": rec.get("suggested_note"),
        "final_note": note if decision in ("APPROVE", "EDIT", "ESCALATE") else None,
        "edits": edits,
        "comment": request.comment,
        "reason": request.reason,
        "decided_at": utcnow(),
        "synthetic_data": True,
    }
    if decision in ("REJECT", "DEFER") or action_type == "NO_ACTION":
        return record, None, None
    draft, validation = revalidate(evaluation, rec, action_type, followup, note, outreach, target,
                                   event_type=edits.get("event_type"), allow_escalation=(decision == "ESCALATE"))
    if not validation["valid"]:
        raise ValidationFailed(validation["errors"], validation)
    record["final_followup_date"] = draft.get("followup_date")
    return record, draft, validation


STATUS_FOR_DECISION = {"APPROVE": "APPROVED", "EDIT": "APPROVED", "REJECT": "REJECTED", "DEFER": "DEFERRED",
                       "ESCALATE": "ESCALATED"}


# ====================================================================================================
# Source refresh and verification of submitted actions
# ====================================================================================================

RECHECK_STATUSES = {"SUBMITTED", "VERIFICATION_FAILED"}


def verify_submitted_actions(evaluation, ops_actions: dict[str, dict], cycle: int) -> tuple[list[dict], list[dict]]:
    """Return (verification_result_rows, updated_actions) for app-submitted actions after a refresh."""
    results, updated = [], []
    for action in ops_actions.values():
        if action.get("status") not in RECHECK_STATUSES:
            continue
        facts = evaluation.facts.get(action["loan_id"])
        if facts is None or action["action_id"] not in facts.verifications:
            continue
        v = facts.verifications[action["action_id"]]
        results.append({
            "verification_id": f"VER-{uuid.uuid4().hex[:12]}",
            "action_id": action["action_id"],
            "loan_id": action["loan_id"],
            "cycle": cycle,
            "verification_status": v["verification_status"],
            "matched_event_ids": v["matched_event_ids"],
            "differences": v["differences"],
            "detail": v["detail"],
            "evaluated_at": utcnow(),
        })
        new_status = action["status"]
        if v["verification_status"] == "VERIFIED":
            new_status = "VERIFIED"
        elif v["verification_status"] in FAILURE_STATUSES:
            new_status = "VERIFICATION_FAILED"
        if new_status != action["status"]:
            changed = dict(action, status=new_status)
            if new_status == "VERIFIED":
                changed["verified_at"] = utcnow()
            updated.append(changed)
    return results, updated


# ====================================================================================================
# LoanServicingService: the facade behind the REST API
# ====================================================================================================

__all__ = ["LoanServicingService", "NotFound", "InvalidState", "ValidationFailed"]


class NotFound(Exception):
    pass


class LoanServicingService:
    def __init__(self, settings, repository, agent_mode: str | None = None, adapter=None, llm=None):
        self.settings = settings
        self.repository = repository
        self.agent_mode = (agent_mode or settings.agent.get("mode") or "auto").lower()
        self.adapter = adapter or SyntheticServicingSystemAdapter(
            settings.demo_scenarios, settings.business_rules.get("followup_event_types", []))
        self._llm = llm
        self._agents: dict[str, object] = {}
        self.lock = threading.RLock()
        self.source = None
        self.ops = OperationalState()
        self.evaluation: PortfolioEvaluation | None = None
        self._events_key = None
        self._events_silver = None
        self._agent_eval: dict | None = None
        self._baseline: PortfolioEvaluation | None = None
        self.loaded_at: str | None = None
        self.backend_ai: dict = {"available": False, "insights": {}, "reviews": {}, "briefing": None}

    # ---- lifecycle ---------------------------------------------------------------------
    def load(self) -> "LoanServicingService":
        with self.lock:
            started = time.perf_counter()
            self.source = self.repository.load_source_silver()
            self._baseline = None
            self.ops = OperationalState.from_tables(self.repository.load_ops())
            self._events_key = None
            self._reevaluate()
            baseline = self.settings.demo_scenarios.get("baseline_recommendations", {})
            if baseline.get("enabled", True) and not self.ops.recommendations:
                self.generate_baseline_recommendations()
            from src.databricks import backend_ai
            self.backend_ai = backend_ai(self.repository)
            self.loaded_at = utcnow()
            log.info("Service loaded in %.1fs (backend=%s)", time.perf_counter() - started, self.repository.backend)
        return self

    def _silver(self):
        key = (self.ops.refresh_cycle, len(self.ops.sor_events))
        if key != self._events_key:
            self._events_silver = apply_system_of_record_updates(self.source, self.ops.sor_frame(),
                                                                 self.ops.refresh_cycle, self.settings)
            self._events_key = key
        return overlay_operational(self._events_silver, self.ops.actions_frame(), self.ops.decisions_frame())

    def _reevaluate(self) -> None:
        self.evaluation = evaluate_portfolio(self._silver(), self.settings)

    @property
    def tool_ctx(self) -> ToolContext:
        return ToolContext(self.evaluation, self.ops, self.settings)

    def agent(self, mode: str | None = None):
        mode = (mode or self.agent_mode).lower()
        if mode not in self._agents:
            self._agents[mode] = create_agent(self.settings, mode, self._llm)
        return self._agents[mode]

    def _persist_activity(self, buffer: ActivityBuffer) -> None:
        if buffer.records:
            self.ops.activity.extend(buffer.records)
            self.repository.upsert("ops_agent_activity", buffer.records)

    def _activity(self, actor: str, step: str, loan_id: str | None, detail: str, success: bool = True,
                  run_id: str | None = None) -> None:
        buffer = ActivityBuffer(actor)
        buffer({"run_id": run_id or new_run_id(actor.upper()[:3]), "loan_id": loan_id, "step": step,
                "output_summary": detail[:400], "success": success, "actor": actor})
        self._persist_activity(buffer)

    def _require_loan(self, loan_id: str) -> str:
        lid = (loan_id or "").strip().upper()
        if lid not in self.evaluation.results:
            raise NotFound("LOAN_NOT_FOUND")
        return lid

    # ---- status helpers ----------------------------------------------------------------
    def _loan_review_status(self, loan_id: str) -> str:
        recs = self.ops.recommendations_for(loan_id)
        latest = next((r for r in recs if r.get("status") != "SUPERSEDED"), None)
        if latest and latest.get("status") == "PENDING_REVIEW":
            return "AWAITING_APPROVAL"
        facts = self.evaluation.facts[loan_id]
        if facts.latest_action and latest and str(latest.get("created_at")) > str(facts.latest_action.get("submitted_at") or "") \
                and latest.get("status") in ("REJECTED", "DEFERRED", "FAILED"):
            return {"REJECTED": "REJECTED", "DEFERRED": "DEFERRED", "FAILED": "AGENT_FAILED"}[latest["status"]]
        if facts.latest_action:
            v = facts.latest_verification["verification_status"]
            status = facts.latest_action.get("status")
            if v == "VERIFIED":
                return "VERIFIED"
            if v in FAILURE_STATUSES:
                return "VERIFICATION_FAILED"
            return "APPROVED" if status == "APPROVED" else "SUBMITTED"
        if latest:
            return {"APPROVED": "APPROVED", "REJECTED": "REJECTED", "DEFERRED": "DEFERRED",
                    "ESCALATED": "ESCALATED", "FAILED": "AGENT_FAILED"}.get(latest["status"], "NOT_ANALYZED")
        return "NOT_ANALYZED"

    def review_status_map(self) -> dict[str, str]:
        return {lid: self._loan_review_status(lid) for lid in self.evaluation.results}

    # ---- portfolio ---------------------------------------------------------------------
    def portfolio_summary(self) -> dict:
        with self.lock:
            kpis = medallion.portfolio_kpis(self.evaluation, list(self.ops.recommendations.values()),
                                       list(self.ops.actions.values()))
            return {**kpis, "health_segments": medallion.health_segments(self.evaluation),
                    "processing_date": self.evaluation.processing_date.isoformat(),
                    "refresh_cycle": self.ops.refresh_cycle, "versions": self.settings.versions(),
                    "evaluation_ms": round(self.evaluation.duration_ms, 1), "synthetic_data": True}

    def portfolio_loans(self, **filters) -> list[dict]:
        with self.lock:
            status = self.review_status_map()
            rows = []
            for r in self.evaluation.results.values():
                rows.append({
                    "loan_id": r["loan_id"], "borrower_display_name": r["borrower_display_name"],
                    "property_state": r["property_state"], "property_county": r["property_county"],
                    "portfolio_id": r["portfolio_id"], "current_balance": r["current_balance"],
                    "payment_status": r["payment_status"], "days_delinquent": r["days_delinquent"],
                    "loan_status": r["loan_status"], "foreclosure_status": r["foreclosure_status"],
                    "current_milestone": r["current_milestone"], "effective_followup_date": r["effective_followup_date"],
                    "health_segment": r["health_segment"], "primary_condition": r["primary_condition"],
                    "attention_score": r["attention_score"], "priority": r["priority"],
                    "specialist_name": r["specialist_name"], "agent_status": status[r["loan_id"]],
                    "is_active": r["is_active"],
                })
        mapping = {"state": "property_state", "portfolio": "portfolio_id", "loan_status": "loan_status",
                   "payment_status": "payment_status", "foreclosure_status": "foreclosure_status",
                   "milestone": "current_milestone", "health": "health_segment", "priority": "priority",
                   "specialist": "specialist_name", "agent_status": "agent_status", "condition": "primary_condition"}
        for key, col in mapping.items():
            value = filters.get(key)
            if value:
                wanted = {v.strip() for v in str(value).split(",")}
                rows = [r for r in rows if str(r[col]) in wanted]
        search = (filters.get("search") or "").strip().lower()
        if search:
            rows = [r for r in rows if search in " ".join(str(r[c]) for c in (
                "loan_id", "borrower_display_name", "property_state", "property_county")).lower()]
        limit = int(filters.get("limit") or 2000)
        return rows[:limit]

    def priority_queue(self, priority: str | None = None, condition: str | None = None,
                       review_status: str | None = None, specialist: str | None = None, limit: int = 200) -> list[dict]:
        with self.lock:
            rows = medallion.priority_queue_rows(self.evaluation, list(self.ops.recommendations.values()),
                                            self.review_status_map())
        for value, col in ((priority, "priority"), (condition, "primary_condition"),
                           (review_status, "review_status"), (specialist, "specialist_name")):
            if value:
                wanted = {v.strip() for v in str(value).split(",")}
                rows = [r for r in rows if str(r[col]) in wanted]
        return rows[:limit]

    def briefing_facts(self) -> list[dict]:
        with self.lock:
            return medallion.briefing_facts(self.evaluation, list(self.ops.recommendations.values()),
                                       list(self.ops.actions.values()))

    # ---- loans ---------------------------------------------------------------------------
    def loan_detail(self, loan_id: str) -> dict:
        with self.lock:
            lid = self._require_loan(loan_id)
            facts = self.evaluation.facts[lid]
            ctx = self.tool_ctx
            from src import tools
            pending = tools.check_pending_action(ctx, lid)["pending_actions"]
            ops_actions = sorted((a for a in self.ops.actions.values() if a["loan_id"] == lid),
                                 key=lambda a: str(a.get("approved_at")), reverse=True)
            return {
                "loan": tools.get_loan_context(ctx, lid),
                "state": self.evaluation.results[lid],
                "parties": tools.get_assigned_party(ctx, lid),
                "milestone_rule": tools.get_milestone_rule(ctx, facts.current_milestone.get("milestone_type"))
                if facts.current_milestone else None,
                "pending_actions": pending,
                "actions": ops_actions,
                "latest_verification": facts.latest_verification,
                "review_status": self._loan_review_status(lid),
                "milestones": [{k: (v.isoformat() if isinstance(v, date) else v) for k, v in row.items()}
                               for row in _milestones(facts)],
                "synthetic_data": True,
            }

    def loan_events(self, loan_id: str, include_payments: bool = False) -> list[dict]:
        with self.lock:
            lid = self._require_loan(loan_id)
            facts = self.evaluation.facts[lid]
            state = self.evaluation.results[lid]
            P = self.evaluation.processing_date
            lookahead = (facts.rule or {}).get("lookahead_days") or 7
            verified_refs = {a["action_id"] for a in facts.actions
                             if facts.verifications[a["action_id"]]["verification_status"] == "VERIFIED"}
            current_id = (facts.current_milestone or {}).get("event_id")
            rows = []
            for ev in facts.events:
                if ev.get("event_type") == "PAYMENT_RECEIVED" and not include_payments:
                    continue
                fu = _as_date(ev.get("followup_date"))
                display = "HISTORY"
                if ev.get("event_type") == "MILESTONE":
                    display = "CURRENT" if ev["event_id"] == current_id and not facts.milestone_complete else "COMPLETED"
                    if ev["event_id"] == current_id and facts.milestone_complete:
                        display = "COMPLETED"
                elif ev.get("status") == "OPEN" and ev.get("is_followup_type") and fu:
                    days = (fu - P).days
                    display = "OVERDUE" if days < 0 else "DUE" if days == 0 else "UPCOMING" if days <= lookahead else "SCHEDULED"
                elif ev.get("status") == "COMPLETED":
                    display = "COMPLETED" if ev.get("event_type") not in ("PAYMENT_RECEIVED", "NOTE") else "HISTORY"
                note = ev.get("event_note") or ""
                if ev.get("source") == "SERVICING_SYSTEM_ADAPTER" and any(f"[ref {a}]" in note for a in verified_refs):
                    display = "VERIFIED"
                rows.append({"event_id": ev["event_id"], "event_type": ev.get("event_type"),
                             "milestone_type": ev.get("milestone_type"),
                             "event_date": _iso(ev.get("event_date")), "followup_date": _iso(ev.get("followup_date")),
                             "completed_date": _iso(ev.get("completed_date")), "status": ev.get("status"),
                             "display_state": display, "source": ev.get("source"), "event_note": note})
            # Proposed and in-flight items that are not (yet) in the source.
            for rec in self.ops.recommendations_for(lid):
                if rec.get("status") == "PENDING_REVIEW" and (rec.get("proposed_event") or {}).get("creates_event"):
                    pe = rec["proposed_event"]
                    rows.append({"event_id": rec["recommendation_id"], "event_type": pe.get("event_type"),
                                 "milestone_type": pe.get("milestone_type"), "event_date": pe.get("event_date"),
                                 "followup_date": pe.get("followup_date"), "completed_date": None,
                                 "status": "PROPOSED", "display_state": "PROPOSED", "source": "AGENT_RECOMMENDATION",
                                 "event_note": pe.get("event_note") or ""})
                    break
            for a in facts.actions:
                v = facts.verifications[a["action_id"]]["verification_status"]
                if v in ("PENDING", "FAILED", "NOT_FOUND"):
                    rows.append({"event_id": a["action_id"], "event_type": a.get("event_type"),
                                 "milestone_type": a.get("milestone_type") or state["current_milestone"],
                                 "event_date": _iso(a.get("event_date")), "followup_date": _iso(a.get("followup_date")),
                                 "completed_date": None, "status": a.get("status"),
                                 "display_state": ("APPROVED" if a.get("status") == "APPROVED" else "SUBMITTED")
                                 if v == "PENDING" else "FAILED",
                                 "source": "APPROVED_ACTION", "event_note": a.get("note") or a.get("failure_reason") or ""})
            rows.sort(key=lambda r: (r["event_date"] or "", r["event_id"]))
            return rows

    def loan_recommendations(self, loan_id: str) -> list[dict]:
        with self.lock:
            lid = self._require_loan(loan_id)
            return self.ops.recommendations_for(lid)

    def activity(self, loan_id: str | None = None, run_id: str | None = None, limit: int = 300) -> list[dict]:
        with self.lock:
            rows = self.ops.activity
            if loan_id:
                rows = [r for r in rows if r.get("loan_id") == loan_id.strip().upper()]
            if run_id:
                rows = [r for r in rows if r.get("run_id") == run_id]
            return list(reversed(rows))[:limit]

    # ---- agent ---------------------------------------------------------------------------
    def analyze_loan(self, loan_id: str, user_id: str = "SPEC-01", agent_mode: str | None = None) -> dict:
        with self.lock:
            lid = self._require_loan(loan_id)
            ctx = self.tool_ctx
        buffer = ActivityBuffer("agent")
        run = RunContext(run_id=new_run_id(), tool_ctx=ctx, settings=self.settings, user_id=user_id,
                         on_activity=buffer)
        agent = self.agent(agent_mode)
        with trace_span("assess_loan", {"loan_id": lid, "run_id": run.run_id, "agent": agent.agent_version}):
            result = agent.assess_loan(lid, run)
        rec = result.get("recommendation")
        with self.lock:
            if rec is not None:
                superseded = []
                for old in self.ops.recommendations_for(lid):
                    if old.get("status") == "PENDING_REVIEW":
                        old["status"] = "SUPERSEDED"
                        superseded.append(old)
                self.ops.recommendations[rec["recommendation_id"]] = rec
                self.repository.upsert("ops_recommendations", superseded + [rec])
            self._persist_activity(buffer)
        state = self.evaluation.results[lid]
        return {
            "run_id": run.run_id, "mode": "assess", "agent_mode": result.get("agent_mode"),
            "answer": result.get("answer"), "loan_id": lid,
            "condition": state["primary_condition"], "secondary_conditions": state["secondary_conditions"],
            "priority": state["priority"], "score": state["attention_score"], "score_drivers": state["score_drivers"],
            "evidence": (rec or {}).get("evidence", []), "recommendation": rec,
            "confidence": (rec or {}).get("confidence"), "uncertainty": (rec or {}).get("uncertainty"),
            "missing_information": (rec or {}).get("missing_information", []),
            "tool_calls": result.get("tool_calls", []), "requires_human_approval": True,
            "error": result.get("error"), "synthetic_data": True,
        }

    def ask(self, question: str, loan_id: str | None = None, user_id: str = "SPEC-01",
            agent_mode: str | None = None) -> dict:
        with self.lock:
            lid = self._require_loan(loan_id) if loan_id else None
            ctx = self.tool_ctx
        buffer = ActivityBuffer("agent")
        run = RunContext(run_id=new_run_id("ASK"), tool_ctx=ctx, settings=self.settings, user_id=user_id,
                         on_activity=buffer)
        run.step("question_received", lid, question[:300])
        result = self.agent(agent_mode).answer_question(question, lid, run)
        run.step("answer_generated", lid, (result.get("answer") or "")[:300])
        with self.lock:
            self._persist_activity(buffer)
        out = {"run_id": run.run_id, "mode": "ask", "agent_mode": result.get("agent_mode"),
               "answer": result.get("answer"), "loan_id": lid, "tool_calls": result.get("tool_calls", []),
               "requires_human_approval": False, "synthetic_data": True}
        if lid:
            state = self.evaluation.results[lid]
            out.update({"condition": state["primary_condition"], "priority": state["priority"],
                        "score": state["attention_score"], "score_drivers": state["score_drivers"]})
        return out

    def briefing(self, agent_mode: str | None = None) -> dict:
        facts = self.briefing_facts()
        buffer = ActivityBuffer("agent")
        run = RunContext(run_id=new_run_id("BRF"), tool_ctx=self.tool_ctx, settings=self.settings, on_activity=buffer)
        result = self.agent(agent_mode).portfolio_briefing(facts, run)
        with self.lock:
            self._persist_activity(buffer)
        return {"run_id": run.run_id, "facts": facts, **result}

    def triage_candidates(self, limit: int = 10) -> list[str]:
        """Highest-scoring attention loans without a current LLM recommendation (demo spotlight loans excluded)."""
        exclude = set(self.settings.demo_scenarios.get("baseline_recommendations", {}).get("exclude_loans", []))
        ids = []
        for r in sorted(self.evaluation.active_results(), key=lambda r: (-r["attention_score"], r["loan_id"])):
            if not r["needs_attention"] or r["loan_id"] in exclude:
                continue
            latest = next((x for x in self.ops.recommendations_for(r["loan_id"]) if x.get("status") != "SUPERSEDED"),
                          None)
            if latest and latest.get("agent_mode") == "llm" and latest.get("state_fingerprint") == r["state_fingerprint"]:
                continue
            ids.append(r["loan_id"])
            if len(ids) >= limit:
                break
        return ids

    def triage(self, loan_ids: list[str] | None = None, limit: int = 10, agent_mode: str | None = None,
               max_workers: int = 4, actor: str = "agent") -> dict:
        """Run the agent on several loans in parallel and persist the proposals (awaiting human review)."""
        from concurrent.futures import ThreadPoolExecutor

        with self.lock:
            ctx = self.tool_ctx
            ids = [self._require_loan(lid) for lid in loan_ids] if loan_ids else self.triage_candidates(limit)
        agent = self.agent(agent_mode)

        def assess(lid: str):
            buffer = ActivityBuffer(actor)
            run = RunContext(run_id=new_run_id("TRI"), tool_ctx=ctx, settings=self.settings, on_activity=buffer)
            try:
                result = agent.assess_loan(lid, run)
            except Exception as exc:  # noqa: BLE001 - a failed loan never blocks the batch
                result = {"recommendation": None, "error": f"{type(exc).__name__}: {exc}", "agent_mode": agent.mode}
            return lid, result, buffer

        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
            outcomes = list(pool.map(assess, ids))
        with self.lock:
            changed: dict[str, dict] = {}
            activity: list[dict] = []
            rows = []
            for lid, result, buffer in outcomes:
                rec = result.get("recommendation")
                if rec:
                    for old in self.ops.recommendations_for(lid):
                        if old.get("status") == "PENDING_REVIEW":
                            old["status"] = "SUPERSEDED"
                            changed[old["recommendation_id"]] = old
                    self.ops.recommendations[rec["recommendation_id"]] = rec
                    changed[rec["recommendation_id"]] = rec
                activity.extend(buffer.records)
                state = self.evaluation.results[lid]
                rows.append({"loan_id": lid, "priority": state["priority"], "condition": state["primary_condition"],
                             "agent_mode": result.get("agent_mode"),
                             "recommended_action": (rec or {}).get("recommended_action"),
                             "confidence": (rec or {}).get("confidence"), "error": result.get("error")})
            self.repository.upsert("ops_recommendations", list(changed.values()))
            if activity:
                self.ops.activity.extend(activity)
                self.repository.upsert("ops_agent_activity", activity)
        return {"analyzed": len(rows), "results": rows, "seconds": round(time.perf_counter() - started, 1)}

    def reload(self) -> dict:
        """Re-read source and operational state (e.g. after the backend workflow ran)."""
        self.repository.flush()
        self.load()
        return {"reloaded_at": self.loaded_at, "recommendations": len(self.ops.recommendations),
                "refresh_cycle": self.ops.refresh_cycle}

    def generate_baseline_recommendations(self) -> int:
        """Deterministic recommendations for attention candidates (no LLM cost)."""
        exclude = set(self.settings.demo_scenarios.get("baseline_recommendations", {}).get("exclude_loans", []))
        agent = self.agent("deterministic")
        ctx = self.tool_ctx
        recs = []
        for r in self.evaluation.active_results():
            if not r["needs_attention"] or r["loan_id"] in exclude:
                continue
            run = RunContext(run_id=new_run_id("BASE"), tool_ctx=ctx, settings=self.settings)
            rec = agent.assess_loan(r["loan_id"], run).get("recommendation")
            if rec:
                recs.append(rec)
        for rec in recs:
            self.ops.recommendations[rec["recommendation_id"]] = rec
        self.repository.upsert("ops_recommendations", recs)
        self._activity("pipeline", "baseline_recommendations", None, f"Generated {len(recs)} baseline recommendations")
        return len(recs)

    # ---- review, action, refresh ----------------------------------------------------------
    def decide(self, recommendation_id: str, request) -> dict:
        with self.lock:
            rec = self.ops.recommendations.get(recommendation_id)
            if rec is None:
                raise NotFound("RECOMMENDATION_NOT_FOUND")
            decision, draft, validation = resolve_decision(rec, request, self.evaluation)
            action = None
            if draft is not None and draft.get("creates_event"):
                mode = self.adapter.mode_for(rec["loan_id"]) if hasattr(self.adapter, "mode_for") else "UNKNOWN"
                action = build_action(rec, decision, draft, request.reviewer_id, mode)
                self.ops.actions[action["action_id"]] = action
                self.repository.upsert("ops_actions", [action])
                if self.repository.backend == "local":
                    write_outbound_file(self.settings.path("outbound_dir"), action)
            rec = dict(rec, status=STATUS_FOR_DECISION[decision["decision"]])
            self.ops.recommendations[rec["recommendation_id"]] = rec
            self.ops.decisions[decision["decision_id"]] = decision
            self.repository.upsert("ops_reviewer_decisions", [decision])
            self.repository.upsert("ops_recommendations", [rec])
            self._activity("reviewer", f"decision_{decision['decision'].lower()}", rec["loan_id"],
                           f"{request.reviewer_id} ({request.reviewer_role}) {decision['decision']} "
                           f"{decision.get('final_action') or decision['original_action']}"
                           + (f" -> action {action['action_id']}" if action else ""), run_id=rec.get("run_id"))
            self._reevaluate()
            return {"decision": decision, "recommendation": rec, "action": action, "validation": validation}

    def get_action(self, action_id: str) -> dict:
        with self.lock:
            action = self.ops.actions.get(action_id)
            if action is None:
                raise NotFound("ACTION_NOT_FOUND")
            facts = self.evaluation.facts[action["loan_id"]]
            return {**action, "verification": facts.verifications.get(action_id)}

    def submit_action(self, action_id: str) -> dict:
        with self.lock:
            action = self.ops.actions.get(action_id)
            if action is None:
                raise NotFound("ACTION_NOT_FOUND")
            updated, sor_rows = submit(action, self.adapter, self.evaluation, self.ops.refresh_cycle)
            self.ops.actions[action_id] = updated
            self.repository.upsert("ops_actions", [updated])
            if sor_rows:
                self.ops.sor_events.extend(sor_rows)
                self.repository.upsert("sor_servicing_events", sor_rows)
            self._activity("adapter", "adapter_submit", updated["loan_id"],
                           f"{action_id} {updated['status']} via synthetic adapter ({updated['adapter_mode']}): "
                           f"{updated['adapter_result'].get('message')}", success=updated["status"] == "SUBMITTED")
            self._reevaluate()
            return self.get_action(action_id)

    # ---- next step: propose, confirm, schedule (human in the loop) ---------------------------
    def next_step(self, loan_id: str, action_type: str | None = None) -> dict:
        """Preview of the next servicing step: allowed actions and the event a chosen action would create."""
        from src import tools as t

        with self.lock:
            lid = self._require_loan(loan_id)
            ctx = self.tool_ctx
            state = self.evaluation.results[lid]
            allowed = state["allowed_actions"]
            action = (action_type or "").upper()
            if action not in allowed:
                action = state["default_action"]
            draft = t.prepare_followup_event(ctx, lid, action)
            pending = t.check_pending_action(ctx, lid)["pending_actions"]
            return {"loan_id": lid, "action_type": action, "allowed_actions": allowed, "event": draft,
                    "pending_actions": pending, "default_action": state["default_action"]}

    def schedule_next_step(self, loan_id: str, action_type: str, followup_date: str | None = None,
                           note: str | None = None, outreach: str | None = None, reviewer_id: str = "SPEC-01",
                           reviewer_role: str = "LOAN_SERVICING_SPECIALIST", source: str = "loan view",
                           send: bool = True) -> dict:
        """A specialist confirms a proposed step: record the decision, re-validate, create the event, and (optionally)
        send it to the servicing system. Returns the decision and the action."""
        from src.models import DecisionEdits, DecisionRequest

        lid = self._require_loan(loan_id)
        proposal = self.analyze_loan(lid, user_id=reviewer_id, agent_mode="deterministic")["recommendation"]
        if proposal is None:
            raise InvalidState("Could not prepare a proposal for this loan")
        edits = DecisionEdits(action_type=action_type if action_type != proposal["recommended_action"] else None,
                              followup_date=followup_date, note=note, outreach=outreach)
        changed = bool(edits.action_type) or any(
            v is not None and v != proposal.get(k) for k, v in (("recommended_followup_date", followup_date),
                                                               ("suggested_note", note),
                                                               ("suggested_outreach", outreach)))
        result = self.decide(proposal["recommendation_id"], DecisionRequest(
            decision="EDIT" if changed else "APPROVE", reviewer_id=reviewer_id, reviewer_role=reviewer_role,
            reason=f"Confirmed in the {source}", edits=edits if changed else None))
        action = result.get("action")
        if action and send:
            action = self.submit_action(action["action_id"])
        return {"decision": result["decision"], "action": action}

    def refresh(self) -> dict:
        with self.lock:
            cycle = self.ops.refresh_cycle + 1
            self.ops.runtime["refresh_cycle"] = str(cycle)
            self.repository.upsert("ops_runtime_state", [{"state_key": "refresh_cycle", "state_value": str(cycle),
                                                          "updated_at": utcnow()}])
            self._reevaluate()
            results, updated = verify_submitted_actions(self.evaluation, self.ops.actions, cycle)
            for action in updated:
                self.ops.actions[action["action_id"]] = action
            for res in results:
                self.ops.verification_results[res["verification_id"]] = res
            self.repository.upsert("ops_actions", updated)
            self.repository.upsert("ops_verification_results", results)
            if updated:
                self._reevaluate()
            counts: dict[str, int] = {}
            for res in results:
                counts[res["verification_status"]] = counts.get(res["verification_status"], 0) + 1
            returned = [r["action_id"] for r in results if r["verification_status"] in FAILURE_STATUSES]
            self._activity("system", "source_refresh", None,
                           f"Cycle {cycle}: verified {len(results)} submitted action(s) {counts}")
            return {"refresh_cycle": cycle, "verification": counts, "returned_to_queue": returned,
                    "evaluated_loans": len(self.evaluation.results), "results": results}

    def pending_actions(self) -> list[dict]:
        with self.lock:
            rows = []
            for v in self.evaluation.all_verifications():
                if v["verification_status"] == "PENDING":
                    ops = self.ops.actions.get(v["action_id"], {})
                    rows.append({**{k: _iso(x) for k, x in v.items()}, "status": ops.get("status") or v["action_status"],
                                 "origin": "APP" if ops else "HISTORY"})
            return rows

    def verification_results(self) -> list[dict]:
        with self.lock:
            lookback = self.settings.thresholds.get("failure_lookback_days", 30)
            P = self.evaluation.processing_date
            rows = []
            for v in self.evaluation.all_verifications():
                event_day = _as_date(v.get("action_event_date"))
                if v["action_id"] in self.ops.actions or (event_day and (P - event_day).days <= lookback):
                    rows.append({**{k: _iso(x) for k, x in v.items()},
                                 "origin": "APP" if v["action_id"] in self.ops.actions else "HISTORY",
                                 "cycle": self.ops.refresh_cycle})
            return sorted(rows, key=lambda r: str(r.get("submitted_at")), reverse=True)

    # ---- evaluation ----------------------------------------------------------------------
    def baseline_evaluation(self) -> PortfolioEvaluation:
        """Evaluation of the source snapshot before any live demo actions (scenario ground truth applies here)."""
        if self._baseline is None:
            self._baseline = evaluate_portfolio(self.source, self.settings)
        return self._baseline

    def manifest_path(self):
        return self.settings.path("generated_dir") / "demo_scenario_manifest.csv"

    def run_agent_evaluation(self, agent_mode: str = "deterministic") -> dict:
        manifest = evaluation.load_manifest(self.manifest_path())
        baseline = self.baseline_evaluation()
        ctx = ToolContext(baseline, OperationalState(), self.settings)
        agent = self.agent(agent_mode)
        recs = {}
        for m in manifest:
            run = RunContext(run_id=new_run_id("EVAL"), tool_ctx=ctx, settings=self.settings)
            result = agent.assess_loan(m["loan_id"], run)
            if result.get("recommendation"):
                recs[m["loan_id"]] = result["recommendation"]
        self._agent_eval = {"agent_mode": agent_mode, "run_at": utcnow(),
                            **evaluation.evaluate_agent(manifest, recs, baseline)}
        self._activity("evaluation", "agent_evaluation", None,
                       f"Agent evaluation ({agent_mode}): {self._agent_eval['metrics']}")
        return self._agent_eval

    def evaluation_summary(self) -> dict:
        manifest = evaluation.load_manifest(self.manifest_path())
        with self.lock:
            rule = evaluation.evaluate_rules(manifest, self.baseline_evaluation())
            history = self.source.reviewer_decisions.to_dict("records")
            live = list(self.ops.decisions.values())
            verif = [v for v in self.evaluation.all_verifications()]
        if self._agent_eval is None:
            self.run_agent_evaluation("deterministic")
        return {
            "rule_metrics": rule["metrics"], "scenarios": rule["rows"],
            "agent_metrics": self._agent_eval["metrics"], "agent_rows": self._agent_eval["rows"],
            "agent_mode": self._agent_eval["agent_mode"], "agent_run_at": self._agent_eval["run_at"],
            "reviewer_metrics": {"synthetic_history": evaluation.reviewer_metrics(history),
                                 "live": evaluation.reviewer_metrics(live),
                                 "combined": evaluation.reviewer_metrics(history + live)},
            "verification_metrics": evaluation.verification_metrics(verif),
            "synthetic": True,
        }

    # ---- operations ----------------------------------------------------------------------
    def reset_demo(self) -> dict:
        if not self.settings.demo_mode:
            raise InvalidState("Reset is only available in demo mode")
        with self.lock:
            self.repository.reset_ops()
            self.ops = OperationalState()
            self._events_key = None
            self._agent_eval = None
            outbound = self.settings.path("outbound_dir")
            if self.repository.backend == "local" and outbound.exists():
                for f in outbound.glob("ACT-*.json"):
                    f.unlink()
            self._reevaluate()
            count = self.generate_baseline_recommendations()
            return {"reset": True, "baseline_recommendations": count, "refresh_cycle": 0}

    def health(self) -> dict:
        return {"status": "ok" if self.evaluation is not None else "loading", "backend": self.repository.backend,
                "agent_mode": self.agent_mode, "model_endpoint": self.settings.agent.get("model_endpoint"),
                "processing_date": self.settings.processing_date.isoformat(),
                "refresh_cycle": self.ops.refresh_cycle, "demo_mode": self.settings.demo_mode,
                "loaded_at": self.loaded_at,
                "write_errors": list(getattr(self.repository, "write_errors", []))[-5:]}


def _iso(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:  # noqa: BLE001
            return str(value)
    if isinstance(value, float) and value != value:
        return None
    return value


def _milestones(facts) -> list[dict]:
    current_id = (facts.current_milestone or {}).get("event_id")
    return [{"milestone_type": e.get("milestone_type"), "event_id": e["event_id"],
             "event_date": _iso(e.get("event_date")), "followup_date": _iso(e.get("followup_date")),
             "completed_date": _iso(e.get("completed_date")), "status": e.get("status"),
             "is_current": e["event_id"] == current_id} for e in facts.milestone_events]
