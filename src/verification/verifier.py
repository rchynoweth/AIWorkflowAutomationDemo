"""Action verification against refreshed source events (RULE-VERIFICATION-002/003).

Pure functions: given an action, the loan's current events, and the processing date, return the
verification status. Statuses: VERIFIED, NOT_FOUND, MISMATCH, DUPLICATE, FAILED, PENDING.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pandas as pd

ADAPTER_SOURCE = "SERVICING_SYSTEM_ADAPTER"
FAILURE_STATUSES = {"FAILED", "NOT_FOUND", "MISMATCH", "DUPLICATE"}
RECOMPUTE_STATUSES = {"SUBMITTED", "VERIFICATION_FAILED"}


def _as_date(value: Any) -> date | None:
    if value is None or (isinstance(value, float) and pd.isna(value)) or value is pd.NaT:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text or text.lower() in {"nat", "none", "nan"}:
        return None
    return date.fromisoformat(text[:10])


def _as_ts(value: Any) -> datetime | None:
    if value is None or value is pd.NaT or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, pd.Timestamp):
        return value.floor("us").to_pydatetime().replace(tzinfo=None)
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    text = str(value).strip()
    if not text or text.lower() in {"nat", "none", "nan"}:
        return None
    return pd.Timestamp(text).floor("us").to_pydatetime().replace(tzinfo=None)


def reference_token(action_id: str) -> str:
    return f"[ref {action_id}]"


def find_candidate_events(action: dict, loan_events: list[dict]) -> list[dict]:
    """Adapter-created events that could correspond to ``action`` (RULE-VERIFICATION-002)."""
    token = reference_token(action["action_id"])
    submitted_at = _as_ts(action.get("submitted_at"))
    matches = []
    for ev in loan_events:
        if ev.get("source") != ADAPTER_SOURCE or ev.get("event_type") != action.get("event_type"):
            continue
        if ev.get("status") == "CANCELLED":
            continue
        note = ev.get("event_note") or ""
        if "[ref " in note:
            if token in note:
                matches.append(ev)
            continue
        created = _as_ts(ev.get("created_at"))
        if submitted_at is not None and created is not None and created >= submitted_at:
            matches.append(ev)
    return matches


def compare_fields(action: dict, event: dict) -> list[dict]:
    differences = []
    for field in ("followup_date", "event_date"):
        approved, actual = _as_date(action.get(field)), _as_date(event.get(field))
        if approved != actual:
            differences.append({"field": field, "approved": approved.isoformat() if approved else None,
                                "actual": actual.isoformat() if actual else None})
    approved_ms = (action.get("milestone_type") or "").strip()
    if approved_ms and approved_ms != (event.get("milestone_type") or ""):
        differences.append({"field": "milestone_type", "approved": approved_ms, "actual": event.get("milestone_type")})
    return differences


def verify_action(action: dict, loan_events: list[dict], processing_date: date, window_days: int = 2) -> dict:
    """Return ``{verification_status, matched_event_ids, differences, rule_id, detail}``."""
    status = (action.get("status") or "").upper()
    result = {"action_id": action["action_id"], "loan_id": action.get("loan_id"), "matched_event_ids": [],
              "differences": [], "rule_id": "RULE-VERIFICATION-003", "detail": ""}
    if status == "VERIFIED":
        return {**result, "verification_status": "VERIFIED", "detail": "Recorded as verified."}
    if status == "FAILED":
        return {**result, "verification_status": "FAILED",
                "detail": action.get("failure_reason") or "Adapter reported failure."}
    if status == "APPROVED":
        return {**result, "verification_status": "PENDING", "detail": "Approved; awaiting submission."}

    candidates = find_candidate_events(action, loan_events)
    ids = [c["event_id"] for c in candidates]
    if not candidates:
        submitted_day = _as_date(action.get("event_date")) or (_as_ts(action.get("submitted_at")) or datetime.min).date()
        age = (processing_date - submitted_day).days
        if age < window_days:
            return {**result, "verification_status": "PENDING",
                    "detail": f"Not yet visible; inside {window_days}-day verification window."}
        return {**result, "verification_status": "NOT_FOUND",
                "detail": f"No matching event {age} days after submission."}
    if len(candidates) > 1:
        return {**result, "verification_status": "DUPLICATE", "matched_event_ids": ids,
                "detail": f"{len(candidates)} matching events found."}
    differences = compare_fields(action, candidates[0])
    if differences:
        return {**result, "verification_status": "MISMATCH", "matched_event_ids": ids, "differences": differences,
                "detail": "Refreshed event differs from the approved action."}
    return {**result, "verification_status": "VERIFIED", "matched_event_ids": ids,
            "detail": "Refreshed event matches the approved action."}
