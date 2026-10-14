"""Medallion layers: Bronze (raw + lineage), Silver (typed, validated), Gold (servicing state tables)."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, fields
from datetime import date, datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from src.rules import PortfolioEvaluation

from src.synthetic_data import ACTION_STATUSES, DECISIONS, EVENT_SOURCES, EVENT_STATUSES, EVENT_TYPES, FORECLOSURE_STATUSES, LOAN_STATUSES, PAYMENT_STATUSES


# ====================================================================================================
# Bronze ingestion: preserve source values as strings and add lineage columns
# ====================================================================================================

# Bronze table name -> source file name
SOURCE_FILES = {
    "bronze_loans": "loans.csv",
    "bronze_loan_events": "loan_events.csv",
    "bronze_milestone_rules": "milestone_rules.csv",
    "bronze_servicing_specialists": "servicing_specialists.csv",
    "bronze_attorneys_vendors": "attorneys_vendors.csv",
    "bronze_servicing_action_history": "servicing_action_history.csv",
    "bronze_reviewer_decisions": "reviewer_decisions.csv",
}
LINEAGE_COLUMNS = ["source_file", "ingested_at", "batch_id", "record_hash", "source_row_number"]


def new_batch_id(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return f"BATCH-{now:%Y%m%d%H%M%S}"


def record_hash(values: list[str]) -> str:
    return hashlib.sha256("|".join("" if v is None else str(v) for v in values).encode("utf-8")).hexdigest()


def read_source_csv(path: str | Path) -> pd.DataFrame:
    """Read a CSV keeping every value as the exact source string (no NA coercion)."""
    return pd.read_csv(path, dtype=str, keep_default_na=False, na_filter=False)


def to_bronze(raw: pd.DataFrame, source_file: str, batch_id: str, ingested_at: str | None = None) -> pd.DataFrame:
    """Return a bronze frame: source columns unchanged + lineage columns."""
    ingested_at = ingested_at or datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
    bronze = raw.copy()
    source_cols = list(raw.columns)
    bronze["source_file"] = source_file
    bronze["ingested_at"] = ingested_at
    bronze["batch_id"] = batch_id
    bronze["record_hash"] = [record_hash(list(row)) for row in raw[source_cols].itertuples(index=False)]
    bronze["source_row_number"] = range(1, len(raw) + 1)
    return bronze


def ingest_directory(directory: str | Path, batch_id: str | None = None) -> dict[str, pd.DataFrame]:
    """Ingest every known source file in ``directory`` into bronze frames."""
    directory = Path(directory)
    batch_id = batch_id or new_batch_id()
    bronze: dict[str, pd.DataFrame] = {}
    for table, filename in SOURCE_FILES.items():
        path = directory / filename
        if not path.exists():
            raise FileNotFoundError(f"Missing source export: {path}")
        bronze[table] = to_bronze(read_source_csv(path), filename, batch_id)
    return bronze


# ====================================================================================================
# Silver standardization: typing, validation, deduplication, normalization, sequencing, DQ flags
# ====================================================================================================

FOLLOWUP_EVENT_TYPES_DEFAULT = ["FOLLOWUP", "CONTACT", "ESCALATION", "INFO_REQUEST", "DATA_REVIEW"]
SOR_EXTRA_COLUMNS = ["available_cycle", "action_id"]


@dataclass
class SilverDataset:
    loans: pd.DataFrame
    loan_events: pd.DataFrame
    milestone_rules: pd.DataFrame
    servicing_specialists: pd.DataFrame
    attorneys_vendors: pd.DataFrame
    active_foreclosures: pd.DataFrame
    servicing_action_history: pd.DataFrame
    reviewer_decisions: pd.DataFrame

    def tables(self) -> dict[str, pd.DataFrame]:
        return {f"silver_{f.name}": getattr(self, f.name) for f in fields(self)}

    def copy(self) -> "SilverDataset":
        return SilverDataset(**{f.name: getattr(self, f.name).copy() for f in fields(self)})


# ---------------------------------------------------------------------------------------------
# typing helpers
# ---------------------------------------------------------------------------------------------
def _blank(series: pd.Series) -> pd.Series:
    return series.isna() | (series.astype(str).str.strip() == "")


def _add_issue(issues: pd.Series, mask: pd.Series, code: str) -> pd.Series:
    return issues.where(~mask, issues.where(issues == "", issues + ";") + code)


def _clean_str(series: pd.Series, upper: bool = False) -> pd.Series:
    s = series.fillna("").astype(str).str.strip()
    return s.str.upper() if upper else s


def _to_date(df: pd.DataFrame, col: str, issues: pd.Series) -> tuple[pd.Series, pd.Series]:
    raw = _clean_str(df[col]) if col in df else pd.Series([""] * len(df), index=df.index)
    parsed = pd.to_datetime(raw.where(raw != ""), errors="coerce", format="mixed")
    invalid = (raw != "") & parsed.isna()
    issues = _add_issue(issues, invalid, f"INVALID_DATE:{col}")
    values = parsed.dt.date.astype(object).where(parsed.notna(), None)
    return values, issues


def _to_ts(df: pd.DataFrame, col: str, issues: pd.Series) -> tuple[pd.Series, pd.Series]:
    raw = _clean_str(df[col]) if col in df else pd.Series([""] * len(df), index=df.index)
    parsed = pd.to_datetime(raw.where(raw != ""), errors="coerce", format="mixed", utc=True)
    invalid = (raw != "") & parsed.isna()
    issues = _add_issue(issues, invalid, f"INVALID_TIMESTAMP:{col}")
    return parsed.dt.tz_localize(None), issues


def _to_num(df: pd.DataFrame, col: str, issues: pd.Series, integer: bool = False) -> tuple[pd.Series, pd.Series]:
    raw = _clean_str(df[col])
    parsed = pd.to_numeric(raw.where(raw != ""), errors="coerce")
    invalid = (raw != "") & parsed.isna()
    issues = _add_issue(issues, invalid, f"INVALID_NUMBER:{col}")
    if integer:
        parsed = parsed.round().astype("Int64")
    return parsed, issues


def _to_bool(series: pd.Series) -> pd.Series:
    return _clean_str(series).str.lower().isin(["true", "1", "yes", "y", "t"])


def _check_domain(values: pd.Series, allowed: list[str], col: str, issues: pd.Series,
                  required: bool = True) -> pd.Series:
    unknown = (values != "") & ~values.isin(allowed)
    issues = _add_issue(issues, unknown, f"UNKNOWN_CODE:{col}")
    if required:
        issues = _add_issue(issues, values == "", f"MISSING_REQUIRED:{col}")
    return issues


def _drop_lineage(df: pd.DataFrame) -> pd.DataFrame:
    return df.drop(columns=[c for c in ("source_file", "ingested_at", "batch_id", "record_hash",
                                        "source_row_number") if c in df.columns])


def _issues(df: pd.DataFrame) -> pd.Series:
    if "dq_issues" in df.columns:
        return df["dq_issues"].fillna("").astype(str)
    return pd.Series([""] * len(df), index=df.index, dtype=object)


# ---------------------------------------------------------------------------------------------
# per-table standardization
# ---------------------------------------------------------------------------------------------
def standardize_milestone_rules(raw: pd.DataFrame) -> pd.DataFrame:
    df = _drop_lineage(raw).copy()
    issues = _issues(df)
    df["milestone_type"] = _clean_str(df["milestone_type"], upper=True)
    for col in ("milestone_sequence", "default_followup_days", "lookahead_days", "severity"):
        df[col], issues = _to_num(df, col, issues, integer=True)
    df["requires_followup"] = _to_bool(df["requires_followup"])
    df["active"] = _to_bool(df["active"])
    df["overdue_action"] = _clean_str(df["overdue_action"], upper=True)
    df["next_milestone_type"] = _clean_str(df["next_milestone_type"], upper=True).replace("", None)
    df["synthetic_data"] = _to_bool(df.get("synthetic_data", pd.Series(["true"] * len(df), index=df.index)))
    df["dq_issues"] = issues
    return df.drop_duplicates("milestone_type", keep="last").reset_index(drop=True)


def standardize_specialists(raw: pd.DataFrame) -> pd.DataFrame:
    df = _drop_lineage(raw).copy()
    df["specialist_id"] = _clean_str(df["specialist_id"], upper=True)
    df["display_name"] = _clean_str(df["display_name"])
    df["team"] = _clean_str(df["team"])
    df["active"] = _to_bool(df["active"])
    df["synthetic_data"] = _to_bool(df["synthetic_data"])
    return df.drop_duplicates("specialist_id", keep="last").reset_index(drop=True)


def standardize_parties(raw: pd.DataFrame) -> pd.DataFrame:
    df = _drop_lineage(raw).copy()
    df["party_id"] = _clean_str(df["party_id"], upper=True)
    df["display_name"] = _clean_str(df["display_name"])
    df["party_type"] = _clean_str(df["party_type"], upper=True)
    df["state"] = _clean_str(df["state"], upper=True)
    df["active"] = _to_bool(df["active"])
    df["synthetic_data"] = _to_bool(df["synthetic_data"])
    return df.drop_duplicates("party_id", keep="last").reset_index(drop=True)


def standardize_loans(raw: pd.DataFrame, specialists: pd.DataFrame, parties: pd.DataFrame,
                      active_statuses: list[str] | None = None) -> pd.DataFrame:
    df = _drop_lineage(raw).copy()
    issues = _issues(df)
    for col in ("loan_id", "loan_status", "payment_status", "foreclosure_status", "assigned_specialist_id",
                "assigned_attorney_vendor_id", "portfolio_id", "property_state"):
        df[col] = _clean_str(df[col], upper=True)
    for col in ("borrower_display_name", "property_address", "property_city", "property_postal_code",
                "property_county"):
        df[col] = _clean_str(df[col])
    issues = _add_issue(issues, df["loan_id"] == "", "MISSING_REQUIRED:loan_id")
    issues = _check_domain(df["loan_status"], LOAN_STATUSES, "loan_status", issues)
    issues = _check_domain(df["payment_status"], PAYMENT_STATUSES, "payment_status", issues)
    issues = _check_domain(df["foreclosure_status"], FORECLOSURE_STATUSES, "foreclosure_status", issues)
    df["original_balance"], issues = _to_num(df, "original_balance", issues)
    df["current_balance"], issues = _to_num(df, "current_balance", issues)
    df["days_delinquent"], issues = _to_num(df, "days_delinquent", issues, integer=True)
    df["boarding_date"], issues = _to_date(df, "boarding_date", issues)
    df["synthetic_data"] = _to_bool(df["synthetic_data"])
    df["dq_issues"] = issues
    df = df.drop_duplicates("loan_id", keep="last")

    spec = specialists.rename(columns={"specialist_id": "assigned_specialist_id", "display_name": "specialist_name",
                                       "active": "specialist_active"})[
        ["assigned_specialist_id", "specialist_name", "specialist_active", "team"]]
    party = parties.rename(columns={"party_id": "assigned_attorney_vendor_id", "display_name": "party_name",
                                    "active": "party_active", "state": "party_state"})[
        ["assigned_attorney_vendor_id", "party_name", "party_type", "party_active"]]
    df = df.merge(spec, how="left", on="assigned_specialist_id").merge(party, how="left",
                                                                         on="assigned_attorney_vendor_id")
    df["specialist_active"] = df["specialist_active"].eq(True)
    df["party_active"] = df["party_active"].eq(True)
    for col in ("specialist_name", "party_name", "party_type", "team"):
        df[col] = df[col].fillna("")
    df["is_active"] = df["loan_status"].isin(active_statuses or ["ACTIVE"])
    return df.reset_index(drop=True)


def standardize_events(raw: pd.DataFrame, rules: pd.DataFrame,
                       followup_event_types: list[str] | None = None) -> pd.DataFrame:
    df = _drop_lineage(raw).copy()
    issues = _issues(df)
    for col in ("event_id", "loan_id", "event_type", "milestone_type", "status", "source"):
        df[col] = _clean_str(df[col], upper=True)
    df["event_note"] = _clean_str(df["event_note"])
    issues = _check_domain(df["event_type"], EVENT_TYPES, "event_type", issues)
    issues = _check_domain(df["status"], EVENT_STATUSES, "status", issues)
    issues = _check_domain(df["source"], EVENT_SOURCES, "source", issues)
    df["event_date"], issues = _to_date(df, "event_date", issues)
    df["followup_date"], issues = _to_date(df, "followup_date", issues)
    df["completed_date"], issues = _to_date(df, "completed_date", issues)
    df["created_at"], issues = _to_ts(df, "created_at", issues)
    df["updated_at"], issues = _to_ts(df, "updated_at", issues)
    issues = _add_issue(issues, df["event_date"].isna(), "MISSING_REQUIRED:event_date")

    is_milestone = df["event_type"] == "MILESTONE"
    has_completed = df["completed_date"].notna()
    completed_before = has_completed & df["event_date"].notna() & (
        pd.to_datetime(df["completed_date"]) < pd.to_datetime(df["event_date"]))
    issues = _add_issue(issues, is_milestone & completed_before, "COMPLETED_BEFORE_EVENT")
    issues = _add_issue(issues, is_milestone & (df["status"] == "COMPLETED") & ~has_completed,
                        "COMPLETED_WITHOUT_DATE")
    issues = _add_issue(issues, is_milestone & (df["status"] == "OPEN") & has_completed,
                        "OPEN_WITH_COMPLETED_DATE")
    df["synthetic_data"] = _to_bool(df["synthetic_data"])
    df["dq_issues"] = issues

    # Deduplicate by event_id keeping the latest update (supports System-of-Record upserts).
    df = df.sort_values(["event_id", "updated_at"], na_position="first").drop_duplicates("event_id", keep="last")

    active_rules = rules[rules["active"]][["milestone_type", "milestone_sequence"]]
    df = df.drop(columns=[c for c in ("milestone_sequence",) if c in df.columns]).merge(
        active_rules, how="left", on="milestone_type")
    df["milestone_sequence"] = df["milestone_sequence"].fillna(-1).astype(int)
    df["is_open"] = df["status"] == "OPEN"
    df["is_followup_type"] = df["event_type"].isin(followup_event_types or FOLLOWUP_EVENT_TYPES_DEFAULT)
    df = df.sort_values(["loan_id", "event_date", "created_at", "event_id"], na_position="first")
    df["event_sequence"] = df.groupby("loan_id").cumcount() + 1
    return df.reset_index(drop=True)


def standardize_actions(raw: pd.DataFrame) -> pd.DataFrame:
    df = _drop_lineage(raw).copy()
    issues = _issues(df)
    for col in ("action_id", "loan_id", "recommendation_id", "action_type", "event_type", "status"):
        df[col] = _clean_str(df[col], upper=True)
    issues = _check_domain(df["status"], ACTION_STATUSES, "status", issues)
    df["failure_reason"] = _clean_str(df["failure_reason"])
    if "milestone_type" in df.columns:
        df["milestone_type"] = _clean_str(df["milestone_type"], upper=True)
    else:
        df["milestone_type"] = ""
    df["event_date"], issues = _to_date(df, "event_date", issues)
    df["followup_date"], issues = _to_date(df, "followup_date", issues)
    df["submitted_at"], issues = _to_ts(df, "submitted_at", issues)
    df["verified_at"], issues = _to_ts(df, "verified_at", issues)
    df["synthetic_data"] = _to_bool(df["synthetic_data"]) if "synthetic_data" in df else True
    df["dq_issues"] = issues
    return df.drop_duplicates("action_id", keep="last").reset_index(drop=True)


def standardize_decisions(raw: pd.DataFrame) -> pd.DataFrame:
    df = _drop_lineage(raw).copy()
    issues = _issues(df)
    for col in ("decision_id", "recommendation_id", "loan_id", "reviewer_id", "decision", "original_action",
                "final_action"):
        df[col] = _clean_str(df[col], upper=True)
    issues = _check_domain(df["decision"], DECISIONS, "decision", issues)
    for col in ("original_note", "final_note", "reason"):
        df[col] = _clean_str(df[col])
    df["original_followup_date"], issues = _to_date(df, "original_followup_date", issues)
    df["final_followup_date"], issues = _to_date(df, "final_followup_date", issues)
    df["decided_at"], issues = _to_ts(df, "decided_at", issues)
    df["synthetic_data"] = _to_bool(df["synthetic_data"]) if "synthetic_data" in df else True
    df["dq_issues"] = issues
    return df.drop_duplicates("decision_id", keep="last").reset_index(drop=True)


def build_active_foreclosures(loans: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    milestones = events[(events["event_type"] == "MILESTONE") & (events["status"] != "CANCELLED")]
    current = (milestones.sort_values(["loan_id", "milestone_sequence", "event_date", "created_at"])
               .groupby("loan_id").tail(1)[["loan_id", "milestone_type", "event_date", "followup_date", "status"]]
               .rename(columns={"milestone_type": "current_milestone", "event_date": "milestone_opened",
                                "followup_date": "milestone_followup_date", "status": "milestone_status"}))
    active = loans[loans["is_active"] & (loans["foreclosure_status"] != "NONE")][
        ["loan_id", "portfolio_id", "property_state", "foreclosure_status", "days_delinquent",
         "assigned_specialist_id", "assigned_attorney_vendor_id"]]
    return active.merge(current, how="left", on="loan_id").reset_index(drop=True)


# ---------------------------------------------------------------------------------------------
# dataset assembly
# ---------------------------------------------------------------------------------------------
def build_silver(bronze: dict[str, pd.DataFrame], settings=None) -> SilverDataset:
    """Build all silver tables from bronze frames (keys ``bronze_*``)."""
    followup_types = settings.business_rules.get("followup_event_types") if settings else None
    active_statuses = settings.business_rules.get("active_loan_statuses") if settings else None
    rules = standardize_milestone_rules(bronze["bronze_milestone_rules"])
    specialists = standardize_specialists(bronze["bronze_servicing_specialists"])
    parties = standardize_parties(bronze["bronze_attorneys_vendors"])
    loans = standardize_loans(bronze["bronze_loans"], specialists, parties, active_statuses)
    events = standardize_events(bronze["bronze_loan_events"], rules, followup_types)
    actions = standardize_actions(bronze["bronze_servicing_action_history"])
    decisions = standardize_decisions(bronze["bronze_reviewer_decisions"])
    return SilverDataset(
        loans=loans,
        loan_events=events,
        milestone_rules=rules,
        servicing_specialists=specialists,
        attorneys_vendors=parties,
        active_foreclosures=build_active_foreclosures(loans, events),
        servicing_action_history=actions,
        reviewer_decisions=decisions,
    )


def _stringify(df: pd.DataFrame) -> pd.DataFrame:
    """Convert typed frames back to source-like strings so they can be re-standardized idempotently."""
    out = pd.DataFrame(index=df.index)
    for col in df.columns:
        series = df[col]
        if pd.api.types.is_datetime64_any_dtype(series):
            out[col] = series.dt.strftime("%Y-%m-%dT%H:%M:%S").fillna("")
        elif pd.api.types.is_bool_dtype(series):
            out[col] = series.map(lambda v: "true" if v else "false")
        else:
            out[col] = series.map(lambda v: "" if v is None or (isinstance(v, float) and pd.isna(v))
                                  else (v.isoformat() if isinstance(v, date) else str(v)))
    return out


def apply_system_of_record_updates(silver: SilverDataset, sor_events: pd.DataFrame | None, cycle: int,
                                   settings=None) -> SilverDataset:
    """Overlay simulated System-of-Record events visible at ``cycle`` onto silver events (upsert by event_id)."""
    if sor_events is None or sor_events.empty:
        return silver
    visible = sor_events.copy()
    if "available_cycle" in visible.columns:
        visible = visible[pd.to_numeric(visible["available_cycle"], errors="coerce").fillna(0) <= cycle]
    if visible.empty:
        return silver
    followup_types = settings.business_rules.get("followup_event_types") if settings else None
    base_cols = ["event_id", "loan_id", "event_type", "milestone_type", "event_date", "followup_date",
                 "completed_date", "status", "event_note", "source", "created_at", "updated_at", "synthetic_data"]
    current = _stringify(silver.loan_events[base_cols])
    incoming = _stringify(visible[[c for c in base_cols if c in visible.columns]])
    merged = pd.concat([current, incoming], ignore_index=True)
    out = silver.copy()
    out.loan_events = standardize_events(merged, silver.milestone_rules, followup_types)
    out.active_foreclosures = build_active_foreclosures(out.loans, out.loan_events)
    return out


def overlay_operational(silver: SilverDataset, ops_actions: pd.DataFrame | None,
                        ops_decisions: pd.DataFrame | None) -> SilverDataset:
    """Union app-written actions/decisions onto source history (idempotent by key)."""
    out = silver
    if ops_actions is not None and not ops_actions.empty:
        out = out if out is not silver else silver.copy()
        cols = ["action_id", "loan_id", "recommendation_id", "action_type", "event_type", "milestone_type",
                "event_date", "followup_date", "status", "submitted_at", "verified_at", "failure_reason"]
        incoming = ops_actions[[c for c in cols if c in ops_actions.columns]].copy()
        incoming["synthetic_data"] = "true"
        base = _stringify(silver.servicing_action_history.drop(columns=["dq_issues"], errors="ignore"))
        out.servicing_action_history = standardize_actions(pd.concat([base, _stringify(incoming)], ignore_index=True))
    if ops_decisions is not None and not ops_decisions.empty:
        out = out if out is not silver else silver.copy()
        cols = ["decision_id", "recommendation_id", "loan_id", "reviewer_id", "decision", "original_action",
                "final_action", "original_followup_date", "final_followup_date", "original_note", "final_note",
                "reason", "decided_at"]
        incoming = ops_decisions[[c for c in cols if c in ops_decisions.columns]].copy()
        incoming["synthetic_data"] = "true"
        base = _stringify(silver.reviewer_decisions.drop(columns=["dq_issues"], errors="ignore"))
        out.reviewer_decisions = standardize_decisions(pd.concat([base, _stringify(incoming)], ignore_index=True))
    return out


# ====================================================================================================
# Gold table assembly from a portfolio evaluation and operational state
# ====================================================================================================

JSON_COLUMNS = ["raw_conditions", "secondary_conditions", "condition_rule_ids", "escalation_reasons",
                "allowed_actions", "removed_actions", "score_drivers", "prior_rejected_actions"]
HEALTH_ORDER = ["Healthy", "Watch", "Action Required", "Critical"]
PRIORITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}


def to_json(value) -> str:
    return json.dumps(value, default=str)


def encode_json_columns(df: pd.DataFrame, columns: list[str] | None = None) -> pd.DataFrame:
    out = df.copy()
    for col in columns or JSON_COLUMNS:
        if col in out.columns:
            out[col] = out[col].map(to_json)
    return out


def loan_state_frame(evaluation: PortfolioEvaluation) -> pd.DataFrame:
    return pd.DataFrame(list(evaluation.results.values()))


def portfolio_kpis(evaluation: PortfolioEvaluation, recommendations: list[dict] | None = None,
                   actions: list[dict] | None = None) -> dict:
    active = evaluation.active_results()
    conditions = Counter(r["primary_condition"] for r in active)
    raw = Counter(c["code"] for r in active for c in r["raw_conditions"])
    P = evaluation.processing_date.isoformat()
    recs = recommendations or []
    acts = actions or []
    return {
        "active_loans": len(active),
        "need_attention": sum(1 for r in active if r["needs_attention"]),
        "upcoming": raw.get("UPCOMING", 0),
        "due": raw.get("DUE", 0),
        "overdue": raw.get("OVERDUE", 0),
        "missing_followup": raw.get("MISSING_FOLLOWUP", 0),
        "critical": sum(1 for r in active if r["priority"] == "CRITICAL"),
        "data_exceptions": raw.get("DATA_EXCEPTION", 0),
        "duplicate_risk": raw.get("DUPLICATE_RISK", 0),
        "recommendations_awaiting_approval": sum(1 for r in recs if r.get("status") == "PENDING_REVIEW"),
        # ``actions`` are app-approved (operational) actions; their event_date is the business approval date.
        "approved_today": sum(1 for a in acts if str(a.get("event_date") or "")[:10] == P),
        "verification_failures": raw.get("VERIFICATION_FAILURE", 0),
        "pending_actions": raw.get("PENDING_ACTION", 0),
        "condition_counts": dict(conditions),
        "raw_condition_counts": dict(raw),
    }


def health_segments(evaluation: PortfolioEvaluation) -> list[dict]:
    active = evaluation.active_results()
    counts = Counter(r["health_segment"] for r in active)
    total = max(1, len(active))
    return [{"health_segment": s, "loan_count": counts.get(s, 0), "share_of_active": round(counts.get(s, 0) / total, 4)}
            for s in HEALTH_ORDER]


def briefing_facts(evaluation: PortfolioEvaluation, recommendations: list[dict] | None = None,
                   actions: list[dict] | None = None) -> list[dict]:
    """Deterministic facts: the only inputs to the portfolio briefing."""
    k = portfolio_kpis(evaluation, recommendations, actions)
    active = evaluation.active_results()
    attention = [r for r in active if r["needs_attention"]]
    facts = [("portfolio", "processing_date", evaluation.processing_date.isoformat())]
    for key in ("active_loans", "need_attention", "critical", "overdue", "due", "upcoming", "missing_followup",
                "data_exceptions", "duplicate_risk", "verification_failures", "pending_actions",
                "recommendations_awaiting_approval", "approved_today"):
        facts.append(("kpi", key, k[key]))
    for seg in health_segments(evaluation):
        facts.append(("health", seg["health_segment"], seg["loan_count"]))
    for prio, n in Counter(r["priority"] for r in active).items():
        facts.append(("priority", prio, n))
    for cond, n in Counter(r["primary_condition"] for r in attention).most_common(5):
        facts.append(("top_attention_condition", cond, n))
    for ms, n in Counter(r["current_milestone"] for r in attention if r["current_milestone"]).most_common(3):
        facts.append(("top_attention_milestone", ms, n))
    for pf, n in Counter(r["portfolio_id"] for r in attention).most_common(2):
        facts.append(("top_attention_portfolio", pf, n))
    for sp, n in Counter(r["specialist_name"] for r in attention if r["specialist_name"]).most_common(2):
        facts.append(("top_attention_specialist", sp, n))
    overdue = [r["days_overdue"] for r in active if any(c["code"] == "OVERDUE" for c in r["raw_conditions"])]
    if overdue:
        facts.append(("overdue", "overdue_30_plus", sum(1 for d in overdue if d >= 30)))
        facts.append(("overdue", "overdue_60_plus", sum(1 for d in overdue if d >= 60)))
        facts.append(("overdue", "max_days_overdue", max(overdue)))
    top = sorted(attention, key=lambda r: (-r["attention_score"], r["loan_id"]))[:3]
    for i, r in enumerate(top, 1):
        facts.append(("top_loan", f"rank_{i}", f"{r['loan_id']} {r['primary_condition']} score {r['attention_score']}"))
    return [{"fact_group": g, "fact_name": n, "fact_value": str(v),
             "processing_date": evaluation.processing_date.isoformat()} for g, n, v in facts]


def priority_queue_rows(evaluation: PortfolioEvaluation, recommendations: list[dict] | None = None,
                        review_status: dict[str, str] | None = None) -> list[dict]:
    latest_rec: dict[str, dict] = {}
    for rec in sorted(recommendations or [], key=lambda r: str(r.get("created_at"))):
        if rec.get("status") != "SUPERSEDED":
            latest_rec[rec["loan_id"]] = rec
    rows = []
    for r in evaluation.active_results():
        if not r["needs_attention"]:
            continue
        rec = latest_rec.get(r["loan_id"], {})
        rows.append({
            "priority": r["priority"],
            "loan_id": r["loan_id"],
            "borrower_display_name": r["borrower_display_name"],
            "primary_condition": r["primary_condition"],
            "secondary_conditions": r["secondary_conditions"],
            "escalation_state": r["escalation_state"],
            "severity": r["milestone_severity"],
            "current_milestone": r["current_milestone"],
            "effective_followup_date": r["effective_followup_date"],
            "days_overdue": r["days_overdue"],
            "attention_score": r["attention_score"],
            "score_drivers": r["score_drivers"],
            "top_drivers_text": r["top_drivers_text"],
            "recommended_action": rec.get("recommended_action") or r["default_action"],
            "recommendation_id": rec.get("recommendation_id"),
            "recommendation_source": rec.get("agent_mode"),
            "confidence": rec.get("confidence"),
            "specialist_name": r["specialist_name"],
            "review_status": (review_status or {}).get(r["loan_id"], "NOT_ANALYZED"),
            "why_prioritized": f"{r['primary_condition']}: " + "; ".join(
                c["detail"] for c in r["raw_conditions"] if c["code"] == r["primary_condition"]),
        })
    rows.sort(key=lambda x: (PRIORITY_ORDER[x["priority"]], -x["attention_score"], x["loan_id"]))
    for i, row in enumerate(rows, 1):
        row["queue_rank"] = i
    return rows


def verification_rows(evaluation: PortfolioEvaluation) -> list[dict]:
    P = evaluation.processing_date.isoformat()
    return [{**v, "evaluated_on": P} for v in evaluation.all_verifications()]


def build_gold_tables(evaluation: PortfolioEvaluation, recommendations: list[dict] | None = None,
                      actions: list[dict] | None = None, review_status: dict[str, str] | None = None) -> dict[str, pd.DataFrame]:
    from src import rules  # imported here: rules depends on this module

    state = loan_state_frame(evaluation)
    verif = pd.DataFrame(verification_rows(evaluation))
    if not verif.empty:
        verif["matched_event_ids"] = verif["matched_event_ids"].map(to_json)
        verif["differences"] = verif["differences"].map(to_json)
        for col in ("submitted_at", "action_event_date", "followup_date"):
            verif[col] = verif[col].astype(str)
    queue = pd.DataFrame(priority_queue_rows(evaluation, recommendations, review_status))
    if not queue.empty:
        queue = encode_json_columns(queue, ["secondary_conditions", "score_drivers"])
    return {
        "gold_loan_servicing_state": encode_json_columns(state),
        "gold_loan_milestone_state": pd.DataFrame(rules.milestone_state_rows(evaluation)),
        "gold_attention_candidates": encode_json_columns(state[state["needs_attention"] & state["is_active"]]),
        "gold_priority_queue": queue,
        "gold_portfolio_health": pd.DataFrame(health_segments(evaluation)).assign(
            processing_date=evaluation.processing_date.isoformat()),
        "gold_portfolio_briefing_facts": pd.DataFrame(briefing_facts(evaluation, recommendations, actions)),
        "gold_action_verification": verif,
        "gold_pending_actions": verif[verif["verification_status"] == "PENDING"] if not verif.empty else verif,
    }
