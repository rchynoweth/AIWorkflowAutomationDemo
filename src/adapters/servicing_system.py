"""Loan-servicing System of Record adapters.

``SyntheticServicingSystemAdapter`` simulates a System of Record by producing event rows that become visible
on a later refresh cycle. It performs no browser automation and calls no real platform.
"""
from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta, timezone

from src.verification.verifier import reference_token

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
