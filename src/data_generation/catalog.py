"""Static synthetic reference data: milestone rules, specialists, parties, value domains.

SYNTHETIC: the milestone sequence is a generic illustration and not a legal process.
"""
from __future__ import annotations

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
