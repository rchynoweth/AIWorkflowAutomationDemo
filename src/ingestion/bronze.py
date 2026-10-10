"""Bronze ingestion: preserve source values as strings and add lineage columns.

The pandas implementation is used locally and in tests; ``notebooks/02_ingest_bronze.py`` applies the same
contract with Spark's CSV reader (all columns as strings) on the Unity Catalog volume.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

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
