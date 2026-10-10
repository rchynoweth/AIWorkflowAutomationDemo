"""Tool registry: typed input models (derived from function signatures), descriptions, and JSON schemas."""
from __future__ import annotations

import inspect
import typing
from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, create_model

from src.tools import servicing_tools as t

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
        fn = getattr(t, name)
        registry[name] = ToolSpec(name=name, description=DESCRIPTIONS[name], fn=fn, input_model=_model_for(name, fn))
    return registry


REGISTRY = build_registry()
