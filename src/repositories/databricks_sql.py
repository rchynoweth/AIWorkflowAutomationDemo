"""Databricks SQL repository: reads silver tables and reads/writes operational Delta tables through a
serverless SQL warehouse using the Statement Execution API (databricks-sdk).

Writes are queued to a background thread so the UI stays responsive; ``flush()`` waits for them.
"""
from __future__ import annotations

import logging
import queue
import threading
import time

import pandas as pd

from src.data_generation.generator import (
    ACTION_COLUMNS,
    DECISION_COLUMNS,
    EVENT_COLUMNS,
    LOAN_COLUMNS,
)
from src.data_generation.catalog import MILESTONE_COLUMNS
from src.repositories.base import OPS_TABLES, ServicingRepository, decode_record, encode_record
from src.transformations.silver import SilverDataset, build_silver

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
