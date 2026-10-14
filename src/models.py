"""Pydantic request and recommendation schemas."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field




# ====================================================================================================
# Pydantic schemas for recommendations, review decisions, actions, and API payloads
# ====================================================================================================

Decision = Literal["APPROVE", "EDIT", "REJECT", "DEFER", "ESCALATE"]
Confidence = Literal["HIGH", "MEDIUM", "LOW"]
RecommendationStatus = Literal["PENDING_REVIEW", "APPROVED", "REJECTED", "DEFERRED", "ESCALATED", "SUPERSEDED",
                               "FAILED"]


class EvidenceItem(BaseModel):
    source_type: Literal["TOOL", "EVENT", "RULE", "ACTION", "DECISION"]
    source_identifier: str
    description: str
    value: Any = None
    observed_at: str


class ScoreDriver(BaseModel):
    factor: str
    points: int
    detail: str


class ToolCallRecord(BaseModel):
    tool_name: str
    success: bool
    duration_ms: float
    input_summary: str = ""
    output_summary: str = ""
    error: str | None = None
    called_at: str
    origin: Literal["agent", "plan", "guardrail"] = "plan"


class Recommendation(BaseModel):
    recommendation_id: str
    loan_id: str
    primary_condition: str
    secondary_conditions: list[str] = Field(default_factory=list)
    attention_score: int
    priority: str
    score_drivers: list[ScoreDriver] = Field(default_factory=list)
    recommended_action: str
    recommended_event_type: str | None = None
    recommended_followup_date: str | None = None
    suggested_note: str = ""
    suggested_outreach: str = ""
    rationale: str = ""
    evidence: list[EvidenceItem] = Field(default_factory=list)
    confidence: Confidence = "MEDIUM"
    uncertainty: str = ""
    missing_information: list[str] = Field(default_factory=list)
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    created_at: str
    agent_version: str
    rule_version: str
    scoring_version: str
    status: RecommendationStatus = "PENDING_REVIEW"
    requires_human_approval: bool = True
    # extensions
    allowed_actions: list[str] = Field(default_factory=list)
    escalation_state: str = "NONE"
    state_fingerprint: str = ""
    proposed_event: dict[str, Any] = Field(default_factory=dict)
    validation: dict[str, Any] = Field(default_factory=dict)
    agent_mode: str = "deterministic"
    run_id: str = ""
    synthetic_data: bool = True


class DecisionEdits(BaseModel):
    action_type: str | None = None
    event_type: str | None = None
    followup_date: str | None = None
    note: str | None = None
    outreach: str | None = None
    escalation_target: str | None = None


class DecisionRequest(BaseModel):
    decision: Decision
    reviewer_id: str = "SPEC-01"
    reviewer_role: str = "LOAN_SERVICING_SPECIALIST"
    reason: str = ""
    comment: str = ""
    edits: DecisionEdits | None = None


class AgentRequest(BaseModel):
    mode: Literal["assess", "ask", "briefing"] = "assess"
    loan_id: str | None = None
    question: str | None = None
    user_id: str = "SPEC-01"
    agent_mode: Literal["auto", "llm", "deterministic"] | None = None


class BatchAgentRequest(BaseModel):
    loan_ids: list[str] | None = None
    limit: int = 3
    user_id: str = "SPEC-01"
    agent_mode: Literal["auto", "llm", "deterministic"] | None = None


class ScheduleRequest(BaseModel):
    action_type: str
    followup_date: str | None = None
    note: str | None = None
    outreach: str | None = None
    reviewer_id: str = "SPEC-01"
    reviewer_role: str = "LOAN_SERVICING_SPECIALIST"
    send: bool = True


class AgentChatRequest(BaseModel):
    messages: list[dict]
    instructions: str | None = None


class EvaluationRequest(BaseModel):
    agent_mode: Literal["auto", "llm", "deterministic"] = "deterministic"
