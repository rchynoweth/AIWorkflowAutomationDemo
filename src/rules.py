"""The deterministic rules engine: facts, conditions, escalation, scoring, allowed actions,
follow-up dates, validation, verification, and full-portfolio evaluation. See docs/BUSINESS_RULES.md."""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:  # avoid a circular import; used for type hints only
    from src.medallion import SilverDataset


# ====================================================================================================
# Action verification against refreshed source events (RULE-VERIFICATION-002/003)
# ====================================================================================================

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


# ====================================================================================================
# Deterministic loan facts derived from silver data (RULE-MILESTONE-001/002, RULE-FOLLOWUP-001, ...)
# ====================================================================================================

PARTY_TYPE_FOR_ACTION = {"CONTACT_ATTORNEY": "ATTORNEY", "CONTACT_SERVICING_VENDOR": "VENDOR"}


@dataclass
class EngineContext:
    settings: Any
    processing_date: date
    rules_by_type: dict[str, dict]          # active rules only
    all_rules_by_type: dict[str, dict]
    parties_by_id: dict[str, dict]
    specialists_by_id: dict[str, dict]

    @property
    def thresholds(self) -> dict:
        return self.settings.thresholds

    @classmethod
    def build(cls, settings, silver, processing_date: date | None = None) -> "EngineContext":
        rules = silver.milestone_rules.to_dict("records")
        return cls(
            settings=settings,
            processing_date=processing_date or settings.processing_date,
            rules_by_type={r["milestone_type"]: _clean(r) for r in rules if r["active"]},
            all_rules_by_type={r["milestone_type"]: _clean(r) for r in rules},
            parties_by_id={p["party_id"]: p for p in silver.attorneys_vendors.to_dict("records")},
            specialists_by_id={s["specialist_id"]: s for s in silver.servicing_specialists.to_dict("records")},
        )


def _clean(record: dict) -> dict:
    out = {}
    for k, v in record.items():
        if isinstance(v, float) and pd.isna(v):
            out[k] = None
        elif v is pd.NA:
            out[k] = None
        elif hasattr(v, "item") and not isinstance(v, (str, bytes)):
            try:
                out[k] = v.item()
            except (ValueError, AttributeError):
                out[k] = v
        else:
            out[k] = v
    return out


@dataclass
class LoanFacts:
    loan: dict
    events: list[dict]
    milestone_events: list[dict] = field(default_factory=list)
    current_milestone: dict | None = None
    rule: dict | None = None
    rule_found: bool = False
    milestone_complete: bool = False
    milestone_conflicts: list[str] = field(default_factory=list)
    open_followups: list[dict] = field(default_factory=list)
    effective_followup_date: date | None = None
    effective_followup_event_id: str | None = None
    days_to_followup: int | None = None
    days_overdue: int = 0
    next_milestone_type: str | None = None
    next_milestone_exists: bool = False
    actions: list[dict] = field(default_factory=list)
    verifications: dict[str, dict] = field(default_factory=dict)
    latest_action: dict | None = None
    latest_verification: dict | None = None
    failed_action_count: int = 0
    pending_action: dict | None = None
    decisions: list[dict] = field(default_factory=list)
    prior_rejected_actions: list[str] = field(default_factory=list)
    latest_decision: dict | None = None
    required_party_type: str | None = None
    party_ok: bool = True
    specialist_ok: bool = True
    dq_issues: list[str] = field(default_factory=list)

    @property
    def loan_id(self) -> str:
        return self.loan["loan_id"]

    @property
    def has_track(self) -> bool:
        return self.current_milestone is not None

    @property
    def severity(self) -> int | None:
        return int(self.rule["severity"]) if self.rule and self.rule.get("severity") is not None else None


def _event_sort_key(ev: dict):
    created = _as_ts(ev.get("created_at"))
    return (_as_date(ev.get("event_date")) or date.min, created or datetime.min, ev["event_id"])


def _action_sort_key(action: dict):
    submitted = _as_ts(action.get("submitted_at")) or datetime.min
    origin = 0 if str(action.get("action_id", "")).startswith("ACT-HIST") else 1
    return (_as_date(action.get("event_date")) or date.min, origin, submitted)


def build_loan_facts(loan: dict, events: list[dict], actions: list[dict], decisions: list[dict],
                     ctx: EngineContext) -> LoanFacts:
    P = ctx.processing_date
    th = ctx.thresholds
    facts = LoanFacts(loan=loan, events=sorted(events, key=_event_sort_key))
    if loan.get("dq_issues"):
        facts.dq_issues.extend(str(loan["dq_issues"]).split(";"))

    # RULE-MILESTONE-001: current milestone
    milestones = [e for e in facts.events if e.get("event_type") == "MILESTONE" and e.get("status") != "CANCELLED"]
    facts.milestone_events = milestones
    if milestones:
        def rank(ev):
            seq = ev.get("milestone_sequence")
            seq = -1 if seq is None or (isinstance(seq, float) and pd.isna(seq)) else int(seq)
            return (seq,) + _event_sort_key(ev)
        current = max(milestones, key=rank)
        facts.current_milestone = current
        mtype = current.get("milestone_type") or ""
        facts.rule = ctx.rules_by_type.get(mtype)
        facts.rule_found = facts.rule is not None
        # RULE-MILESTONE-002 + RULE-DATA-002
        completed_date = _as_date(current.get("completed_date"))
        event_date = _as_date(current.get("event_date"))
        status = current.get("status")
        facts.milestone_complete = status == "COMPLETED" and completed_date is not None
        if completed_date and event_date and completed_date < event_date:
            facts.milestone_conflicts.append("COMPLETED_BEFORE_EVENT")
        if status == "COMPLETED" and completed_date is None:
            facts.milestone_conflicts.append("COMPLETED_WITHOUT_DATE")
        if status == "OPEN" and completed_date is not None:
            facts.milestone_conflicts.append("OPEN_WITH_COMPLETED_DATE")
        if current.get("dq_issues"):
            for issue in str(current["dq_issues"]).split(";"):
                if issue and issue not in facts.milestone_conflicts and not issue.startswith(
                        ("COMPLETED_BEFORE", "COMPLETED_WITHOUT", "OPEN_WITH")):
                    facts.dq_issues.append(issue)

        # RULE-FOLLOWUP-001: effective follow-up
        facts.open_followups = [
            e for e in facts.events
            if e.get("is_followup_type") and e.get("status") == "OPEN" and (e.get("milestone_type") or "") == mtype
        ]
        with_dates = [e for e in facts.open_followups if _as_date(e.get("followup_date"))]
        if with_dates:
            latest = max(with_dates, key=_event_sort_key)
            facts.effective_followup_date = _as_date(latest["followup_date"])
            facts.effective_followup_event_id = latest["event_id"]
        elif _as_date(current.get("followup_date")):
            facts.effective_followup_date = _as_date(current["followup_date"])
            facts.effective_followup_event_id = current["event_id"]
        if facts.effective_followup_date and not facts.milestone_complete:
            facts.days_to_followup = (facts.effective_followup_date - P).days
            facts.days_overdue = max(0, -facts.days_to_followup)

        # next milestone
        rule_any = facts.rule or {}
        facts.next_milestone_type = rule_any.get("next_milestone_type") or None
        if facts.next_milestone_type:
            facts.next_milestone_exists = any(
                (e.get("milestone_type") or "") == facts.next_milestone_type for e in facts.events)

        # RULE-DATA-003 / RULE-DATA-004: assigned parties
        if facts.rule:
            facts.required_party_type = PARTY_TYPE_FOR_ACTION.get(facts.rule.get("overdue_action"))
        if facts.required_party_type:
            party = ctx.parties_by_id.get(loan.get("assigned_attorney_vendor_id") or "")
            facts.party_ok = bool(party and party.get("active") and party.get("party_type") == facts.required_party_type)
        spec = ctx.specialists_by_id.get(loan.get("assigned_specialist_id") or "")
        facts.specialist_ok = bool(spec and spec.get("active"))

    # actions + verification
    facts.actions = sorted(actions, key=_action_sort_key)
    window = int(th.get("verification_window_days", 2))
    lookback_start = P - timedelta(days=int(th.get("failure_lookback_days", 30)))
    for action in facts.actions:
        facts.verifications[action["action_id"]] = verify_action(action, facts.events, P, window)
    recent = [a for a in facts.actions if (_as_date(a.get("event_date")) or date.min) >= lookback_start]
    if recent:
        facts.latest_action = recent[-1]
        facts.latest_verification = facts.verifications[facts.latest_action["action_id"]]
        if facts.latest_verification["verification_status"] == "PENDING":
            facts.pending_action = facts.latest_action
    facts.failed_action_count = sum(
        1 for a in recent if facts.verifications[a["action_id"]]["verification_status"] in FAILURE_STATUSES)

    # decisions
    facts.decisions = sorted(decisions, key=lambda d: _as_ts(d.get("decided_at")) or datetime.min)
    if facts.decisions:
        facts.latest_decision = facts.decisions[-1]
    rejection_start = P - timedelta(days=int(th.get("prior_rejection_lookback_days", 14)))
    facts.prior_rejected_actions = sorted({
        d["original_action"] for d in facts.decisions
        if d.get("decision") == "REJECT" and d.get("original_action")
        and ((_as_ts(d.get("decided_at")) or datetime.min).date() >= rejection_start)
    })
    return facts


# ====================================================================================================
# Deterministic servicing-condition detection (see docs/BUSINESS_RULES.md)
# ====================================================================================================

def _cond(code: str, rule_id: str, detail: str) -> dict:
    return {"code": code, "rule_id": rule_id, "detail": detail}


def detect_raw_conditions(facts: LoanFacts, ctx: EngineContext) -> list[dict]:
    th = ctx.thresholds
    raw: list[dict] = []
    P = ctx.processing_date

    # Verification and pending actions (apply with or without a servicing track).
    latest_v = facts.latest_verification
    if latest_v and latest_v["verification_status"] in FAILURE_STATUSES:
        raw.append(_cond("VERIFICATION_FAILURE", "RULE-VERIFICATION-001",
                         f"Action {latest_v['action_id']} verification {latest_v['verification_status']}: "
                         f"{latest_v['detail']}"))
    if facts.pending_action:
        raw.append(_cond("PENDING_ACTION", "RULE-PENDING-001",
                         f"Action {facts.pending_action['action_id']} ({facts.pending_action['action_type']}) "
                         "awaiting verification."))

    # Deferred recommendation awaiting review.
    latest_d = facts.latest_decision
    if latest_d and latest_d.get("decision") == "DEFER":
        decided = _as_ts(latest_d.get("decided_at"))
        if decided and decided.date() >= P - timedelta(days=int(th.get("deferral_lookback_days", 14))):
            raw.append(_cond("PENDING_REVIEW", "RULE-PENDING-003",
                             f"Recommendation {latest_d['recommendation_id']} deferred on {decided.date()}."))

    if not facts.has_track:
        if facts.dq_issues:
            raw.append(_cond("DATA_EXCEPTION", "RULE-DATA-005", "Invalid source values: " + ", ".join(facts.dq_issues)))
        return raw

    cm = facts.current_milestone
    mtype = cm.get("milestone_type") or "UNKNOWN"

    # Data exceptions
    if not facts.rule_found:
        raw.append(_cond("DATA_EXCEPTION", "RULE-DATA-001", f"No active milestone rule for {mtype}."))
    if facts.milestone_conflicts:
        raw.append(_cond("DATA_EXCEPTION", "RULE-DATA-002",
                         f"Conflicting dates on {mtype}: " + ", ".join(facts.milestone_conflicts)))
    if facts.required_party_type and not facts.party_ok:
        raw.append(_cond("DATA_EXCEPTION", "RULE-DATA-003",
                         f"{mtype} requires an active assigned {facts.required_party_type.lower()}; none assigned."))
    if not facts.specialist_ok:
        raw.append(_cond("DATA_EXCEPTION", "RULE-DATA-004", "No active assigned servicing specialist."))
    if facts.dq_issues:
        raw.append(_cond("DATA_EXCEPTION", "RULE-DATA-005", "Invalid source values: " + ", ".join(facts.dq_issues)))

    # Duplicates: two or more open follow-up-type events of the same type for the current milestone.
    by_type: dict[str, int] = {}
    for ev in facts.open_followups:
        by_type[ev["event_type"]] = by_type.get(ev["event_type"], 0) + 1
    dupes = {k: v for k, v in by_type.items() if v >= 2}
    if dupes:
        raw.append(_cond("DUPLICATE_RISK", "RULE-DUPLICATE-001",
                         ", ".join(f"{v} open {k} events" for k, v in dupes.items()) + f" for {mtype}."))

    rule = facts.rule or {}
    if facts.milestone_complete:
        if facts.next_milestone_type and not facts.next_milestone_exists:
            raw.append(_cond("COMPLETED_NEEDS_NEXT", "RULE-MILESTONE-003",
                             f"{mtype} completed; next milestone {facts.next_milestone_type} not opened."))
        elif facts.rule_found and not facts.next_milestone_type:
            raw.append(_cond("COMPLETED", "RULE-MILESTONE-004", f"Terminal milestone {mtype} complete."))
    else:
        lookahead = rule.get("lookahead_days")
        if lookahead is None:
            lookahead = int(th.get("default_lookahead_days", 7))
        if facts.effective_followup_date is None:
            if facts.rule_found and rule.get("requires_followup"):
                raw.append(_cond("MISSING_FOLLOWUP", "RULE-FOLLOWUP-002", f"{mtype} requires a follow-up date; none exists."))
        else:
            dtf = facts.days_to_followup
            if dtf < 0:
                raw.append(_cond("OVERDUE", "RULE-FOLLOWUP-003",
                                 f"{mtype} follow-up {facts.effective_followup_date} is {facts.days_overdue} days overdue."))
            elif dtf == 0:
                raw.append(_cond("DUE", "RULE-FOLLOWUP-004", f"{mtype} follow-up due today."))
            elif dtf <= int(lookahead):
                raw.append(_cond("UPCOMING", "RULE-FOLLOWUP-005",
                                 f"{mtype} follow-up in {dtf} days (look-ahead {lookahead})."))

    # Already actioned: actionable condition covered by a pending approved action.
    actionable = set(ctx.settings.business_rules.get("actionable_conditions", []))
    if facts.pending_action and any(c["code"] in actionable for c in raw):
        raw.append(_cond("ALREADY_ACTIONED", "RULE-PENDING-002",
                         f"Actionable condition covered by pending action {facts.pending_action['action_id']}."))
    return raw


def select_primary(raw: list[dict], precedence: list[str]) -> tuple[str, list[str]]:
    codes = []
    for c in raw:
        if c["code"] not in codes:
            codes.append(c["code"])
    if not codes:
        return "NO_ACTION", []
    ranked = sorted(codes, key=lambda c: precedence.index(c) if c in precedence else len(precedence))
    return ranked[0], ranked[1:]


def evaluate_conditions(facts: LoanFacts, ctx: EngineContext) -> dict:
    raw = detect_raw_conditions(facts, ctx)
    primary, secondary = select_primary(raw, ctx.settings.business_rules["condition_precedence"])
    rule_ids = sorted({c["rule_id"] for c in raw})
    if primary == "NO_ACTION" and not raw:
        detail = "On track." if facts.has_track else "No servicing track."
        raw_out = [_cond("NO_ACTION", "RULE-NOACTION-001", detail)]
        rule_ids = ["RULE-NOACTION-001"]
    else:
        raw_out = raw
    return {"raw_conditions": raw_out, "primary_condition": primary, "secondary_conditions": secondary,
            "condition_rule_ids": rule_ids}


# ====================================================================================================
# Deterministic escalation (config/escalation_rules.yml, RULE-ESCALATION-001..010)
# ====================================================================================================

def _matches(when: dict, facts: LoanFacts, cond: dict) -> bool:
    primary = cond["primary_condition"]
    codes = {c["code"] for c in cond["raw_conditions"]}
    severity = facts.severity or 0
    checks = {
        "min_days_overdue": lambda v: facts.days_overdue >= v,
        "min_severity": lambda v: severity >= v,
        "max_days_to_followup": lambda v: facts.days_to_followup is not None and facts.days_to_followup <= v,
        "milestone_incomplete": lambda v: (not facts.milestone_complete) == bool(v) and facts.has_track,
        "min_failed_actions": lambda v: facts.failed_action_count >= v,
        "any_condition": lambda v: bool(codes & set(v)),
        "primary_condition_in": lambda v: primary in v,
        "primary_condition_not_in": lambda v: primary not in v,
        "missing_assigned_party": lambda v: (bool(facts.required_party_type) and not facts.party_ok) == bool(v),
        "prior_rejection": lambda v: bool(facts.prior_rejected_actions) == bool(v),
    }
    for key, value in when.items():
        if key not in checks:
            raise ValueError(f"Unknown escalation condition key: {key}")
        if not checks[key](value):
            return False
    return True


def compute_escalation(facts: LoanFacts, cond: dict, ctx: EngineContext) -> dict:
    cfg = ctx.settings.escalation_rules
    order = cfg["states_order"]
    state = "NONE"
    reasons = []
    for rule in cfg["rules"]:
        if _matches(rule.get("when", {}), facts, cond):
            reasons.append({"rule_id": rule["id"], "state": rule["state"], "reason": rule["reason"]})
            if order.index(rule["state"]) > order.index(state):
                state = rule["state"]
    return {
        "escalation_state": state,
        "escalation_reasons": reasons,
        "required_role": cfg["required_roles"][state],
        "health_segment": cfg["health_segments"][state],
        "needs_attention": state in ("FOLLOW_UP", "ESCALATE", "CRITICAL"),
    }


# ====================================================================================================
# Deterministic, explainable attention scoring (config/attention_scoring.yml, RULE-SCORING-001)
# ====================================================================================================

def priority_for(score: int, thresholds: dict) -> str:
    for name, minimum in sorted(thresholds.items(), key=lambda kv: kv[1], reverse=True):
        if score >= minimum:
            return name
    return "LOW"


def compute_attention_score(facts: LoanFacts, cond: dict, ctx: EngineContext) -> dict:
    cfg = ctx.settings.attention_scoring
    f = cfg["factors"]
    primary = cond["primary_condition"]
    drivers: list[dict] = []

    def add(factor: str, points: int, detail: str) -> None:
        if points:
            drivers.append({"factor": factor, "points": int(points), "detail": detail})

    add("primary_condition", cfg["condition_points"].get(primary, 0), primary)
    if facts.days_overdue:
        pts = min(f["days_overdue"]["max_points"], facts.days_overdue * f["days_overdue"]["points_per_unit"])
        add("days_overdue", pts, f"{facts.days_overdue} days overdue")
    if facts.has_track and primary not in cfg.get("severity_applies_to_conditions_except", []):
        severity = facts.severity if facts.severity is not None else cfg.get("default_missing_rule_severity", 3)
        mtype = facts.current_milestone.get("milestone_type")
        pts = min(f["milestone_severity"]["max_points"], severity * f["milestone_severity"]["points_per_unit"])
        add("milestone_severity", pts, f"{mtype} severity {severity}" + ("" if facts.rule_found else " (default)"))
    secondary = cond["secondary_conditions"]
    if secondary:
        pts = min(f["secondary_conditions"]["max_points"], len(secondary) * f["secondary_conditions"]["points_per_unit"])
        add("secondary_conditions", pts, ", ".join(secondary))
    if facts.failed_action_count:
        pts = min(f["failed_actions"]["max_points"], facts.failed_action_count * f["failed_actions"]["points_per_unit"])
        add("failed_actions", pts, f"{facts.failed_action_count} failed/unverified action(s)")
    if facts.required_party_type and not facts.party_ok:
        add("missing_assigned_party", f["missing_assigned_party"]["points"], f"No active {facts.required_party_type.lower()}")
    if facts.prior_rejected_actions:
        add("prior_rejection", f["prior_rejection"]["points"], "Rejected: " + ", ".join(facts.prior_rejected_actions))
    cdp = f["critical_date_proximity"]
    if (facts.has_track and not facts.milestone_complete and (facts.severity or 0) >= cdp["min_severity"]
            and facts.days_to_followup is not None and facts.days_to_followup <= cdp["max_days_to_followup"]
            and primary not in ("ALREADY_ACTIONED", "PENDING_ACTION")):
        add("critical_date_proximity", cdp["points"], f"Severity {facts.severity} milestone within {cdp['max_days_to_followup']} days")
    if primary == "ALREADY_ACTIONED":
        add("covered_by_pending_action", f["covered_by_pending_action"]["points"], "Covered by a pending approved action")

    score = max(0, min(cfg["max_score"], sum(d["points"] for d in drivers)))
    return {
        "score": int(score),
        "priority": priority_for(score, cfg["priority_thresholds"]),
        "score_drivers": drivers,
        "calculated_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds"),
        "scoring_version": cfg["version"],
    }


def drivers_text(drivers: list[dict], top: int = 3) -> str:
    ranked = sorted(drivers, key=lambda d: d["points"], reverse=True)[:top]
    return "; ".join(f"{d['detail']} ({d['points']:+d})" for d in ranked)


# ====================================================================================================
# Allowed actions (config/allowed_actions.yml, RULE-ACTIONS-001, RULE-REVIEW-001)
# ====================================================================================================

def _dedupe(seq: list[str]) -> list[str]:
    out: list[str] = []
    for item in seq:
        if item and item not in out:
            out.append(item)
    return out


def compute_allowed_actions(facts: LoanFacts, cond: dict, escalation: dict, ctx: EngineContext) -> dict:
    cfg = ctx.settings.allowed_actions
    primary = cond["primary_condition"]
    removed: list[dict] = []

    base = list(cfg["by_condition"].get(primary, ["NO_ACTION"]))
    if primary == "VERIFICATION_FAILURE" and facts.latest_verification:
        override = cfg.get("verification_overrides", {}).get(facts.latest_verification["verification_status"])
        if override:
            base = list(override)
    overdue_action = (facts.rule or {}).get("overdue_action") or "CREATE_FOLLOWUP"
    if overdue_action == "NO_ACTION":
        overdue_action = "CREATE_FOLLOWUP"
    actions = _dedupe([overdue_action if a == "MILESTONE_OVERDUE_ACTION" else a for a in base])

    state = escalation["escalation_state"]
    if primary not in cfg.get("escalation_adjustment_exempt_conditions", []):
        adj = cfg.get("escalation_adjustments", {}).get(state, {})
        actions = _dedupe(list(adj.get("prepend", [])) + actions + list(adj.get("append", [])))

    # Contact actions need an active party of the required type.
    party = ctx.parties_by_id.get(facts.loan.get("assigned_attorney_vendor_id") or "")
    kept = []
    for action in actions:
        required = cfg["actions"].get(action, {}).get("requires_party_type")
        if required and not (party and party.get("active") and party.get("party_type") == required):
            removed.append({"action": action, "reason": f"No active assigned {required.lower()}", "rule_id": "RULE-DATA-003"})
            continue
        kept.append(action)
    actions = kept

    # RULE-REVIEW-001: prior rejection, unless escalated.
    if facts.prior_rejected_actions and state not in ("ESCALATE", "CRITICAL"):
        kept = []
        for action in actions:
            if action in facts.prior_rejected_actions and action != "NO_ACTION":
                removed.append({"action": action, "reason": "Rejected by a reviewer inside the lookback window",
                                "rule_id": "RULE-REVIEW-001"})
                continue
            kept.append(action)
        actions = kept

    if not actions:
        actions = ["REQUEST_INFORMATION"]
    return {"allowed_actions": actions, "default_action": actions[0], "removed_actions": removed,
            "rule_id": "RULE-ACTIONS-001", "actions_version": cfg["version"]}


# ====================================================================================================
# Date logic: days to follow-up and follow-up date calculation (RULE-FOLLOWUP-006)
# ====================================================================================================

def days_between(start: date, end: date) -> int:
    return (end - start).days


def roll_to_business_day(day: date) -> date:
    while day.weekday() >= 5:  # Saturday=5, Sunday=6
        day += timedelta(days=1)
    return day


def followup_days_for(action_type: str, facts: LoanFacts, ctx: EngineContext, original_action: dict | None = None) -> tuple[int, str]:
    """Return (days, basis) for the proposed follow-up of ``action_type``."""
    spec = ctx.settings.allowed_actions["actions"].get(action_type, {})
    setting = spec.get("followup_days")
    if setting == "milestone_default":
        days = (facts.rule or {}).get("default_followup_days") or 14
        return int(days), f"{(facts.current_milestone or {}).get('milestone_type')} default_followup_days"
    if setting == "next_milestone_default":
        nxt = ctx.rules_by_type.get(facts.next_milestone_type or "", {})
        return int(nxt.get("default_followup_days") or 14), f"{facts.next_milestone_type} default_followup_days"
    if setting is None:
        return 0, "no follow-up"
    return int(setting), f"{action_type} followup_days"


def calculate_followup_date(action_type: str, facts: LoanFacts, ctx: EngineContext) -> dict:
    days, basis = followup_days_for(action_type, facts, ctx)
    if days <= 0:
        return {"followup_date": None, "days": 0, "basis": basis, "rolled": False, "rule_id": "RULE-FOLLOWUP-006"}
    raw = ctx.processing_date + timedelta(days=days)
    rolled = roll_to_business_day(raw) if ctx.thresholds.get("business_days_only", True) else raw
    return {"followup_date": rolled.isoformat(), "days": days, "basis": basis, "rolled": rolled != raw,
            "rule_id": "RULE-FOLLOWUP-006"}


# ====================================================================================================
# Outbound event preparation and validation (RULE-DUPLICATE-002, RULE-VALIDATION-001)
# ====================================================================================================

def event_type_for(action_type: str, ctx: EngineContext, original_action: dict | None = None) -> str | None:
    spec = ctx.settings.allowed_actions["actions"].get(action_type, {})
    if not spec.get("creates_event"):
        return None
    event_type = spec.get("event_type")
    if event_type == "from_original_action":
        return (original_action or {}).get("event_type") or "FOLLOWUP"
    return event_type


def milestone_for(action_type: str, facts: LoanFacts, original_action: dict | None = None) -> str | None:
    if action_type == "CREATE_NEXT_MILESTONE":
        return facts.next_milestone_type
    if action_type == "RETRY_FAILED_ACTION" and original_action and original_action.get("milestone_type"):
        return original_action["milestone_type"]
    return (facts.current_milestone or {}).get("milestone_type")


def idempotency_key(loan_id: str, action_type: str, milestone: str | None, event_date: date) -> str:
    raw = f"{loan_id}|{action_type}|{milestone or ''}|{event_date.isoformat()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def prepare_event(action_type: str, facts: LoanFacts, ctx: EngineContext, followup_date: str | None = None,
                  note: str | None = None, outreach: str | None = None, escalation_target: str | None = None,
                  original_action: dict | None = None) -> dict:
    """Build an uncommitted, loan-servicing-system-compatible outbound event draft."""

    P = ctx.processing_date
    event_type = event_type_for(action_type, ctx, original_action)
    milestone = milestone_for(action_type, facts, original_action)
    if event_type is None:
        return {"loan_id": facts.loan_id, "action_type": action_type, "event_type": None, "creates_event": False,
                "status": "NO_EVENT", "synthetic_data": True}
    calc = calculate_followup_date(action_type, facts, ctx)
    fu = followup_date or calc["followup_date"]
    party_id = facts.loan.get("assigned_attorney_vendor_id") or None
    party = ctx.parties_by_id.get(party_id or "", {})
    return {
        "loan_id": facts.loan_id,
        "action_type": action_type,
        "event_type": event_type,
        "milestone_type": milestone,
        "event_date": P.isoformat(),
        "followup_date": fu,
        "followup_basis": calc["basis"] if not followup_date else "reviewer edit",
        "event_note": (note or "").strip(),
        "outreach_text": (outreach or "").strip(),
        "assigned_party_id": party_id,
        "assigned_party_type": party.get("party_type"),
        "escalation_target_role": escalation_target if action_type == "ESCALATE_TO_SPECIALIST" else None,
        "retry_of_action_id": (original_action or {}).get("action_id") if action_type == "RETRY_FAILED_ACTION" else None,
        "source_system": "LOAN_SERVICING_INTELLIGENCE",
        "idempotency_key": idempotency_key(facts.loan_id, action_type, milestone, P),
        "creates_event": True,
        "status": "DRAFT_UNCOMMITTED",
        "synthetic_data": True,
    }


def check_existing_event(facts: LoanFacts, event_type: str | None, milestone_type: str | None,
                         action_type: str | None, ctx: EngineContext) -> dict:
    """RULE-DUPLICATE-001/002."""
    P = ctx.processing_date
    equivalent = []
    if event_type == "MILESTONE":
        equivalent = [e for e in facts.events if (e.get("milestone_type") or "") == (milestone_type or "")
                      and e.get("event_type") == "MILESTONE" and e.get("status") != "CANCELLED"]
    elif event_type:
        for e in facts.events:
            if e.get("event_type") != event_type or e.get("status") != "OPEN":
                continue
            if milestone_type and (e.get("milestone_type") or "") != milestone_type:
                continue
            fu = _as_date(e.get("followup_date"))
            if fu is None or fu >= P:
                equivalent.append(e)
    same_pending = bool(facts.pending_action and action_type and facts.pending_action.get("action_type") == action_type)
    open_same_type = {}
    for e in facts.open_followups:
        open_same_type[e["event_type"]] = open_same_type.get(e["event_type"], 0) + 1
    return {
        "open_equivalent_events": [
            {"event_id": e["event_id"], "event_type": e["event_type"], "milestone_type": e.get("milestone_type"),
             "followup_date": str(_as_date(e.get("followup_date")) or ""), "status": e.get("status")}
            for e in equivalent],
        "pending_action_same_type": same_pending,
        "duplicate_risk": bool(equivalent) or same_pending,
        "existing_duplicate_open_events": {k: v for k, v in open_same_type.items() if v >= 2},
        "rule_ids": ["RULE-DUPLICATE-001", "RULE-DUPLICATE-002"],
    }


def validate_proposed_event(draft: dict, facts: LoanFacts, evaluation: dict, ctx: EngineContext,
                            recommendation_fingerprint: str | None = None,
                            recommendation_rule_version: str | None = None) -> dict:
    th = ctx.thresholds
    P = ctx.processing_date
    errors: list[dict] = []
    warnings: list[dict] = []
    action = draft.get("action_type")

    def err(code: str, message: str) -> None:
        errors.append({"code": code, "message": message})

    if action not in evaluation["allowed_actions"]:
        err("ACTION_NOT_ALLOWED", f"{action} is not in allowed actions {evaluation['allowed_actions']}.")
    if not facts.loan.get("is_active", True):
        err("LOAN_INACTIVE", "Loan is not active.")
    if recommendation_fingerprint and recommendation_fingerprint != evaluation["state_fingerprint"]:
        err("STALE_RECOMMENDATION", "Loan state changed since the recommendation was generated; re-run analysis.")
    if recommendation_rule_version and recommendation_rule_version != ctx.settings.rule_version:
        err("STALE_RECOMMENDATION", "Rule version changed since the recommendation was generated.")

    if not draft.get("creates_event"):
        warnings.append({"code": "NO_EVENT_FOR_ACTION", "message": "NO_ACTION produces no outbound event."})
        return {"valid": not errors, "errors": errors, "warnings": warnings, "rule_id": "RULE-VALIDATION-001"}

    expected_type = event_type_for(action, ctx, {"event_type": draft.get("event_type")}) if action else None
    if action != "RETRY_FAILED_ACTION" and draft.get("event_type") != expected_type:
        err("EVENT_TYPE_MISMATCH", f"{action} must create {expected_type}, not {draft.get('event_type')}.")
    fu = _as_date(draft.get("followup_date"))
    horizon = P + timedelta(days=int(th.get("max_followup_horizon_days", 120)))
    if fu is None or fu < P or fu > horizon:
        err("FOLLOWUP_OUT_OF_RANGE", f"Follow-up date must be between {P} and {horizon}.")
    required = ctx.settings.allowed_actions["actions"].get(action, {}).get("requires_party_type")
    if required:
        party = ctx.parties_by_id.get(draft.get("assigned_party_id") or "")
        if not (party and party.get("active") and party.get("party_type") == required):
            err("PARTY_REQUIRED", f"{action} requires an active assigned {required.lower()}.")
    if len(draft.get("event_note") or "") > int(th.get("max_note_length", 1000)):
        err("NOTE_TOO_LONG", "Note exceeds the maximum length.")
    if action != "REVIEW_DATA_EXCEPTION":
        dup = check_existing_event(facts, draft.get("event_type"), draft.get("milestone_type"), action, ctx)
        if dup["duplicate_risk"]:
            err("DUPLICATE_EVENT", "An equivalent open event or pending action already exists.")
    if facts.pending_action and action != "RETRY_FAILED_ACTION":
        err("PENDING_ACTION_EXISTS", f"Action {facts.pending_action['action_id']} is still awaiting verification.")
    return {"valid": not errors, "errors": errors, "warnings": warnings, "rule_id": "RULE-VALIDATION-001"}


# ====================================================================================================
# Portfolio evaluation engine: facts -> conditions -> escalation -> score -> allowed actions
# ====================================================================================================

@dataclass
class PortfolioEvaluation:
    ctx: EngineContext
    silver: SilverDataset
    facts: dict[str, LoanFacts]
    results: dict[str, dict]
    duration_ms: float = 0.0
    loan_ids: list[str] = field(default_factory=list)

    @property
    def processing_date(self) -> date:
        return self.ctx.processing_date

    def get(self, loan_id: str) -> dict | None:
        return self.results.get(loan_id)

    def active_results(self) -> list[dict]:
        return [r for r in self.results.values() if r["is_active"]]

    def all_verifications(self) -> list[dict]:
        out = []
        for facts in self.facts.values():
            for action in facts.actions:
                v = facts.verifications[action["action_id"]]
                out.append({**v, "action_type": action.get("action_type"), "event_type": action.get("event_type"),
                            "action_status": action.get("status"), "submitted_at": action.get("submitted_at"),
                            "action_event_date": action.get("event_date"), "followup_date": action.get("followup_date")})
        return out


def state_fingerprint(facts: LoanFacts, primary: str, rule_version: str) -> str:
    parts = [
        primary,
        (facts.current_milestone or {}).get("event_id") or "",
        str(facts.effective_followup_date or ""),
        (facts.pending_action or {}).get("action_id") or "",
        (facts.latest_verification or {}).get("verification_status") or "",
        str(len(facts.open_followups)),
        rule_version,
    ]
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:12]


def evaluate_loan(facts: LoanFacts, ctx: EngineContext) -> dict:
    cond = evaluate_conditions(facts, ctx)
    esc = compute_escalation(facts, cond, ctx)
    score = compute_attention_score(facts, cond, ctx)
    allowed = compute_allowed_actions(facts, cond, esc, ctx)
    loan = facts.loan
    cm = facts.current_milestone or {}
    primary = cond["primary_condition"]
    return {
        "loan_id": facts.loan_id,
        "borrower_display_name": loan.get("borrower_display_name"),
        "property_state": loan.get("property_state"),
        "property_county": loan.get("property_county"),
        "portfolio_id": loan.get("portfolio_id"),
        "current_balance": loan.get("current_balance"),
        "payment_status": loan.get("payment_status"),
        "days_delinquent": loan.get("days_delinquent"),
        "loan_status": loan.get("loan_status"),
        "foreclosure_status": loan.get("foreclosure_status"),
        "is_active": bool(loan.get("is_active")),
        "assigned_specialist_id": loan.get("assigned_specialist_id"),
        "specialist_name": loan.get("specialist_name"),
        "assigned_party_id": loan.get("assigned_attorney_vendor_id") or None,
        "party_name": loan.get("party_name") or None,
        "party_type": loan.get("party_type") or None,
        "current_milestone": cm.get("milestone_type"),
        "milestone_sequence": cm.get("milestone_sequence"),
        "milestone_status": cm.get("status"),
        "milestone_event_id": cm.get("event_id"),
        "milestone_complete": facts.milestone_complete,
        "milestone_severity": facts.severity,
        "effective_followup_date": facts.effective_followup_date.isoformat() if facts.effective_followup_date else None,
        "days_to_followup": facts.days_to_followup,
        "days_overdue": facts.days_overdue,
        "raw_conditions": cond["raw_conditions"],
        "primary_condition": primary,
        "secondary_conditions": cond["secondary_conditions"],
        "condition_rule_ids": cond["condition_rule_ids"],
        **{k: esc[k] for k in ("escalation_state", "escalation_reasons", "required_role", "health_segment",
                               "needs_attention")},
        "allowed_actions": allowed["allowed_actions"],
        "default_action": allowed["default_action"],
        "removed_actions": allowed["removed_actions"],
        "attention_score": score["score"],
        "priority": score["priority"],
        "score_drivers": score["score_drivers"],
        "top_drivers_text": drivers_text(score["score_drivers"]),
        "pending_action_id": (facts.pending_action or {}).get("action_id"),
        "latest_action_id": (facts.latest_action or {}).get("action_id"),
        "latest_verification_status": (facts.latest_verification or {}).get("verification_status"),
        "failed_action_count": facts.failed_action_count,
        "prior_rejected_actions": facts.prior_rejected_actions,
        "state_fingerprint": state_fingerprint(facts, primary, ctx.settings.rule_version),
        "processing_date": ctx.processing_date.isoformat(),
        "rule_version": ctx.settings.rule_version,
        "scoring_version": score["scoring_version"],
        "calculated_at": score["calculated_at"],
    }


def _group(frame: pd.DataFrame, key: str = "loan_id") -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    if frame is None or frame.empty:
        return grouped
    for rec in frame.to_dict("records"):
        grouped.setdefault(rec[key], []).append(_clean(rec))
    return grouped


def evaluate_portfolio(silver: SilverDataset, settings, processing_date: date | None = None) -> PortfolioEvaluation:
    started = time.perf_counter()
    ctx = EngineContext.build(settings, silver, processing_date)
    events = _group(silver.loan_events)
    actions = _group(silver.servicing_action_history)
    decisions = _group(silver.reviewer_decisions)
    facts_by_loan: dict[str, LoanFacts] = {}
    results: dict[str, dict] = {}
    loan_ids = []
    for loan in silver.loans.to_dict("records"):
        loan = _clean(loan)
        lid = loan["loan_id"]
        loan_ids.append(lid)
        facts = build_loan_facts(loan, events.get(lid, []), actions.get(lid, []), decisions.get(lid, []), ctx)
        facts_by_loan[lid] = facts
        results[lid] = evaluate_loan(facts, ctx)
    return PortfolioEvaluation(ctx=ctx, silver=silver, facts=facts_by_loan, results=results,
                               duration_ms=(time.perf_counter() - started) * 1000, loan_ids=loan_ids)


def milestone_state_rows(evaluation: PortfolioEvaluation) -> list[dict]:
    rows = []
    for lid, facts in evaluation.facts.items():
        current_id = (facts.current_milestone or {}).get("event_id")
        for ev in facts.milestone_events:
            rows.append({
                "loan_id": lid,
                "milestone_type": ev.get("milestone_type"),
                "milestone_sequence": ev.get("milestone_sequence"),
                "event_id": ev["event_id"],
                "event_date": str(_as_date(ev.get("event_date")) or ""),
                "followup_date": str(_as_date(ev.get("followup_date")) or ""),
                "completed_date": str(_as_date(ev.get("completed_date")) or ""),
                "status": ev.get("status"),
                "is_current": ev["event_id"] == current_id,
                "is_complete": ev.get("status") == "COMPLETED" and _as_date(ev.get("completed_date")) is not None,
                "dq_issues": ev.get("dq_issues") or "",
            })
    return rows
