"""Repository interface for source data and operational state."""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

from src.transformations.silver import SilverDataset

# Operational tables: name -> (key columns, ordered columns). All stored as strings; nested values as JSON.
OPS_TABLES: dict[str, tuple[list[str], list[str]]] = {
    "ops_recommendations": (["recommendation_id"], [
        "recommendation_id", "loan_id", "primary_condition", "secondary_conditions", "attention_score", "priority",
        "score_drivers", "recommended_action", "recommended_event_type", "recommended_followup_date",
        "suggested_note", "suggested_outreach", "rationale", "evidence", "confidence", "uncertainty",
        "missing_information", "tool_calls", "created_at", "agent_version", "rule_version", "scoring_version",
        "status", "requires_human_approval", "allowed_actions", "escalation_state", "state_fingerprint",
        "proposed_event", "validation", "agent_mode", "run_id", "synthetic_data"]),
    "ops_reviewer_decisions": (["decision_id"], [
        "decision_id", "recommendation_id", "loan_id", "reviewer_id", "reviewer_role", "decision",
        "original_action", "final_action", "original_followup_date", "final_followup_date", "original_note",
        "final_note", "edits", "comment", "reason", "decided_at", "synthetic_data"]),
    "ops_actions": (["action_id"], [
        "action_id", "loan_id", "recommendation_id", "decision_id", "action_type", "event_type", "milestone_type",
        "event_date", "followup_date", "note", "outreach", "status", "outbound_payload", "adapter_mode",
        "adapter_result", "approved_by", "approved_at", "submitted_at", "verified_at", "failure_reason",
        "retry_of_action_id", "synthetic_data"]),
    "ops_verification_results": (["verification_id"], [
        "verification_id", "action_id", "loan_id", "cycle", "verification_status", "matched_event_ids",
        "differences", "detail", "evaluated_at"]),
    "ops_agent_activity": (["activity_id"], [
        "activity_id", "run_id", "loan_id", "step", "tool_name", "input_summary", "output_summary", "duration_ms",
        "success", "error", "actor", "created_at"]),
    "sor_servicing_events": (["event_id", "updated_at"], [
        "event_id", "loan_id", "event_type", "milestone_type", "event_date", "followup_date", "completed_date",
        "status", "event_note", "source", "created_at", "updated_at", "synthetic_data", "available_cycle",
        "action_id"]),
    "ops_runtime_state": (["state_key"], ["state_key", "state_value", "updated_at"]),
}


def encode_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (list, dict)):
        return json.dumps(value, default=str)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def encode_record(table: str, record: dict) -> dict:
    _, columns = OPS_TABLES[table]
    return {c: encode_value(record.get(c)) for c in columns}


JSON_FIELDS = {
    "secondary_conditions", "score_drivers", "evidence", "missing_information", "tool_calls", "allowed_actions",
    "proposed_event", "validation", "edits", "outbound_payload", "adapter_result", "matched_event_ids",
    "differences",
}
INT_FIELDS = {"attention_score", "cycle", "available_cycle"}
FLOAT_FIELDS = {"duration_ms"}
BOOL_FIELDS = {"requires_human_approval", "synthetic_data", "success"}


def decode_record(record: dict) -> dict:
    out = {}
    for key, value in record.items():
        if value is None or value == "":
            out[key] = None if key not in JSON_FIELDS else ([] if key not in {
                "proposed_event", "validation", "edits", "outbound_payload", "adapter_result"} else {})
            continue
        if key in JSON_FIELDS and isinstance(value, str):
            try:
                out[key] = json.loads(value)
            except json.JSONDecodeError:
                out[key] = value
        elif key in INT_FIELDS:
            out[key] = int(float(value))
        elif key in FLOAT_FIELDS:
            out[key] = float(value)
        elif key in BOOL_FIELDS and isinstance(value, str):
            out[key] = value.lower() == "true"
        else:
            out[key] = value
    return out


class ServicingRepository(ABC):
    """Storage boundary for source (silver) data and operational state."""

    backend: str = "abstract"

    @abstractmethod
    def load_source_silver(self) -> SilverDataset: ...

    @abstractmethod
    def load_ops(self) -> dict[str, list[dict]]: ...

    @abstractmethod
    def upsert(self, table: str, records: list[dict]) -> None: ...

    @abstractmethod
    def reset_ops(self) -> None: ...

    def flush(self) -> None:
        """Block until pending writes are persisted (no-op for synchronous backends)."""

    def describe(self) -> str:
        return self.backend
