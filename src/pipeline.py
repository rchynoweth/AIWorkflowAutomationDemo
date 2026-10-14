"""Databricks pipeline steps (called by notebooks). Requires an active SparkSession.

Bronze uses Spark's CSV reader on the Unity Catalog volume; Silver/Gold use the shared pandas logic
(ADR-003) and persist Delta tables with Spark.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from src.medallion import new_batch_id, SOURCE_FILES

TABLE_COMMENT = "Loan Servicing Intelligence - SYNTHETIC DEMONSTRATION DATA"


def fq(settings, table: str) -> str:
    return f"`{settings.catalog}`.`{settings.schema}`.`{table}`"


def to_spark(spark, pdf: pd.DataFrame):
    """Convert a pandas frame (python dates, JSON-able objects, nullable ints) into a Spark DataFrame."""
    from pyspark.sql import functions as F

    pdf = pdf.copy()
    date_cols = []
    for col in pdf.columns:
        series = pdf[col]
        if series.dtype == object:
            sample = [v for v in series.head(500) if v is not None and not (isinstance(v, float) and pd.isna(v))]
            if sample and all(isinstance(v, date) and not isinstance(v, datetime) for v in sample):
                pdf[col] = series.map(lambda v: v.isoformat() if isinstance(v, date) else None).astype("string")
                date_cols.append(col)
            elif sample and all(isinstance(v, bool) for v in sample):
                pdf[col] = series.astype("boolean")
            else:
                pdf[col] = series.map(lambda v: None if v is None or (isinstance(v, float) and pd.isna(v)) else (
                    json.dumps(v, default=str) if isinstance(v, (list, dict)) else str(v))).astype("string")
    sdf = spark.createDataFrame(pdf)
    for col in date_cols:
        sdf = sdf.withColumn(col, F.to_date(col))
    return sdf


def write_table(spark, settings, name: str, pdf: pd.DataFrame) -> int:
    sdf = to_spark(spark, pdf)
    sdf.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(fq(settings, name))
    spark.sql(f"COMMENT ON TABLE {fq(settings, name)} IS '{TABLE_COMMENT}'")
    return len(pdf)


def run_sql_file(spark, settings, path: Path) -> int:
    text = path.read_text(encoding="utf-8").replace("${catalog}", settings.catalog).replace("${schema}", settings.schema)
    # Statements are separated by a semicolon at end of line (string literals must not end a line with ';').
    body = "\n".join(line for line in text.splitlines() if not line.strip().startswith("--"))
    statements = [s.strip() for s in re.split(r";\s*(?:\n|$)", body) if s.strip()]
    for statement in statements:
        spark.sql(statement)
    return len(statements)
