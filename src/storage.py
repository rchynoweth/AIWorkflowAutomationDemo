"""Storage: source data and operational state (local files, Databricks SQL warehouse, or Spark)."""
from __future__ import annotations

import json
import logging
import queue
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from src.medallion import build_silver, ingest_directory, SilverDataset, SOURCE_FILES
from src.synthetic_data import ACTION_COLUMNS, DECISION_COLUMNS, EVENT_COLUMNS, LOAN_COLUMNS, MILESTONE_COLUMNS


# ====================================================================================================
# Repository interface for source data and operational state
# ====================================================================================================

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


# ====================================================================================================
# In-memory operational state (write-through to the repository)
# ====================================================================================================

@dataclass
class OperationalState:
    recommendations: dict[str, dict] = field(default_factory=dict)
    decisions: dict[str, dict] = field(default_factory=dict)
    actions: dict[str, dict] = field(default_factory=dict)
    verification_results: dict[str, dict] = field(default_factory=dict)
    activity: list[dict] = field(default_factory=list)
    sor_events: list[dict] = field(default_factory=list)
    runtime: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_tables(cls, tables: dict[str, list[dict]]) -> "OperationalState":
        state = cls()
        state.recommendations = {r["recommendation_id"]: r for r in tables.get("ops_recommendations", [])}
        state.decisions = {r["decision_id"]: r for r in tables.get("ops_reviewer_decisions", [])}
        state.actions = {r["action_id"]: r for r in tables.get("ops_actions", [])}
        state.verification_results = {r["verification_id"]: r for r in tables.get("ops_verification_results", [])}
        state.activity = sorted(tables.get("ops_agent_activity", []), key=lambda r: str(r.get("created_at")))
        state.sor_events = tables.get("sor_servicing_events", [])
        state.runtime = {r["state_key"]: r["state_value"] for r in tables.get("ops_runtime_state", [])}
        return state

    @property
    def refresh_cycle(self) -> int:
        return int(self.runtime.get("refresh_cycle", "0") or 0)

    def recommendations_for(self, loan_id: str) -> list[dict]:
        recs = [r for r in self.recommendations.values() if r["loan_id"] == loan_id]
        return sorted(recs, key=lambda r: str(r.get("created_at")), reverse=True)

    def actions_frame(self) -> pd.DataFrame | None:
        return pd.DataFrame(list(self.actions.values())) if self.actions else None

    def decisions_frame(self) -> pd.DataFrame | None:
        return pd.DataFrame(list(self.decisions.values())) if self.decisions else None

    def sor_frame(self) -> pd.DataFrame | None:
        return pd.DataFrame(self.sor_events) if self.sor_events else None


# ====================================================================================================
# Local file repository: source CSVs -> bronze -> silver in memory; ops state as JSONL files
# ====================================================================================================

class LocalRepository(ServicingRepository):
    backend = "local"

    def __init__(self, settings, source_dir: str | Path | None = None, state_dir: str | Path | None = None):
        self.settings = settings
        landing = settings.path("landing_dir")
        has_landing = all((landing / f).exists() for f in SOURCE_FILES.values())
        self.source_dir = Path(source_dir) if source_dir else (landing if has_landing else settings.path("generated_dir"))
        self.state_dir = Path(state_dir) if state_dir else settings.path("processed_dir") / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._cache: dict[str, dict[tuple, dict]] | None = None

    def load_source_silver(self) -> SilverDataset:
        return build_silver(ingest_directory(self.source_dir), self.settings)

    def _path(self, table: str) -> Path:
        return self.state_dir / f"{table}.jsonl"

    def _load_cache(self) -> dict[str, dict[tuple, dict]]:
        if self._cache is None:
            self._cache = {}
            for table, (keys, _) in OPS_TABLES.items():
                rows: dict[tuple, dict] = {}
                path = self._path(table)
                if path.exists():
                    for line in path.read_text(encoding="utf-8").splitlines():
                        if line.strip():
                            rec = json.loads(line)
                            rows[tuple(rec.get(k) for k in keys)] = rec
                self._cache[table] = rows
        return self._cache

    def load_ops(self) -> dict[str, list[dict]]:
        with self._lock:
            cache = self._load_cache()
            return {t: [decode_record(r) for r in rows.values()] for t, rows in cache.items()}

    def upsert(self, table: str, records: list[dict]) -> None:
        if not records:
            return
        keys, _ = OPS_TABLES[table]
        with self._lock:
            cache = self._load_cache()
            for record in records:
                enc = encode_record(table, record)
                cache[table][tuple(enc.get(k) for k in keys)] = enc
            with open(self._path(table), "w", encoding="utf-8") as fh:
                for rec in cache[table].values():
                    fh.write(json.dumps(rec) + "\n")

    def reset_ops(self) -> None:
        with self._lock:
            for table in OPS_TABLES:
                path = self._path(table)
                if path.exists():
                    path.unlink()
            self._cache = None


# ====================================================================================================
# Databricks SQL repository: reads silver tables and reads/writes operational Delta tables through a
# ====================================================================================================

log = logging.getLogger(__name__)

SILVER_SOURCE_COLUMNS = {
    "bronze_loans": ("silver_loans", LOAN_COLUMNS),
    "bronze_loan_events": ("silver_loan_events", EVENT_COLUMNS),
    "bronze_milestone_rules": ("silver_milestone_rules", MILESTONE_COLUMNS + ["synthetic_data"]),
    "bronze_servicing_specialists": ("silver_servicing_specialists",
                                     ["specialist_id", "display_name", "team", "active", "synthetic_data"]),
    "bronze_attorneys_vendors": ("silver_attorneys_vendors",
                                 ["party_id", "display_name", "party_type", "state", "active", "synthetic_data"]),
    "bronze_servicing_action_history": ("silver_servicing_action_history", ACTION_COLUMNS),
    "bronze_reviewer_decisions": ("silver_reviewer_decisions", DECISION_COLUMNS),
}


def sql_literal(value) -> str:
    if value is None:
        return "NULL"
    text = str(value).replace("\\", "\\\\").replace("'", "\\'")
    return f"'{text}'"


class DatabricksSqlRepository(ServicingRepository):
    backend = "databricks"

    def __init__(self, settings, warehouse_id: str | None = None, catalog: str | None = None,
                 schema: str | None = None, client=None, async_writes: bool = True):
        if client is None:
            from databricks.sdk import WorkspaceClient
            client = WorkspaceClient()
        self.client = client
        self.settings = settings
        self.warehouse_id = warehouse_id or settings.warehouse_id
        if not self.warehouse_id:
            raise ValueError("DATABRICKS_WAREHOUSE_ID is required for the databricks backend")
        self.catalog = catalog or settings.catalog
        self.schema = schema or settings.schema
        self.async_writes = async_writes
        self.write_errors: list[str] = []
        self._queue: queue.Queue = queue.Queue()
        self._tables_ready = False
        if async_writes:
            threading.Thread(target=self._writer, daemon=True, name="lsi-sql-writer").start()

    # ---- execution ----------------------------------------------------------------
    def fq(self, table: str) -> str:
        return f"`{self.catalog}`.`{self.schema}`.`{table}`"

    def execute(self, statement: str) -> list[dict]:
        from databricks.sdk.service.sql import Disposition, Format, StatementState

        api = self.client.statement_execution
        resp = api.execute_statement(statement=statement, warehouse_id=self.warehouse_id, wait_timeout="50s",
                                     format=Format.JSON_ARRAY, disposition=Disposition.INLINE)
        deadline = time.time() + 600
        while resp.status and resp.status.state in (StatementState.PENDING, StatementState.RUNNING):
            if time.time() > deadline:
                raise TimeoutError("SQL statement timed out")
            time.sleep(1.0)
            resp = api.get_statement(resp.statement_id)
        if not resp.status or resp.status.state != StatementState.SUCCEEDED:
            message = resp.status.error.message if resp.status and resp.status.error else str(resp.status)
            raise RuntimeError(f"SQL failed: {message}")
        if not resp.manifest or not resp.manifest.schema or not resp.manifest.schema.columns:
            return []
        columns = [c.name for c in resp.manifest.schema.columns]
        rows = list((resp.result.data_array if resp.result else None) or [])
        next_chunk = resp.result.next_chunk_index if resp.result else None
        while next_chunk is not None:
            chunk = api.get_statement_result_chunk_n(resp.statement_id, next_chunk)
            rows.extend(chunk.data_array or [])
            next_chunk = chunk.next_chunk_index
        return [dict(zip(columns, row)) for row in rows]

    def _writer(self) -> None:
        while True:
            statement = self._queue.get()
            try:
                self.execute(statement)
            except Exception as exc:  # noqa: BLE001 - surfaced via write_errors and logs
                log.exception("Background SQL write failed")
                self.write_errors.append(str(exc)[:500])
            finally:
                self._queue.task_done()

    def _submit(self, statement: str) -> None:
        if self.async_writes:
            self._queue.put(statement)
        else:
            self.execute(statement)

    def flush(self) -> None:
        if self.async_writes:
            self._queue.join()

    # ---- schema -------------------------------------------------------------------
    def ensure_ops_tables(self) -> None:
        if self._tables_ready:
            return
        for table, (_, columns) in OPS_TABLES.items():
            cols = ", ".join(f"`{c}` STRING" for c in columns)
            self.execute(f"CREATE TABLE IF NOT EXISTS {self.fq(table)} ({cols}) USING DELTA "
                         "COMMENT 'Loan Servicing Intelligence operational state (synthetic demonstration)'")
        self._tables_ready = True

    # ---- reads --------------------------------------------------------------------
    def load_source_silver(self) -> SilverDataset:
        frames = {}
        for bronze_name, (silver_table, columns) in SILVER_SOURCE_COLUMNS.items():
            select = ", ".join(f"CAST(`{c}` AS STRING) AS `{c}`" for c in columns)
            rows = self.execute(f"SELECT {select} FROM {self.fq(silver_table)}")
            frames[bronze_name] = pd.DataFrame(rows, columns=columns).fillna("")
        return build_silver(frames, self.settings)

    def load_ops(self) -> dict[str, list[dict]]:
        self.ensure_ops_tables()
        return {t: [decode_record(r) for r in self.execute(f"SELECT * FROM {self.fq(t)}")] for t in OPS_TABLES}

    # ---- writes -------------------------------------------------------------------
    def upsert(self, table: str, records: list[dict]) -> None:
        if not records:
            return
        self.ensure_ops_tables()
        keys, columns = OPS_TABLES[table]
        for start in range(0, len(records), 50):
            batch = [encode_record(table, r) for r in records[start:start + 50]]
            values = ", ".join("(" + ", ".join(sql_literal(r[c]) for c in columns) + ")" for r in batch)
            col_list = ", ".join(f"`{c}`" for c in columns)
            on = " AND ".join(f"t.`{k}` <=> s.`{k}`" for k in keys)
            sets = ", ".join(f"t.`{c}` = s.`{c}`" for c in columns if c not in keys)
            self._submit(
                f"MERGE INTO {self.fq(table)} t USING (SELECT * FROM VALUES {values} AS v({col_list})) s ON {on} "
                f"WHEN MATCHED THEN UPDATE SET {sets} WHEN NOT MATCHED THEN INSERT ({col_list}) VALUES "
                f"({', '.join(f's.`{c}`' for c in columns)})")

    def reset_ops(self) -> None:
        self.ensure_ops_tables()
        self.flush()
        for table in OPS_TABLES:
            self.execute(f"DELETE FROM {self.fq(table)}")


# ====================================================================================================
# Spark repository used by Databricks notebooks (same interface as the SQL-warehouse repository)
# ====================================================================================================

class SparkRepository(ServicingRepository):
    backend = "databricks"

    def __init__(self, spark, settings, catalog: str | None = None, schema: str | None = None):
        self.spark = spark
        self.settings = settings
        self.catalog = catalog or settings.catalog
        self.schema = schema or settings.schema
        self._ready = False

    def fq(self, table: str) -> str:
        return f"`{self.catalog}`.`{self.schema}`.`{table}`"

    def ensure_ops_tables(self) -> None:
        if self._ready:
            return
        for table, (_, columns) in OPS_TABLES.items():
            cols = ", ".join(f"`{c}` STRING" for c in columns)
            self.spark.sql(f"CREATE TABLE IF NOT EXISTS {self.fq(table)} ({cols}) USING DELTA "
                           "COMMENT 'Loan Servicing Intelligence operational state (synthetic demonstration)'")
        self._ready = True

    def read_strings(self, table: str, columns: list[str]) -> pd.DataFrame:
        select = ", ".join(f"CAST(`{c}` AS STRING) AS `{c}`" for c in columns)
        return self.spark.sql(f"SELECT {select} FROM {self.fq(table)}").toPandas().fillna("")

    def load_source_silver(self) -> SilverDataset:
        frames = {bronze: self.read_strings(silver, cols) for bronze, (silver, cols) in SILVER_SOURCE_COLUMNS.items()}
        return build_silver(frames, self.settings)

    def load_ops(self) -> dict[str, list[dict]]:
        self.ensure_ops_tables()
        out = {}
        for table in OPS_TABLES:
            pdf = self.spark.table(self.fq(table)).toPandas()
            out[table] = [decode_record({k: (None if pd.isna(v) else v) for k, v in row.items()})
                          for row in pdf.to_dict("records")]
        return out

    def upsert(self, table: str, records: list[dict]) -> None:
        if not records:
            return
        self.ensure_ops_tables()
        keys, columns = OPS_TABLES[table]
        pdf = pd.DataFrame([encode_record(table, r) for r in records], columns=columns).astype("string")
        view = f"lsi_upsert_{table}"
        self.spark.createDataFrame(pdf).createOrReplaceTempView(view)
        on = " AND ".join(f"t.`{k}` <=> s.`{k}`" for k in keys)
        self.spark.sql(f"MERGE INTO {self.fq(table)} t USING {view} s ON {on} "
                       "WHEN MATCHED THEN UPDATE SET * WHEN NOT MATCHED THEN INSERT *")

    def reset_ops(self) -> None:
        self.ensure_ops_tables()
        for table in OPS_TABLES:
            self.spark.sql(f"DELETE FROM {self.fq(table)}")


# ====================================================================================================
# Repository selection
# ====================================================================================================

def create_repository(settings, backend: str | None = None) -> ServicingRepository:
    """Local files by default; Delta tables through a SQL warehouse when backend is 'databricks'."""
    backend = (backend or settings.backend or "local").lower()
    if backend == "databricks":
        return DatabricksSqlRepository(settings)
    return LocalRepository(settings)
