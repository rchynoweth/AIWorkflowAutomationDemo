"""Agent tools: 29 deterministic, read-only tools, their registry and executor, and the Unity Catalog
SQL functions used by the deployed agent."""
from __future__ import annotations

import inspect
import json
import time
import typing
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, create_model, ValidationError

from src import medallion
from src.rules import (
    _as_date,
    calculate_followup_date as _calc_followup,
    check_existing_event as _check_existing,
    compare_fields,
    FAILURE_STATUSES,
    find_candidate_events,
    LoanFacts,
    PortfolioEvaluation,
    prepare_event,
    validate_proposed_event as _validate,
)
from src.storage import OperationalState


# ====================================================================================================
# Deterministic servicing tools used by the Loan Servicing Agent (docs/AGENT_TOOLS.md)
# ====================================================================================================

class ToolError(Exception):
    """Raised for expected tool failures (e.g. LOAN_NOT_FOUND)."""


@dataclass
class ToolContext:
    evaluation: PortfolioEvaluation
    ops: OperationalState
    settings: Any

    @property
    def processing_date(self) -> date:
        return self.evaluation.processing_date

    def facts(self, loan_id: str) -> LoanFacts:
        facts = self.evaluation.facts.get((loan_id or "").strip().upper())
        if facts is None:
            raise ToolError("LOAN_NOT_FOUND")
        return facts

    def result(self, loan_id: str) -> dict:
        self.facts(loan_id)
        return self.evaluation.results[loan_id.strip().upper()]


def _s(value: Any) -> Any:
    """JSON-safe scalar."""
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:  # noqa: BLE001
            return str(value)
    if isinstance(value, float) and value != value:
        return None
    return value


def _event(ev: dict) -> dict:
    return {k: _s(ev.get(k)) for k in ("event_id", "event_type", "milestone_type", "event_date", "followup_date",
                                       "completed_date", "status", "source", "event_note")}


# ---- loan context and history -------------------------------------------------------------
def get_loan_context(ctx: ToolContext, loan_id: str) -> dict:
    f = ctx.facts(loan_id)
    loan = f.loan
    keys = ["loan_id", "borrower_display_name", "property_city", "property_state", "property_county",
            "portfolio_id", "original_balance", "current_balance", "loan_status", "payment_status", "days_delinquent",
            "foreclosure_status", "boarding_date", "assigned_specialist_id", "specialist_name",
            "assigned_attorney_vendor_id", "party_name", "party_type", "is_active", "synthetic_data"]
    return {k: _s(loan.get(k)) for k in keys}


def get_event_history(ctx: ToolContext, loan_id: str, limit: int = 50, include_payments: bool = False) -> dict:
    f = ctx.facts(loan_id)
    events = [e for e in f.events if include_payments or e.get("event_type") != "PAYMENT_RECEIVED"]
    return {"loan_id": f.loan_id, "event_count": len(events), "events": [_event(e) for e in events[-limit:]]}


def get_current_milestone(ctx: ToolContext, loan_id: str) -> dict:
    f = ctx.facts(loan_id)
    if not f.current_milestone:
        return {"loan_id": f.loan_id, "has_servicing_track": False, "rule_id": "RULE-MILESTONE-001"}
    cm = f.current_milestone
    return {"loan_id": f.loan_id, "has_servicing_track": True, **_event(cm),
            "milestone_sequence": cm.get("milestone_sequence"), "rule_found": f.rule_found,
            "rule_id": "RULE-MILESTONE-001"}


def check_milestone_completion(ctx: ToolContext, loan_id: str) -> dict:
    f = ctx.facts(loan_id)
    cm = f.current_milestone or {}
    return {"loan_id": f.loan_id, "milestone_type": cm.get("milestone_type"), "is_complete": f.milestone_complete,
            "completed_date": _s(_as_date(cm.get("completed_date"))), "status": cm.get("status"),
            "conflicts": f.milestone_conflicts, "rule_ids": ["RULE-MILESTONE-002", "RULE-DATA-002"]}


def check_followup_status(ctx: ToolContext, loan_id: str) -> dict:
    f = ctx.facts(loan_id)
    r = ctx.result(loan_id)
    followup_codes = [c["code"] for c in r["raw_conditions"]
                      if c["code"] in ("OVERDUE", "DUE", "UPCOMING", "MISSING_FOLLOWUP")]
    return {"loan_id": f.loan_id, "milestone_type": r["current_milestone"],
            "effective_followup_date": r["effective_followup_date"],
            "source_event_id": f.effective_followup_event_id, "days_to_followup": f.days_to_followup,
            "days_overdue": f.days_overdue, "lookahead_days": (f.rule or {}).get("lookahead_days"),
            "followup_condition": followup_codes[0] if followup_codes else "ON_TRACK_OR_NOT_APPLICABLE",
            "open_followup_events": len(f.open_followups),
            "rule_ids": ["RULE-FOLLOWUP-001", "RULE-FOLLOWUP-002", "RULE-FOLLOWUP-003", "RULE-FOLLOWUP-004",
                         "RULE-FOLLOWUP-005"]}


def calculate_days_to_followup(ctx: ToolContext, loan_id: str | None = None, followup_date: str | None = None) -> dict:
    if followup_date:
        fu = _as_date(followup_date)
    else:
        fu = ctx.facts(loan_id).effective_followup_date
    if fu is None:
        return {"followup_date": None, "days_to_followup": None, "days_overdue": None}
    days = (fu - ctx.processing_date).days
    return {"followup_date": fu.isoformat(), "processing_date": ctx.processing_date.isoformat(),
            "days_to_followup": days, "days_overdue": max(0, -days)}


def get_next_required_milestone(ctx: ToolContext, loan_id: str) -> dict:
    f = ctx.facts(loan_id)
    nxt = f.next_milestone_type
    rule = ctx.evaluation.ctx.rules_by_type.get(nxt or "", {})
    return {"loan_id": f.loan_id, "current_milestone": (f.current_milestone or {}).get("milestone_type"),
            "next_milestone_type": nxt, "exists_already": f.next_milestone_exists,
            "default_followup_days": rule.get("default_followup_days"), "rule_id": "RULE-MILESTONE-003"}


def get_milestone_rule(ctx: ToolContext, milestone_type: str) -> dict:
    mt = (milestone_type or "").strip().upper()
    rule = ctx.evaluation.ctx.rules_by_type.get(mt)
    if rule is None:
        inactive = ctx.evaluation.ctx.all_rules_by_type.get(mt)
        return {"milestone_type": mt, "found": False, "inactive_rule_exists": inactive is not None,
                "rule_id": "RULE-DATA-001"}
    return {"found": True, **{k: _s(v) for k, v in rule.items() if k != "dq_issues"}, "synthetic_assumption": True}


# ---- duplicate, pending, review checks ----------------------------------------------------
def check_existing_event(ctx: ToolContext, loan_id: str, event_type: str, milestone_type: str | None = None,
                         action_type: str | None = None) -> dict:
    f = ctx.facts(loan_id)
    mt = milestone_type or (f.current_milestone or {}).get("milestone_type")
    return {"loan_id": f.loan_id, "event_type": event_type, "milestone_type": mt,
            **_check_existing(f, event_type, mt, action_type, ctx.evaluation.ctx)}


def check_pending_recommendation(ctx: ToolContext, loan_id: str) -> dict:
    f = ctx.facts(loan_id)
    pending = [r for r in ctx.ops.recommendations_for(f.loan_id) if r.get("status") in ("PENDING_REVIEW", "DEFERRED")]
    return {"loan_id": f.loan_id, "pending_recommendations": [
        {k: r.get(k) for k in ("recommendation_id", "status", "recommended_action", "created_at", "agent_mode")}
        for r in pending], "has_pending": bool(pending)}


def check_pending_action(ctx: ToolContext, loan_id: str) -> dict:
    f = ctx.facts(loan_id)
    pending = []
    for a in f.actions:
        v = f.verifications[a["action_id"]]
        if v["verification_status"] == "PENDING":
            pending.append({"action_id": a["action_id"], "action_type": a.get("action_type"),
                            "status": a.get("status"), "verification_status": "PENDING",
                            "event_date": _s(a.get("event_date")), "followup_date": _s(a.get("followup_date"))})
    return {"loan_id": f.loan_id, "pending_actions": pending, "has_pending": bool(pending),
            "rule_id": "RULE-PENDING-001"}


def check_previous_rejection(ctx: ToolContext, loan_id: str) -> dict:
    f = ctx.facts(loan_id)
    rejections = [{"decision_id": d["decision_id"], "original_action": d.get("original_action"),
                   "reason": d.get("reason"), "decided_at": _s(d.get("decided_at"))}
                  for d in f.decisions if d.get("decision") == "REJECT"]
    return {"loan_id": f.loan_id, "rejections": rejections[-5:], "rejected_actions_in_lookback": f.prior_rejected_actions,
            "lookback_days": ctx.settings.thresholds.get("prior_rejection_lookback_days"),
            "rule_id": "RULE-REVIEW-001"}


def get_assigned_party(ctx: ToolContext, loan_id: str) -> dict:
    f = ctx.facts(loan_id)
    ectx = ctx.evaluation.ctx
    spec = ectx.specialists_by_id.get(f.loan.get("assigned_specialist_id") or "", {})
    party = ectx.parties_by_id.get(f.loan.get("assigned_attorney_vendor_id") or "", {})
    return {"loan_id": f.loan_id,
            "specialist": {"id": spec.get("specialist_id"), "name": spec.get("display_name"),
                           "team": spec.get("team"), "active": bool(spec.get("active"))},
            "party": {"id": party.get("party_id"), "name": party.get("display_name"),
                      "type": party.get("party_type"), "active": bool(party.get("active"))} if party else None,
            "required_party_type": f.required_party_type, "party_ok": f.party_ok, "specialist_ok": f.specialist_ok,
            "rule_ids": ["RULE-DATA-003", "RULE-DATA-004"]}


# ---- escalation, scoring, actions ----------------------------------------------------------
def calculate_escalation_state(ctx: ToolContext, loan_id: str) -> dict:
    r = ctx.result(loan_id)
    return {"loan_id": r["loan_id"], "escalation_state": r["escalation_state"],
            "escalation_reasons": r["escalation_reasons"], "required_role": r["required_role"],
            "allowed_actions": r["allowed_actions"], "health_segment": r["health_segment"],
            "escalation_version": ctx.settings.escalation_version}


def calculate_loan_attention_score(ctx: ToolContext, loan_id: str) -> dict:
    r = ctx.result(loan_id)
    return {"loan_id": r["loan_id"], "score": r["attention_score"], "priority": r["priority"],
            "score_drivers": r["score_drivers"], "primary_condition": r["primary_condition"],
            "secondary_conditions": r["secondary_conditions"], "calculated_at": r["calculated_at"],
            "scoring_version": r["scoring_version"]}


def get_attention_score_drivers(ctx: ToolContext, loan_id: str) -> dict:
    r = ctx.result(loan_id)
    drivers = sorted(r["score_drivers"], key=lambda d: d["points"], reverse=True)
    return {"loan_id": r["loan_id"], "score": r["attention_score"], "priority": r["priority"],
            "score_drivers": drivers, "summary": r["top_drivers_text"]}


def get_allowed_actions(ctx: ToolContext, loan_id: str) -> dict:
    r = ctx.result(loan_id)
    return {"loan_id": r["loan_id"], "primary_condition": r["primary_condition"],
            "allowed_actions": r["allowed_actions"], "default_action": r["default_action"],
            "removed_actions": r["removed_actions"], "rule_id": "RULE-ACTIONS-001"}


def calculate_followup_date(ctx: ToolContext, loan_id: str, action_type: str) -> dict:
    f = ctx.facts(loan_id)
    return {"loan_id": f.loan_id, "action_type": action_type, **_calc_followup(action_type, f, ctx.evaluation.ctx)}


def _original_failed_action(f: LoanFacts) -> dict | None:
    for a in reversed(f.actions):
        if f.verifications[a["action_id"]]["verification_status"] in FAILURE_STATUSES:
            return a
    return None


def prepare_followup_event(ctx: ToolContext, loan_id: str, action_type: str, followup_date: str | None = None,
                           note: str | None = None, outreach: str | None = None) -> dict:
    f = ctx.facts(loan_id)
    original = _original_failed_action(f) if action_type == "RETRY_FAILED_ACTION" else None
    return prepare_event(action_type, f, ctx.evaluation.ctx, followup_date, note, outreach, None, original)


def prepare_escalation(ctx: ToolContext, loan_id: str, reason: str | None = None, target_role: str | None = None) -> dict:
    f = ctx.facts(loan_id)
    r = ctx.result(loan_id)
    role = target_role or ("SERVICING_MANAGER" if r["escalation_state"] == "CRITICAL" else "SENIOR_SPECIALIST")
    draft = prepare_event("ESCALATE_TO_SPECIALIST", f, ctx.evaluation.ctx, None,
                          reason or f"Escalation: {r['primary_condition']} ({r['escalation_state']}).", None, role)
    return {**draft, "required_role": role, "escalation_reasons": r["escalation_reasons"]}


def validate_proposed_event(ctx: ToolContext, loan_id: str, action_type: str, event_type: str | None = None,
                            followup_date: str | None = None, note: str | None = None,
                            recommendation_fingerprint: str | None = None) -> dict:
    f = ctx.facts(loan_id)
    draft = prepare_followup_event(ctx, loan_id, action_type, followup_date, note)
    if event_type and draft.get("creates_event"):
        draft["event_type"] = event_type
    return _validate(draft, f, ctx.result(loan_id), ctx.evaluation.ctx, recommendation_fingerprint)


# ---- verification -------------------------------------------------------------------------
def _find_action(ctx: ToolContext, action_id: str) -> tuple[dict, LoanFacts]:
    for f in ctx.evaluation.facts.values():
        for a in f.actions:
            if a["action_id"] == action_id:
                return a, f
    raise ToolError("ACTION_NOT_FOUND")


def verify_servicing_event_created(ctx: ToolContext, action_id: str) -> dict:
    action, f = _find_action(ctx, action_id)
    return {**f.verifications[action_id], "action_type": action.get("action_type")}


def compare_approved_to_actual(ctx: ToolContext, action_id: str) -> dict:
    action, f = _find_action(ctx, action_id)
    candidates = find_candidate_events(action, f.events)
    approved = {k: _s(action.get(k)) for k in ("event_type", "event_date", "followup_date", "milestone_type")}
    return {"action_id": action_id, "approved": approved, "actual": [_event(c) for c in candidates],
            "differences": compare_fields(action, candidates[0]) if len(candidates) == 1 else [],
            "match_count": len(candidates), "rule_id": "RULE-VERIFICATION-002"}


# ---- portfolio tools -----------------------------------------------------------------------
def get_portfolio_health_summary(ctx: ToolContext) -> dict:
    ops_actions = list(ctx.ops.actions.values())
    return {"processing_date": ctx.processing_date.isoformat(),
            **medallion.portfolio_kpis(ctx.evaluation, list(ctx.ops.recommendations.values()), ops_actions),
            "health_segments": medallion.health_segments(ctx.evaluation)}


def get_priority_queue(ctx: ToolContext, limit: int = 20, priority: str | None = None,
                       condition: str | None = None) -> dict:
    rows = medallion.priority_queue_rows(ctx.evaluation, list(ctx.ops.recommendations.values()))
    if priority:
        rows = [r for r in rows if r["priority"] == priority.upper()]
    if condition:
        rows = [r for r in rows if r["primary_condition"] == condition.upper()]
    keep = ("queue_rank", "priority", "loan_id", "primary_condition", "attention_score", "current_milestone",
            "days_overdue", "top_drivers_text", "recommended_action")
    return {"count": len(rows), "rows": [{k: r[k] for k in keep} for r in rows[:limit]]}


def get_portfolio_exceptions(ctx: ToolContext, limit: int = 50) -> dict:
    rows = []
    for r in ctx.evaluation.active_results():
        exc = [c for c in r["raw_conditions"] if c["code"] in ("DATA_EXCEPTION", "DUPLICATE_RISK")]
        if exc:
            rows.append({"loan_id": r["loan_id"], "priority": r["priority"], "conditions": exc})
    return {"count": len(rows), "rows": rows[:limit]}


def get_specialist_workload_summary(ctx: ToolContext) -> dict:
    summary: dict[str, dict] = {}
    for r in ctx.evaluation.active_results():
        key = r["specialist_name"] or "Unassigned"
        s = summary.setdefault(key, {"specialist": key, "assigned": 0, "need_attention": 0, "critical": 0, "high": 0})
        s["assigned"] += 1
        s["need_attention"] += int(r["needs_attention"])
        s["critical"] += int(r["priority"] == "CRITICAL")
        s["high"] += int(r["priority"] == "HIGH")
    return {"specialists": sorted(summary.values(), key=lambda s: -s["need_attention"])}


def get_recommendations_awaiting_approval(ctx: ToolContext, limit: int = 50) -> dict:
    recs = [r for r in ctx.ops.recommendations.values() if r.get("status") == "PENDING_REVIEW"]
    recs.sort(key=lambda r: -int(r.get("attention_score") or 0))
    return {"count": len(recs), "rows": [
        {k: r.get(k) for k in ("recommendation_id", "loan_id", "priority", "attention_score", "recommended_action",
                               "confidence", "created_at", "agent_mode")} for r in recs[:limit]]}


def get_failed_verifications(ctx: ToolContext, limit: int = 50) -> dict:
    rows = [{k: _s(v.get(k)) for k in ("action_id", "loan_id", "action_type", "verification_status", "detail")}
            for v in ctx.evaluation.all_verifications() if v["verification_status"] in FAILURE_STATUSES]
    return {"count": len(rows), "rows": rows[:limit]}


# ====================================================================================================
# Tool registry: typed input models (derived from function signatures), descriptions, and JSON schemas
# ====================================================================================================

DESCRIPTIONS: dict[str, str] = {
    "get_loan_context": "Loan attributes, balances, statuses, portfolio, assigned specialist and party.",
    "get_event_history": "Chronological servicing events for a loan (payments excluded unless requested).",
    "get_current_milestone": "Current servicing milestone per RULE-MILESTONE-001.",
    "check_milestone_completion": "Whether the current milestone is complete and any conflicting dates.",
    "check_followup_status": "Effective follow-up date, days to follow-up, days overdue, follow-up condition.",
    "calculate_days_to_followup": "Days between the processing date and a follow-up date.",
    "get_next_required_milestone": "Configured next milestone and whether it already exists.",
    "get_milestone_rule": "Synthetic milestone rule (follow-up days, look-ahead, overdue action, severity).",
    "check_existing_event": "Open equivalent events or pending actions that would make a new event a duplicate.",
    "check_pending_recommendation": "Recommendations for the loan awaiting review or deferred.",
    "check_pending_action": "Approved actions awaiting verification.",
    "check_previous_rejection": "Prior reviewer rejections and rejected actions inside the lookback window.",
    "get_assigned_party": "Assigned specialist and attorney/vendor, and whether the required party is present.",
    "calculate_escalation_state": "Deterministic escalation state, reasons, required role, allowed actions.",
    "calculate_loan_attention_score": "Deterministic attention score, priority, and score drivers.",
    "get_attention_score_drivers": "Score drivers sorted by contribution with a plain-language summary.",
    "get_allowed_actions": "Actions the agent may recommend for this loan, default action, removed actions.",
    "calculate_followup_date": "Deterministic proposed follow-up date for an action (RULE-FOLLOWUP-006).",
    "prepare_followup_event": "Prepare an UNCOMMITTED outbound event draft for an action. Never submits.",
    "prepare_escalation": "Prepare an UNCOMMITTED escalation draft. Never submits.",
    "validate_proposed_event": "Validate a proposed action/event against RULE-VALIDATION-001.",
    "verify_servicing_event_created": "Verification status of an approved action against refreshed events.",
    "compare_approved_to_actual": "Field-by-field comparison of an approved action and matching events.",
    "get_portfolio_health_summary": "Portfolio KPIs and health segments (deterministic).",
    "get_priority_queue": "Ranked attention queue with drivers.",
    "get_portfolio_exceptions": "Loans with data exceptions or duplicate risk.",
    "get_specialist_workload_summary": "Per-specialist assigned, attention, critical, and high counts.",
    "get_recommendations_awaiting_approval": "Recommendations awaiting specialist review.",
    "get_failed_verifications": "Actions that failed or did not verify.",
}

LOAN_TOOLS = [
    "get_loan_context", "get_event_history", "get_current_milestone", "check_milestone_completion",
    "check_followup_status", "calculate_days_to_followup", "get_next_required_milestone", "get_milestone_rule",
    "check_existing_event", "check_pending_recommendation", "check_pending_action", "check_previous_rejection",
    "get_assigned_party", "calculate_escalation_state", "calculate_loan_attention_score",
    "get_attention_score_drivers", "get_allowed_actions", "calculate_followup_date", "prepare_followup_event",
    "prepare_escalation", "validate_proposed_event", "verify_servicing_event_created", "compare_approved_to_actual",
]
PORTFOLIO_TOOLS = [
    "get_portfolio_health_summary", "get_priority_queue", "get_portfolio_exceptions",
    "get_specialist_workload_summary", "get_recommendations_awaiting_approval", "get_failed_verifications",
]
ALL_TOOLS = LOAN_TOOLS + PORTFOLIO_TOOLS


@dataclass
class ToolSpec:
    name: str
    description: str
    fn: Callable[..., dict]
    input_model: type[BaseModel]

    def json_schema(self) -> dict:
        schema = self.input_model.model_json_schema()
        props = {}
        for key, prop in schema.get("properties", {}).items():
            prop = {k: v for k, v in prop.items() if k != "title"}
            if "anyOf" in prop:  # Optional[X] -> X
                types = [a for a in prop.pop("anyOf") if a.get("type") != "null"]
                if types:
                    prop.update(types[0])
            props[key] = prop
        return {"type": "object", "properties": props, "required": schema.get("required", [])}

    def openai_tool(self) -> dict:
        return {"type": "function", "function": {"name": self.name, "description": self.description,
                                                 "parameters": self.json_schema()}}


def _model_for(name: str, fn: Callable) -> type[BaseModel]:
    fields: dict[str, Any] = {}
    hints = typing.get_type_hints(fn)
    for pname, param in list(inspect.signature(fn).parameters.items())[1:]:  # skip ctx
        annotation = hints.get(pname, Any)
        default = param.default if param.default is not inspect.Parameter.empty else ...
        fields[pname] = (annotation, default)
    model_name = "".join(p.title() for p in name.split("_")) + "Input"
    return create_model(model_name, __config__=ConfigDict(extra="forbid"), **fields)


def build_registry() -> dict[str, ToolSpec]:
    registry = {}
    for name in ALL_TOOLS:
        fn = globals()[name]
        registry[name] = ToolSpec(name=name, description=DESCRIPTIONS[name], fn=fn, input_model=_model_for(name, fn))
    return registry


REGISTRY = build_registry()


# ====================================================================================================
# Tool executor: input validation, timing, structured result, and activity logging
# ====================================================================================================

def utcnow() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="milliseconds")


def summarize(value, limit: int = 400) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str, separators=(",", ":"))
    return text if len(text) <= limit else text[: limit - 3] + "..."


class ToolExecutor:
    """Runs registered tools against a ToolContext and records every call."""

    def __init__(self, ctx: ToolContext, run_id: str, loan_id: str | None = None,
                 on_record: Callable[[dict], None] | None = None):
        self.ctx = ctx
        self.run_id = run_id
        self.loan_id = loan_id
        self.records: list[dict] = []
        self.results: dict[str, dict] = {}
        self.on_record = on_record

    def call(self, name: str, arguments: dict | None = None, origin: str = "plan") -> dict:
        arguments = dict(arguments or {})
        started = time.perf_counter()
        called_at = utcnow()
        spec = REGISTRY.get(name)
        data, error = None, None
        try:
            if spec is None:
                raise ToolError(f"UNKNOWN_TOOL:{name}")
            params = spec.input_model(**arguments)
            data = spec.fn(self.ctx, **params.model_dump())
        except ValidationError as exc:
            error = "INVALID_INPUT: " + "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        except ToolError as exc:
            error = str(exc)
        except Exception as exc:  # noqa: BLE001 - tool failures never crash the agent
            error = f"TOOL_ERROR: {type(exc).__name__}: {exc}"
        duration = round((time.perf_counter() - started) * 1000, 2)
        result = {"tool_name": name, "success": error is None, "data": data, "error": error,
                  "duration_ms": duration, "called_at": called_at, "input": arguments}
        record = {
            "tool_name": name, "success": error is None, "duration_ms": duration,
            "input_summary": summarize(arguments, 200), "output_summary": summarize(data if error is None else error),
            "error": error, "called_at": called_at, "origin": origin,
        }
        self.records.append(record)
        if error is None:
            self.results[name] = data
        if self.on_record:
            self.on_record({"run_id": self.run_id, "loan_id": self.loan_id or arguments.get("loan_id"), **record})
        return result


# ====================================================================================================
# Unity Catalog SQL table functions: the governed toolset of the deployed Loan Servicing Agent
# ====================================================================================================

LOAN_PARAM = "loan_id STRING COMMENT 'Synthetic loan identifier, for example LSI-SYN-000005'"


def tool_names() -> list[str]:
    return [name for name, _ in uc_function_statements("c", "s")]


def uc_function_statements(catalog: str, schema: str) -> list[tuple[str, str]]:
    t = f"`{catalog}`.`{schema}`"

    def fn(name: str, params: str, returns: str, comment: str, body: str) -> tuple[str, str]:
        safe = comment.replace("'", "")
        return name, (f"CREATE OR REPLACE FUNCTION {t}.`{name}`({params}) RETURNS TABLE ({returns}) "
                      f"COMMENT '{safe} (synthetic demonstration data)' RETURN {body}")

    def loan(name: str) -> str:
        return f"upper({name}.loan_id)"

    return [
        fn("lsi_get_loan_context", LOAN_PARAM,
           "loan_id STRING, borrower_display_name STRING, portfolio_id STRING, property_state STRING, "
           "current_balance DOUBLE, payment_status STRING, days_delinquent BIGINT, loan_status STRING, "
           "foreclosure_status STRING, specialist_name STRING, party_name STRING, party_type STRING",
           "Loan attributes, balances, statuses, assigned specialist and attorney or vendor",
           f"SELECT loan_id, borrower_display_name, portfolio_id, property_state, CAST(current_balance AS DOUBLE), "
           f"payment_status, CAST(days_delinquent AS BIGINT), loan_status, foreclosure_status, specialist_name, "
           f"party_name, party_type FROM {t}.gold_loan_servicing_state "
           f"WHERE loan_id = {loan('lsi_get_loan_context')}"),
        fn("lsi_get_event_history", LOAN_PARAM,
           "event_date STRING, event_type STRING, milestone_type STRING, followup_date STRING, completed_date STRING, "
           "status STRING, source STRING, event_id STRING, event_note STRING",
           "Chronological servicing events for a loan, payments excluded",
           f"SELECT CAST(event_date AS STRING), event_type, milestone_type, CAST(followup_date AS STRING), "
           f"CAST(completed_date AS STRING), status, source, event_id, event_note FROM {t}.silver_loan_events "
           f"WHERE loan_id = {loan('lsi_get_event_history')} AND event_type <> 'PAYMENT_RECEIVED' "
           f"ORDER BY event_date, event_id"),
        fn("lsi_get_current_milestone", LOAN_PARAM,
           "milestone_type STRING, status STRING, event_date STRING, followup_date STRING, completed_date STRING, "
           "event_id STRING",
           "Current servicing milestone of a loan (highest configured sequence, RULE-MILESTONE-001)",
           f"SELECT milestone_type, status, CAST(event_date AS STRING), CAST(followup_date AS STRING), "
           f"CAST(completed_date AS STRING), event_id FROM {t}.gold_loan_milestone_state "
           f"WHERE loan_id = {loan('lsi_get_current_milestone')} AND is_current"),
        fn("lsi_check_followup_status", LOAN_PARAM,
           "current_milestone STRING, milestone_complete BOOLEAN, effective_followup_date STRING, "
           "days_to_followup STRING, days_overdue BIGINT, primary_condition STRING, secondary_conditions STRING, "
           "conditions_detail STRING, rule_ids STRING",
           "Effective follow-up date, days overdue, and the deterministic conditions detected for a loan",
           f"SELECT current_milestone, CAST(milestone_complete AS BOOLEAN), CAST(effective_followup_date AS STRING), "
           f"CAST(days_to_followup AS STRING), CAST(days_overdue AS BIGINT), primary_condition, "
           f"secondary_conditions, raw_conditions, condition_rule_ids FROM {t}.gold_loan_servicing_state "
           f"WHERE loan_id = {loan('lsi_check_followup_status')}"),
        fn("lsi_get_open_followups", LOAN_PARAM,
           "event_id STRING, event_type STRING, milestone_type STRING, event_date STRING, followup_date STRING, "
           "source STRING",
           "Open follow-up type events for a loan; two or more of the same type for a milestone is a duplicate risk",
           f"SELECT event_id, event_type, milestone_type, CAST(event_date AS STRING), CAST(followup_date AS STRING), "
           f"source FROM {t}.silver_loan_events WHERE loan_id = {loan('lsi_get_open_followups')} AND status = 'OPEN' "
           f"AND event_type IN ('FOLLOWUP', 'CONTACT', 'ESCALATION', 'INFO_REQUEST', 'DATA_REVIEW') "
           f"ORDER BY event_date"),
        fn("lsi_get_milestone_rule",
           "milestone_type STRING COMMENT 'Milestone code, for example TITLE_REVIEW'",
           "milestone_type STRING, milestone_sequence BIGINT, default_followup_days BIGINT, lookahead_days BIGINT, "
           "requires_followup BOOLEAN, overdue_action STRING, next_milestone_type STRING, severity BIGINT",
           "Configured synthetic milestone rule: follow-up days, look-ahead, overdue action, next milestone, severity",
           f"SELECT milestone_type, CAST(milestone_sequence AS BIGINT), CAST(default_followup_days AS BIGINT), "
           f"CAST(lookahead_days AS BIGINT), requires_followup, overdue_action, next_milestone_type, "
           f"CAST(severity AS BIGINT) FROM {t}.silver_milestone_rules "
           f"WHERE milestone_type = upper(lsi_get_milestone_rule.milestone_type) AND active"),
        fn("lsi_get_escalation_state", LOAN_PARAM,
           "escalation_state STRING, required_role STRING, health_segment STRING, escalation_reasons STRING",
           "Deterministic escalation state, required approver role, and the escalation rules that matched",
           f"SELECT escalation_state, required_role, health_segment, escalation_reasons "
           f"FROM {t}.gold_loan_servicing_state WHERE loan_id = {loan('lsi_get_escalation_state')}"),
        fn("lsi_get_attention_score", LOAN_PARAM,
           "attention_score BIGINT, priority STRING, score_drivers STRING, drivers_summary STRING, "
           "scoring_version STRING",
           "Deterministic attention score, priority, and score drivers. The agent must report, never recalculate, it",
           f"SELECT CAST(attention_score AS BIGINT), priority, score_drivers, top_drivers_text, scoring_version "
           f"FROM {t}.gold_loan_servicing_state WHERE loan_id = {loan('lsi_get_attention_score')}"),
        fn("lsi_get_allowed_actions", LOAN_PARAM,
           "allowed_actions STRING, default_action STRING, removed_actions STRING",
           "Actions the agent may recommend for this loan, the deterministic default, and actions removed and why",
           f"SELECT allowed_actions, default_action, removed_actions FROM {t}.gold_loan_servicing_state "
           f"WHERE loan_id = {loan('lsi_get_allowed_actions')}"),
        fn("lsi_check_pending_actions", LOAN_PARAM,
           "action_id STRING, action_type STRING, status STRING, followup_date STRING, origin STRING",
           "Approved or submitted actions still awaiting verification; a pending action means do not duplicate it",
           f"SELECT action_id, action_type, status, followup_date, 'APP' FROM {t}.ops_actions "
           f"WHERE loan_id = {loan('lsi_check_pending_actions')} AND status IN ('APPROVED', 'SUBMITTED') "
           f"UNION ALL SELECT action_id, action_type, 'SUBMITTED', CAST(followup_date AS STRING), 'HISTORY' "
           f"FROM {t}.gold_pending_actions WHERE loan_id = {loan('lsi_check_pending_actions')}"),
        fn("lsi_check_prior_rejections", LOAN_PARAM,
           "decided_at STRING, original_action STRING, reason STRING, reviewer_id STRING",
           "Prior reviewer rejections for a loan; recently rejected actions should not be re-proposed",
           f"SELECT CAST(decided_at AS STRING), original_action, reason, reviewer_id FROM {t}.gold_reviewer_decisions "
           f"WHERE loan_id = {loan('lsi_check_prior_rejections')} AND decision = 'REJECT' ORDER BY decided_at DESC"),
        fn("lsi_get_agent_proposals", LOAN_PARAM,
           "created_at STRING, recommended_action STRING, recommended_followup_date STRING, confidence STRING, "
           "status STRING, agent_mode STRING",
           "Existing agent proposals for a loan and their review status",
           f"SELECT created_at, recommended_action, recommended_followup_date, confidence, status, agent_mode "
           f"FROM {t}.ops_recommendations WHERE loan_id = {loan('lsi_get_agent_proposals')} "
           f"AND status <> 'SUPERSEDED' ORDER BY created_at DESC"),
        fn("lsi_get_ai_loan_insight", LOAN_PARAM,
           "ai_summary STRING, generated_at STRING, model_endpoint STRING",
           "AI Functions (ai_query) summary written by the backend workflow, if one exists",
           f"SELECT ai_summary, CAST(generated_at AS STRING), model_endpoint FROM {t}.gold_ai_loan_insights "
           f"WHERE loan_id = {loan('lsi_get_ai_loan_insight')}"),
        fn("lsi_priority_queue",
           "max_rows INT COMMENT 'Number of queue rows to return, for example 10'",
           "queue_rank BIGINT, priority STRING, loan_id STRING, primary_condition STRING, attention_score BIGINT, "
           "top_drivers STRING, recommended_action STRING, why_prioritized STRING",
           "Ranked servicing work queue across the portfolio",
           f"SELECT CAST(queue_rank AS BIGINT), priority, loan_id, primary_condition, CAST(attention_score AS BIGINT), "
           f"top_drivers_text, recommended_action, why_prioritized FROM {t}.gold_priority_queue "
           f"WHERE CAST(queue_rank AS INT) <= lsi_priority_queue.max_rows"),
        fn("lsi_portfolio_health_summary", "",
           "health_segment STRING, loan_count BIGINT, share_of_active DOUBLE",
           "Portfolio health segments: Healthy, Watch, Action Required, Critical",
           f"SELECT health_segment, CAST(loan_count AS BIGINT), CAST(share_of_active AS DOUBLE) "
           f"FROM {t}.gold_portfolio_health"),
        fn("lsi_specialist_workload", "",
           "specialist_name STRING, assigned_loans BIGINT, need_attention BIGINT, critical BIGINT, high BIGINT",
           "Per-specialist assigned loans, loans needing attention, critical and high counts",
           f"SELECT specialist_name, CAST(assigned_loans AS BIGINT), CAST(need_attention AS BIGINT), "
           f"CAST(critical AS BIGINT), CAST(high AS BIGINT) FROM {t}.v_lsi_specialist_workload"),
        fn("lsi_get_failed_verifications", "",
           "action_id STRING, loan_id STRING, action_type STRING, verification_status STRING, detail STRING",
           "Approved actions that failed verification against the servicing system",
           f"SELECT action_id, loan_id, action_type, verification_status, detail "
           f"FROM {t}.v_lsi_verification_failures"),
    ]
