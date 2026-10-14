"""Deterministic synthetic loan-servicing exports (SYNTHETIC DEMONSTRATION DATA)."""
from __future__ import annotations

import argparse
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from src.config import get_settings


# ====================================================================================================
# Static synthetic reference data: milestone rules, specialists, parties, value domains
# ====================================================================================================

# milestone_type, sequence, default_followup_days, lookahead_days, requires_followup,
# overdue_action, next_milestone_type, severity, active
MILESTONE_RULES = [
    ("BORROWER_OUTREACH", 1, 10, 5, True, "CONTACT_SERVICING_VENDOR", "DEMAND_LETTER", 1, True),
    ("DEMAND_LETTER", 2, 30, 7, True, "CREATE_FOLLOWUP", "REFERRAL_TO_ATTORNEY", 2, True),
    ("REFERRAL_TO_ATTORNEY", 3, 14, 7, True, "CONTACT_ATTORNEY", "TITLE_REVIEW", 3, True),
    ("TITLE_REVIEW", 4, 21, 7, True, "CONTACT_ATTORNEY", "COMPLAINT_FILED", 2, True),
    ("COMPLAINT_FILED", 5, 30, 10, True, "CONTACT_ATTORNEY", "SERVICE_OF_PROCESS", 3, True),
    ("SERVICE_OF_PROCESS", 6, 30, 10, True, "CONTACT_ATTORNEY", "JUDGMENT_HEARING", 3, True),
    ("JUDGMENT_HEARING", 7, 45, 14, True, "CONTACT_ATTORNEY", "SALE_SCHEDULED", 4, True),
    ("SALE_SCHEDULED", 8, 30, 14, True, "CONTACT_ATTORNEY", "SALE_COMPLETED", 5, True),
    ("SALE_COMPLETED", 9, 0, 0, False, "NO_ACTION", None, 1, True),
    ("LEGACY_REVIEW", 0, 15, 7, True, "CREATE_FOLLOWUP", None, 2, False),
]

MILESTONE_COLUMNS = [
    "milestone_type", "milestone_sequence", "default_followup_days", "lookahead_days",
    "requires_followup", "overdue_action", "next_milestone_type", "severity", "active",
]

TRACK = [r[0] for r in MILESTONE_RULES if r[1] >= 1]  # ordered active track
RULE_BY_TYPE = {r[0]: dict(zip(MILESTONE_COLUMNS, r)) for r in MILESTONE_RULES}

SPECIALISTS = [
    ("SPEC-01", "Synthetic Specialist 01", "Synthetic Team A", True),
    ("SPEC-02", "Synthetic Specialist 02", "Synthetic Team A", True),
    ("SPEC-03", "Synthetic Specialist 03", "Synthetic Team A", True),
    ("SPEC-04", "Synthetic Specialist 04", "Synthetic Team B", True),
    ("SPEC-05", "Synthetic Specialist 05", "Synthetic Team B", True),
    ("SPEC-06", "Synthetic Specialist 06", "Synthetic Team C", True),
    ("SPEC-07", "Synthetic Specialist 07", "Synthetic Team C", True),
    ("SPEC-08", "Synthetic Specialist 08", "Synthetic Team C", False),
]
ACTIVE_SPECIALISTS = [s[0] for s in SPECIALISTS if s[3]]

STATES = ["AZ", "CA", "CO", "FL", "GA", "IL", "NC", "NY", "OH", "TX"]

PARTIES = [
    ("ATT-01", "Synthetic Legal Vendor 01", "ATTORNEY", "AZ", True),
    ("ATT-02", "Synthetic Legal Vendor 02", "ATTORNEY", "FL", True),
    ("ATT-03", "Synthetic Legal Vendor 03", "ATTORNEY", "IL", True),
    ("ATT-04", "Synthetic Legal Vendor 04", "ATTORNEY", "NY", True),
    ("ATT-05", "Synthetic Legal Vendor 05", "ATTORNEY", "TX", True),
    ("ATT-06", "Synthetic Legal Vendor 06", "ATTORNEY", "CA", False),
    ("VEN-01", "Synthetic Servicing Vendor 01", "VENDOR", "GA", True),
    ("VEN-02", "Synthetic Servicing Vendor 02", "VENDOR", "OH", True),
    ("VEN-03", "Synthetic Servicing Vendor 03", "VENDOR", "NC", True),
    ("VEN-04", "Synthetic Servicing Vendor 04", "VENDOR", "CO", True),
]
ACTIVE_ATTORNEYS = [p[0] for p in PARTIES if p[2] == "ATTORNEY" and p[4]]
ACTIVE_VENDORS = [p[0] for p in PARTIES if p[2] == "VENDOR" and p[4]]

PORTFOLIOS = ["SYN-PORTFOLIO-A", "SYN-PORTFOLIO-B", "SYN-PORTFOLIO-C", "SYN-PORTFOLIO-D"]

FORECLOSURE_STATUS_BY_STAGE = {
    "BORROWER_OUTREACH": "PRE_FORECLOSURE",
    "DEMAND_LETTER": "PRE_FORECLOSURE",
    "REFERRAL_TO_ATTORNEY": "REFERRED",
    "TITLE_REVIEW": "REFERRED",
    "COMPLAINT_FILED": "ACTIVE",
    "SERVICE_OF_PROCESS": "ACTIVE",
    "JUDGMENT_HEARING": "ACTIVE",
    "SALE_SCHEDULED": "SALE_SCHEDULED",
    "SALE_COMPLETED": "COMPLETED",
    "LEGACY_REVIEW": "PRE_FORECLOSURE",
}

DELINQUENCY_BY_STAGE = {
    "BORROWER_OUTREACH": (30, 59),
    "DEMAND_LETTER": (60, 89),
    "REFERRAL_TO_ATTORNEY": (90, 150),
    "TITLE_REVIEW": (120, 180),
    "COMPLAINT_FILED": (150, 240),
    "SERVICE_OF_PROCESS": (180, 300),
    "JUDGMENT_HEARING": (240, 360),
    "SALE_SCHEDULED": (300, 420),
    "SALE_COMPLETED": (360, 480),
    "LEGACY_REVIEW": (60, 120),
}

LOAN_STATUSES = ["ACTIVE", "PAID_OFF", "SOLD"]
PAYMENT_STATUSES = ["CURRENT", "DELINQUENT_30", "DELINQUENT_60", "DELINQUENT_90_PLUS"]
FORECLOSURE_STATUSES = ["NONE", "PRE_FORECLOSURE", "REFERRED", "ACTIVE", "SALE_SCHEDULED", "COMPLETED"]
EVENT_TYPES = ["MILESTONE", "FOLLOWUP", "CONTACT", "ESCALATION", "INFO_REQUEST", "DATA_REVIEW",
               "PAYMENT_RECEIVED", "NOTE"]
EVENT_STATUSES = ["OPEN", "COMPLETED", "CANCELLED"]
EVENT_SOURCES = ["SERVICING_SYSTEM_EXPORT", "SERVICING_SYSTEM_ADAPTER"]
ACTION_STATUSES = ["APPROVED", "SUBMITTED", "VERIFIED", "FAILED", "VERIFICATION_FAILED"]
DECISIONS = ["APPROVE", "EDIT", "REJECT", "DEFER", "ESCALATE"]


def payment_status_for(days_delinquent: int) -> str:
    if days_delinquent < 30:
        return "CURRENT"
    if days_delinquent < 60:
        return "DELINQUENT_30"
    if days_delinquent < 90:
        return "DELINQUENT_60"
    return "DELINQUENT_90_PLUS"


# ====================================================================================================
# Deterministic synthetic loan-servicing export generator
# ====================================================================================================

LOAN_COLUMNS = [
    "loan_id", "borrower_display_name", "property_address", "property_city", "property_state",
    "property_postal_code", "property_county", "original_balance", "current_balance", "loan_status",
    "payment_status", "days_delinquent", "foreclosure_status", "assigned_specialist_id",
    "assigned_attorney_vendor_id", "boarding_date", "portfolio_id", "synthetic_data",
]
EVENT_COLUMNS = [
    "event_id", "loan_id", "event_type", "milestone_type", "event_date", "followup_date", "completed_date",
    "status", "event_note", "source", "created_at", "updated_at", "synthetic_data",
]
ACTION_COLUMNS = [
    "action_id", "loan_id", "recommendation_id", "action_type", "event_type", "event_date", "followup_date",
    "status", "submitted_at", "verified_at", "failure_reason", "synthetic_data",
]
DECISION_COLUMNS = [
    "decision_id", "recommendation_id", "loan_id", "reviewer_id", "decision", "original_action",
    "final_action", "original_followup_date", "final_followup_date", "original_note", "final_note", "reason",
    "decided_at", "synthetic_data",
]
MANIFEST_COLUMNS = [
    "scenario_id", "loan_id", "scenario_type", "expected_condition", "expected_priority", "expected_action",
    "expected_verification_status", "description",
]

ACTION_EVENT_TYPE = {
    "CREATE_FOLLOWUP": "FOLLOWUP",
    "CONTACT_ATTORNEY": "CONTACT",
    "CONTACT_SERVICING_VENDOR": "CONTACT",
    "ESCALATE_TO_SPECIALIST": "ESCALATION",
    "REQUEST_INFORMATION": "INFO_REQUEST",
}

# scenario_id, loan index, type, condition, priority, action, verification, description
SCENARIOS = [
    ("S01", 1, "HEALTHY_NO_ACTION", "NO_ACTION", "LOW", "NO_ACTION", "NOT_APPLICABLE",
     "Performing synthetic loan with no servicing track."),
    ("S02", 2, "UPCOMING", "UPCOMING", "LOW", "NO_ACTION", "NOT_APPLICABLE",
     "DEMAND_LETTER follow-up five days after the processing date (inside look-ahead)."),
    ("S03", 3, "DUE_TODAY", "DUE", "MEDIUM", "CREATE_FOLLOWUP", "NOT_APPLICABLE",
     "DEMAND_LETTER follow-up equals the processing date."),
    ("S04", 4, "ONE_DAY_OVERDUE", "OVERDUE", "MEDIUM", "CONTACT_ATTORNEY", "NOT_APPLICABLE",
     "REFERRAL_TO_ATTORNEY follow-up one day overdue; adapter configured to FAIL."),
    ("S05", 5, "MATERIALLY_OVERDUE", "OVERDUE", "HIGH", "CONTACT_ATTORNEY", "NOT_APPLICABLE",
     "TITLE_REVIEW follow-up 18 days overdue (main demo path)."),
    ("S06", 6, "SEVERELY_OVERDUE", "OVERDUE", "CRITICAL", "ESCALATE_TO_SPECIALIST", "NOT_APPLICABLE",
     "JUDGMENT_HEARING follow-up 75 days overdue."),
    ("S07", 7, "COMPLETED_NEEDS_NEXT", "COMPLETED_NEEDS_NEXT", "MEDIUM", "CREATE_NEXT_MILESTONE",
     "NOT_APPLICABLE", "TITLE_REVIEW completed three days ago; COMPLAINT_FILED not opened."),
    ("S08", 8, "MISSING_FOLLOWUP", "MISSING_FOLLOWUP", "MEDIUM", "CREATE_FOLLOWUP", "NOT_APPLICABLE",
     "COMPLAINT_FILED open with no follow-up date; adapter configured to DUPLICATE."),
    ("S09", 9, "DUPLICATE_RISK", "DUPLICATE_RISK", "MEDIUM", "REVIEW_DATA_EXCEPTION", "NOT_APPLICABLE",
     "Two equivalent open FOLLOWUP events for SERVICE_OF_PROCESS."),
    ("S10", 10, "CONFLICTING_DATES", "DATA_EXCEPTION", "MEDIUM", "REVIEW_DATA_EXCEPTION", "NOT_APPLICABLE",
     "DEMAND_LETTER completed date earlier than its event date."),
    ("S11", 11, "MISSING_RULE", "DATA_EXCEPTION", "MEDIUM", "REVIEW_DATA_EXCEPTION", "NOT_APPLICABLE",
     "Current milestone LEGACY_REVIEW has no active milestone rule."),
    ("S12", 12, "MISSING_ASSIGNED_PARTY", "DATA_EXCEPTION", "HIGH", "REVIEW_DATA_EXCEPTION", "NOT_APPLICABLE",
     "COMPLAINT_FILED five days overdue with no assigned synthetic legal vendor."),
    ("S13", 13, "PRIOR_REJECTION", "OVERDUE", "HIGH", "CREATE_FOLLOWUP", "NOT_APPLICABLE",
     "Overdue 10 days; CONTACT_ATTORNEY rejected three days ago; adapter configured to MISMATCH."),
    ("S14", 14, "APPROVED_ACTION_PENDING", "PENDING_ACTION", "LOW", "NO_ACTION", "PENDING",
     "Approved CREATE_FOLLOWUP submitted on the processing date, awaiting verification."),
    ("S15", 15, "SUCCESSFUL_VERIFICATION", "NO_ACTION", "LOW", "NO_ACTION", "VERIFIED",
     "Approved CONTACT_ATTORNEY found in the refreshed source with matching fields."),
    ("S16", 16, "FAILED_VERIFICATION", "VERIFICATION_FAILURE", "CRITICAL", "RETRY_FAILED_ACTION", "NOT_FOUND",
     "Approved CONTACT_ATTORNEY submitted five days ago is missing from the refreshed source."),
    ("S17", 17, "MISMATCHED_VERIFICATION", "VERIFICATION_FAILURE", "HIGH", "REVIEW_DATA_EXCEPTION", "MISMATCH",
     "Refreshed source event follow-up date differs from the approved date by seven days."),
    ("S18", 18, "MULTIPLE_UNRESOLVED", "DATA_EXCEPTION", "CRITICAL", "REVIEW_DATA_EXCEPTION", "NOT_APPLICABLE",
     "Overdue 38 days, duplicate open follow-ups, and no assigned synthetic legal vendor."),
    ("S19", 19, "URGENT_COVERED_BY_PENDING", "ALREADY_ACTIONED", "LOW", "NO_ACTION", "PENDING",
     "Overdue 20 days but an approved CONTACT_ATTORNEY was submitted on the processing date."),
    ("S20", 20, "DEFERRED_PENDING_REVIEW", "PENDING_REVIEW", "MEDIUM", "NO_ACTION", "NOT_APPLICABLE",
     "Upcoming follow-up; prior recommendation deferred two days ago."),
]
SCENARIO_COUNT = len(SCENARIOS)


@dataclass
class GeneratedDataset:
    loans: pd.DataFrame
    loan_events: pd.DataFrame
    milestone_rules: pd.DataFrame
    servicing_specialists: pd.DataFrame
    attorneys_vendors: pd.DataFrame
    servicing_action_history: pd.DataFrame
    reviewer_decisions: pd.DataFrame
    demo_scenario_manifest: pd.DataFrame

    def tables(self) -> dict[str, pd.DataFrame]:
        return {
            "loans": self.loans,
            "loan_events": self.loan_events,
            "milestone_rules": self.milestone_rules,
            "servicing_specialists": self.servicing_specialists,
            "attorneys_vendors": self.attorneys_vendors,
            "servicing_action_history": self.servicing_action_history,
            "reviewer_decisions": self.reviewer_decisions,
            "demo_scenario_manifest": self.demo_scenario_manifest,
        }


def loan_id_for(index: int) -> str:
    return f"LSI-SYN-{index:06d}"


class _Builder:
    def __init__(self, seed: int, processing_date: date):
        self.rng = random.Random(seed)
        self.P = processing_date
        self.loans: list[dict] = []
        self.events: list[dict] = []
        self.actions: list[dict] = []
        self.decisions: list[dict] = []
        self._evt = 0
        self._act = 0
        self._dec = 0
        self._rec = 0

    # ---- primitives ---------------------------------------------------------------
    def d(self, offset: int) -> date:
        return self.P + timedelta(days=offset)

    def ts(self, day: date, hour: int | None = None, minute: int | None = None) -> str:
        h = self.rng.randint(8, 17) if hour is None else hour
        m = self.rng.randint(0, 59) if minute is None else minute
        return datetime(day.year, day.month, day.day, h, m, 0).isoformat()

    def next_rec(self) -> str:
        self._rec += 1
        return f"REC-HIST-{self._rec:05d}"

    def add_event(self, loan_id: str, event_type: str, milestone_type: str | None, event_date: date,
                  followup_date: date | None = None, completed_date: date | None = None,
                  status: str = "OPEN", note: str = "", source: str = "SERVICING_SYSTEM_EXPORT",
                  created_at: str | None = None) -> str:
        self._evt += 1
        event_id = f"EVT-SYN-{self._evt:07d}"
        created = created_at or self.ts(event_date)
        updated = self.ts(completed_date) if completed_date and completed_date >= event_date else created
        self.events.append({
            "event_id": event_id,
            "loan_id": loan_id,
            "event_type": event_type,
            "milestone_type": milestone_type or "",
            "event_date": event_date.isoformat(),
            "followup_date": followup_date.isoformat() if followup_date else "",
            "completed_date": completed_date.isoformat() if completed_date else "",
            "status": status,
            "event_note": note,
            "source": source,
            "created_at": created,
            "updated_at": max(created, updated),
            "synthetic_data": "true",
        })
        return event_id

    def add_action(self, loan_id: str, action_type: str, event_date: date, followup_date: date | None,
                   status: str, submitted_at: str, verified_at: str = "", failure_reason: str = "",
                   recommendation_id: str | None = None, action_id: str | None = None) -> str:
        self._act += 1
        action_id = action_id or f"ACT-HIST-{self._act:05d}"
        self.actions.append({
            "action_id": action_id,
            "loan_id": loan_id,
            "recommendation_id": recommendation_id or self.next_rec(),
            "action_type": action_type,
            "event_type": ACTION_EVENT_TYPE.get(action_type, "FOLLOWUP"),
            "event_date": event_date.isoformat(),
            "followup_date": followup_date.isoformat() if followup_date else "",
            "status": status,
            "submitted_at": submitted_at,
            "verified_at": verified_at,
            "failure_reason": failure_reason,
            "synthetic_data": "true",
        })
        return action_id

    def add_decision(self, loan_id: str, recommendation_id: str, decision: str, original_action: str,
                     final_action: str | None, decided_at: str, reason: str, reviewer_id: str = "SPEC-02",
                     original_followup: date | None = None, final_followup: date | None = None,
                     original_note: str = "", final_note: str = "") -> str:
        self._dec += 1
        decision_id = f"DEC-HIST-{self._dec:05d}"
        self.decisions.append({
            "decision_id": decision_id,
            "recommendation_id": recommendation_id,
            "loan_id": loan_id,
            "reviewer_id": reviewer_id,
            "decision": decision,
            "original_action": original_action,
            "final_action": final_action or "",
            "original_followup_date": original_followup.isoformat() if original_followup else "",
            "final_followup_date": final_followup.isoformat() if final_followup else "",
            "original_note": original_note,
            "final_note": final_note,
            "reason": reason,
            "decided_at": decided_at,
            "synthetic_data": "true",
        })
        return decision_id

    # ---- loans ----------------------------------------------------------------------
    def add_loan(self, index: int, *, stage: str | None, party: str | None = "auto",
                 specialist: str | None = None, loan_status: str = "ACTIVE") -> dict:
        rng = self.rng
        loan_id = loan_id_for(index)
        state = rng.choice(STATES)
        original = round(rng.uniform(80_000, 650_000), -2)
        current = round(original * rng.uniform(0.55, 0.98), 2)
        boarding = self.d(-rng.randint(400, 2200))
        if stage is None:
            days_delinquent, foreclosure = 0, "NONE"
            if rng.random() < 0.08:
                days_delinquent = rng.randint(1, 25)
        else:
            low, high = DELINQUENCY_BY_STAGE[stage]
            days_delinquent = rng.randint(low, high)
            foreclosure = FORECLOSURE_STATUS_BY_STAGE[stage]
        if party == "auto":
            if stage is None:
                party = rng.choice(ACTIVE_VENDORS) if rng.random() < 0.25 else None
            elif RULE_BY_TYPE[stage]["milestone_sequence"] <= 2:
                party = rng.choice(ACTIVE_VENDORS)
            else:
                party = rng.choice(ACTIVE_ATTORNEYS)
        loan = {
            "loan_id": loan_id,
            "borrower_display_name": f"Synthetic Borrower {index:04d}",
            "property_address": f"Synthetic Address {index:04d}",
            "property_city": f"Synthetic City {rng.randint(1, 40):02d}",
            "property_state": state,
            "property_postal_code": f"SYN{rng.randint(1, 99):02d}",
            "property_county": f"Synthetic County {rng.randint(1, 60):02d}",
            "original_balance": f"{original:.2f}",
            "current_balance": f"{current:.2f}",
            "loan_status": loan_status,
            "payment_status": payment_status_for(days_delinquent),
            "days_delinquent": str(days_delinquent),
            "foreclosure_status": foreclosure,
            "assigned_specialist_id": specialist or rng.choice(ACTIVE_SPECIALISTS),
            "assigned_attorney_vendor_id": party or "",
            "boarding_date": boarding.isoformat(),
            "portfolio_id": rng.choice(PORTFOLIOS),
            "synthetic_data": "true",
        }
        self.loans.append(loan)
        last_paid = self.d(-days_delinquent - rng.randint(0, 5)) if days_delinquent else self.d(-rng.randint(1, 20))
        self.add_payments(loan_id, boarding, last_paid)
        return loan

    def add_payments(self, loan_id: str, boarding: date, last_paid: date, months: int = 18) -> None:
        day, count = last_paid, 0
        while day >= boarding and count < months:
            self.add_event(loan_id, "PAYMENT_RECEIVED", None, day, completed_date=day, status="COMPLETED",
                           note="Synthetic payment posted.")
            day -= timedelta(days=30)
            count += 1

    def add_history(self, loan_id: str, stage: str, current_start: date) -> None:
        """Completed milestones before ``stage``, walking backwards from ``current_start``."""
        rng = self.rng
        cursor = current_start
        idx = TRACK.index(stage) if stage in TRACK else 0
        for prior in reversed(TRACK[:idx]):
            rule = RULE_BY_TYPE[prior]
            duration = max(6, int(rule["default_followup_days"] * rng.uniform(0.8, 1.6)))
            completed = cursor - timedelta(days=rng.randint(0, 3))
            opened = completed - timedelta(days=duration)
            followup = opened + timedelta(days=rule["default_followup_days"])
            self.add_event(loan_id, "MILESTONE", prior, opened, followup, completed, "COMPLETED",
                           f"Synthetic note: {prior} milestone opened.")
            for _ in range(rng.randint(0, 2)):
                fu_date = opened + timedelta(days=rng.randint(1, max(2, duration - 1)))
                if fu_date >= completed:
                    continue
                self.add_event(loan_id, "FOLLOWUP", prior, fu_date, fu_date + timedelta(days=7),
                               min(completed, fu_date + timedelta(days=rng.randint(1, 7))), "COMPLETED",
                               "Synthetic note: follow-up completed.")
            if rng.random() < 0.5:
                self.add_event(loan_id, "NOTE", prior, opened + timedelta(days=1),
                               completed_date=opened + timedelta(days=1), status="COMPLETED",
                               note="Synthetic note: file reviewed by servicing specialist.")
            cursor = opened

    def add_current(self, loan_id: str, stage: str, opened: date, followup: date | None,
                    completed: date | None = None, status: str = "OPEN", open_followups: list | None = None) -> str:
        event_id = self.add_event(loan_id, "MILESTONE", stage, opened, followup, completed, status,
                                  f"Synthetic note: {stage} milestone opened.")
        for event_date, fu_date in open_followups or []:
            self.add_event(loan_id, "FOLLOWUP", stage, event_date, fu_date, None, "OPEN",
                           "Synthetic note: follow-up scheduled with assigned party.")
        return event_id

    def track_loan(self, index: int, stage: str, opened_offset: int, followup_offset: int | None,
                   party: str | None = "auto", completed_offset: int | None = None,
                   status: str = "OPEN", open_followups: list | None = None) -> str:
        loan = self.add_loan(index, stage=stage, party=party)
        opened = self.d(opened_offset)
        self.add_history(loan["loan_id"], stage, opened)
        self.add_current(
            loan["loan_id"], stage, opened,
            self.d(followup_offset) if followup_offset is not None else None,
            self.d(completed_offset) if completed_offset is not None else None,
            status,
            [(self.d(e), self.d(f)) for e, f in (open_followups or [])],
        )
        return loan["loan_id"]

    # ---- scenarios -------------------------------------------------------------------
    def build_scenarios(self) -> None:
        P = self.P
        self.add_loan(1, stage=None, party=None)                                    # S01 healthy
        self.track_loan(2, "DEMAND_LETTER", -25, 5)                                 # S02 upcoming
        self.track_loan(3, "DEMAND_LETTER", -30, 0)                                 # S03 due today
        self.track_loan(4, "REFERRAL_TO_ATTORNEY", -15, -1, party="ATT-01")         # S04 1 day overdue
        self.track_loan(5, "TITLE_REVIEW", -39, -18, party="ATT-02")                # S05 materially overdue
        self.track_loan(6, "JUDGMENT_HEARING", -120, -75, party="ATT-03")           # S06 severely overdue
        self.track_loan(7, "TITLE_REVIEW", -25, -4, completed_offset=-3, status="COMPLETED")  # S07
        self.track_loan(8, "COMPLAINT_FILED", -6, None)                             # S08 missing follow-up
        self.track_loan(9, "SERVICE_OF_PROCESS", -15, 15, open_followups=[(-5, 20), (-4, 21)])  # S09
        self.track_loan(10, "DEMAND_LETTER", -20, 10, completed_offset=-25, status="COMPLETED")  # S10
        # S11: only a LEGACY_REVIEW milestone whose rule is inactive.
        loan11 = self.add_loan(11, stage="LEGACY_REVIEW")
        self.add_current(loan11["loan_id"], "LEGACY_REVIEW", self.d(-10), self.d(30))
        self.track_loan(12, "COMPLAINT_FILED", -35, -5, party=None)                 # S12 missing party
        loan13 = self.track_loan(13, "REFERRAL_TO_ATTORNEY", -24, -10, party="ATT-04")  # S13 prior rejection
        rec13 = self.next_rec()
        self.add_decision(loan13, rec13, "REJECT", "CONTACT_ATTORNEY", None, self.ts(self.d(-3), 14, 5),
                          "Synthetic reason: assigned legal vendor already engaged outside this workflow.",
                          original_followup=self.d(4))
        # S14: approved action submitted on P, pending verification.
        loan14 = self.track_loan(14, "DEMAND_LETTER", -26, 4)
        rec14 = self.next_rec()
        self.add_decision(loan14, rec14, "APPROVE", "CREATE_FOLLOWUP", "CREATE_FOLLOWUP",
                          self.ts(P, 8, 15), "Synthetic reason: follow-up confirmed.",
                          original_followup=self.d(30), final_followup=self.d(30))
        self.add_action(loan14, "CREATE_FOLLOWUP", P, self.d(30), "SUBMITTED", self.ts(P, 8, 30),
                        recommendation_id=rec14)
        # S15: successful verification.
        loan15 = self.track_loan(15, "REFERRAL_TO_ATTORNEY", -20, -6, party="ATT-05")
        rec15 = self.next_rec()
        self.add_decision(loan15, rec15, "APPROVE", "CONTACT_ATTORNEY", "CONTACT_ATTORNEY",
                          self.ts(self.d(-3), 9, 40), "Synthetic reason: outreach appropriate.",
                          original_followup=self.d(14), final_followup=self.d(14))
        act15 = self.add_action(loan15, "CONTACT_ATTORNEY", self.d(-3), self.d(14), "SUBMITTED",
                                self.ts(self.d(-3), 10, 0), recommendation_id=rec15)
        self.add_event(loan15, "CONTACT", "REFERRAL_TO_ATTORNEY", self.d(-3), self.d(14), None, "OPEN",
                       f"Synthetic outreach to assigned legal vendor. [ref {act15}]",
                       source="SERVICING_SYSTEM_ADAPTER", created_at=self.ts(self.d(-3), 10, 5))
        # S16: failed verification (not found).
        loan16 = self.track_loan(16, "COMPLAINT_FILED", -38, -8, party="ATT-01")
        rec16 = self.next_rec()
        self.add_decision(loan16, rec16, "APPROVE", "CONTACT_ATTORNEY", "CONTACT_ATTORNEY",
                          self.ts(self.d(-5), 10, 40), "Synthetic reason: overdue follow-up.",
                          original_followup=self.d(2), final_followup=self.d(2))
        self.add_action(loan16, "CONTACT_ATTORNEY", self.d(-5), self.d(2), "SUBMITTED",
                        self.ts(self.d(-5), 11, 0), recommendation_id=rec16)
        # S17: mismatched verification.
        loan17 = self.track_loan(17, "SERVICE_OF_PROCESS", -34, -4, party="ATT-02")
        rec17 = self.next_rec()
        self.add_decision(loan17, rec17, "EDIT", "CREATE_FOLLOWUP", "CREATE_FOLLOWUP",
                          self.ts(self.d(-4), 8, 45), "Synthetic reason: adjusted follow-up window.",
                          original_followup=self.d(30), final_followup=self.d(26))
        act17 = self.add_action(loan17, "CREATE_FOLLOWUP", self.d(-4), self.d(26), "SUBMITTED",
                                self.ts(self.d(-4), 9, 0), recommendation_id=rec17)
        self.add_event(loan17, "FOLLOWUP", "SERVICE_OF_PROCESS", self.d(-4), self.d(33), None, "OPEN",
                       f"Synthetic follow-up created by servicing system. [ref {act17}]",
                       source="SERVICING_SYSTEM_ADAPTER", created_at=self.ts(self.d(-4), 9, 10))
        # S18: multiple unresolved conditions.
        self.track_loan(18, "COMPLAINT_FILED", -75, -45, party=None, open_followups=[(-50, -40), (-45, -38)])
        # S19: urgent-looking loan already covered by a pending action.
        loan19 = self.track_loan(19, "SERVICE_OF_PROCESS", -50, -20, party="ATT-03")
        rec19 = self.next_rec()
        self.add_decision(loan19, rec19, "APPROVE", "CONTACT_ATTORNEY", "CONTACT_ATTORNEY",
                          self.ts(P, 9, 10), "Synthetic reason: overdue follow-up.",
                          original_followup=self.d(7), final_followup=self.d(7))
        self.add_action(loan19, "CONTACT_ATTORNEY", P, self.d(7), "SUBMITTED", self.ts(P, 9, 30),
                        recommendation_id=rec19)
        # S20: deferred recommendation awaiting review.
        loan20 = self.track_loan(20, "DEMAND_LETTER", -24, 6)
        self.add_decision(loan20, self.next_rec(), "DEFER", "CREATE_FOLLOWUP", None,
                          self.ts(self.d(-2), 15, 20), "Synthetic reason: awaiting servicing vendor confirmation.",
                          original_followup=self.d(36))

    # ---- background portfolio --------------------------------------------------------
    def build_background(self, start_index: int, end_index: int) -> None:
        rng = self.rng
        stage_weights = [0.16, 0.18, 0.12, 0.10, 0.12, 0.10, 0.09, 0.08, 0.05]
        for index in range(start_index, end_index + 1):
            roll = rng.random()
            if roll < 0.03:
                self.add_loan(index, stage=None, loan_status=rng.choice(["PAID_OFF", "SOLD"]))
                continue
            if roll < 0.56:
                self.add_loan(index, stage=None)
                continue
            stage = rng.choices(TRACK, weights=stage_weights)[0]
            rule = RULE_BY_TYPE[stage]
            lookahead = rule["lookahead_days"]
            if stage == "SALE_COMPLETED":
                loan_id = self.track_loan(index, stage, -rng.randint(20, 90), None,
                                          completed_offset=-rng.randint(1, 15), status="COMPLETED")
                self._maybe_history_action(loan_id)
                continue
            kind = rng.choices(["on_track", "upcoming", "due", "overdue", "missing", "needs_next"],
                               weights=[0.50, 0.13, 0.03, 0.24, 0.03, 0.07])[0]
            opened_offset = -rng.randint(3, 40)
            if kind == "needs_next":
                completed = -rng.randint(1, 10)
                loan_id = self.track_loan(index, stage, min(opened_offset, completed - 3), completed - 1,
                                          completed_offset=completed, status="COMPLETED")
            elif kind == "missing":
                loan_id = self.track_loan(index, stage, opened_offset, None)
            else:
                if kind == "on_track":
                    target = rng.randint(lookahead + 1, max(lookahead + 2, 45))
                elif kind == "upcoming":
                    target = rng.randint(1, max(1, lookahead))
                elif kind == "due":
                    target = 0
                else:
                    target = -rng.choices(
                        [rng.randint(1, 14), rng.randint(15, 29), rng.randint(30, 59), rng.randint(60, 110)],
                        weights=[0.55, 0.25, 0.12, 0.08])[0]
                    opened_offset = min(opened_offset, target - rng.randint(5, 30))
                if rng.random() < 0.5:
                    loan_id = self.track_loan(index, stage, opened_offset, target)
                else:
                    milestone_followup = opened_offset + max(1, rule["default_followup_days"] // 2)
                    fu_event = min(-1, max(opened_offset + 1, target - 7))
                    loan_id = self.track_loan(index, stage, opened_offset, min(milestone_followup, target),
                                              open_followups=[(fu_event, target)])
            self._maybe_history_action(loan_id)

    def _maybe_history_action(self, loan_id: str) -> None:
        rng = self.rng
        roll = rng.random()
        if roll < 0.25:
            submitted_day = self.d(-rng.randint(40, 200))
            action_type = rng.choice(["CREATE_FOLLOWUP", "CONTACT_ATTORNEY", "CONTACT_SERVICING_VENDOR",
                                      "REQUEST_INFORMATION"])
            rec = self.next_rec()
            decision = rng.choices(["APPROVE", "EDIT"], weights=[0.75, 0.25])[0]
            followup = submitted_day + timedelta(days=rng.choice([5, 7, 14, 30]))
            self.add_decision(loan_id, rec, decision, action_type, action_type,
                              self.ts(submitted_day, 9), "Synthetic reason: historical review.",
                              reviewer_id=rng.choice(ACTIVE_SPECIALISTS),
                              original_followup=followup if decision == "APPROVE" else followup + timedelta(days=3),
                              final_followup=followup)
            act = self.add_action(loan_id, action_type, submitted_day, followup, "VERIFIED",
                                  self.ts(submitted_day, 10), self.ts(submitted_day + timedelta(days=1), 10),
                                  recommendation_id=rec)
            self.add_event(loan_id, ACTION_EVENT_TYPE[action_type], None, submitted_day, followup,
                           followup, "COMPLETED", f"Synthetic event created by servicing system. [ref {act}]",
                           source="SERVICING_SYSTEM_ADAPTER", created_at=self.ts(submitted_day, 11))
        elif roll < 0.31:
            day = self.d(-rng.randint(20, 120))
            self.add_decision(loan_id, self.next_rec(), "REJECT", "CREATE_FOLLOWUP", None, self.ts(day, 13),
                              "Synthetic reason: not needed at that time.",
                              reviewer_id=rng.choice(ACTIVE_SPECIALISTS))
        elif roll < 0.34:
            day = self.d(-rng.randint(20, 120))
            self.add_decision(loan_id, self.next_rec(), "DEFER", "REQUEST_INFORMATION", None, self.ts(day, 16),
                              "Synthetic reason: revisit later.", reviewer_id=rng.choice(ACTIVE_SPECIALISTS))

    # ---- assembly --------------------------------------------------------------------
    def frames(self) -> GeneratedDataset:
        manifest = [
            dict(zip(MANIFEST_COLUMNS, (sid, loan_id_for(idx), stype, cond, prio, act, ver, desc)))
            for sid, idx, stype, cond, prio, act, ver, desc in SCENARIOS
        ]
        rules = [dict(zip(MILESTONE_COLUMNS, r)) for r in MILESTONE_RULES]
        for r in rules:
            r["next_milestone_type"] = r["next_milestone_type"] or ""
            r["requires_followup"] = str(r["requires_followup"]).lower()
            r["active"] = str(r["active"]).lower()
            r["synthetic_data"] = "true"
        return GeneratedDataset(
            loans=pd.DataFrame(self.loans, columns=LOAN_COLUMNS),
            loan_events=pd.DataFrame(self.events, columns=EVENT_COLUMNS),
            milestone_rules=pd.DataFrame(rules, columns=MILESTONE_COLUMNS + ["synthetic_data"]),
            servicing_specialists=pd.DataFrame(
                [{"specialist_id": s, "display_name": n, "team": t, "active": str(a).lower(), "synthetic_data": "true"}
                 for s, n, t, a in SPECIALISTS]),
            attorneys_vendors=pd.DataFrame(
                [{"party_id": p, "display_name": n, "party_type": t, "state": s, "active": str(a).lower(),
                  "synthetic_data": "true"} for p, n, t, s, a in PARTIES]),
            servicing_action_history=pd.DataFrame(self.actions, columns=ACTION_COLUMNS),
            reviewer_decisions=pd.DataFrame(self.decisions, columns=DECISION_COLUMNS),
            demo_scenario_manifest=pd.DataFrame(manifest, columns=MANIFEST_COLUMNS),
        )


def generate_dataset(seed: int | None = None, processing_date: date | None = None,
                     loan_count: int | None = None) -> GeneratedDataset:
    """Generate the full synthetic dataset deterministically."""
    settings = get_settings()
    builder = _Builder(seed if seed is not None else settings.seed, processing_date or settings.processing_date)
    builder.build_scenarios()
    builder.build_background(SCENARIO_COUNT + 1, loan_count or settings.loan_count)
    return builder.frames()


def write_dataset(dataset: GeneratedDataset, out_dir: str | Path) -> dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, frame in dataset.tables().items():
        path = out / f"{name}.csv"
        frame.to_csv(path, index=False)
        paths[name] = path
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic loan-servicing exports.")
    parser.add_argument("--out", default=None, help="Output directory (default: config data.generated_dir)")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--processing-date", default=None)
    args = parser.parse_args()
    settings = get_settings()
    dataset = generate_dataset(
        seed=args.seed,
        processing_date=date.fromisoformat(args.processing_date) if args.processing_date else None,
    )
    paths = write_dataset(dataset, args.out or settings.path("generated_dir"))
    for name, path in paths.items():
        print(f"{name:28s} {len(dataset.tables()[name]):>7,d} rows -> {path}")


if __name__ == "__main__":
    main()
