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

from src.ingestion.bronze import SOURCE_FILES, new_batch_id

TABLE_COMMENT = "Loan Servicing Intelligence - SYNTHETIC DEMONSTRATION DATA"


def fq(settings, table: str) -> str:
    return f"`{settings.catalog}`.`{settings.schema}`.`{table}`"


def volume_path(settings) -> str:
    vol = settings.application["databricks"]["landing_volume"]
    return f"/Volumes/{settings.catalog}/{settings.schema}/{vol}"


def ensure_schema(spark, settings) -> None:
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS `{settings.catalog}`.`{settings.schema}` COMMENT '{TABLE_COMMENT}'")
    vol = settings.application["databricks"]["landing_volume"]
    spark.sql(f"CREATE VOLUME IF NOT EXISTS `{settings.catalog}`.`{settings.schema}`.`{vol}` COMMENT '{TABLE_COMMENT}'")


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


# ---- 01 generate -------------------------------------------------------------------------
def generate_to_volume(spark, settings) -> dict:
    from src.data_generation.generator import generate_dataset

    ensure_schema(spark, settings)
    dataset = generate_dataset(seed=settings.seed, processing_date=settings.processing_date,
                               loan_count=settings.loan_count)
    base = Path(volume_path(settings))
    batch = new_batch_id()
    counts = {}
    for target in (base / "current", base / "archive" / batch):
        target.mkdir(parents=True, exist_ok=True)
        for name, frame in dataset.tables().items():
            frame.to_csv(target / f"{name}.csv", index=False)
            counts[name] = len(frame)
    return {"batch_id": batch, "path": str(base / "current"), "counts": counts}


# ---- 02 bronze ---------------------------------------------------------------------------
def ingest_bronze(spark, settings, source_dir: str | None = None, batch_id: str | None = None) -> dict:
    from pyspark.sql import Window
    from pyspark.sql import functions as F

    source_dir = source_dir or f"{volume_path(settings)}/current"
    batch_id = batch_id or new_batch_id()
    counts = {}
    for table, filename in SOURCE_FILES.items():
        raw = (spark.read.option("header", True).option("inferSchema", False).option("multiLine", True)
               .option("escape", '"').csv(f"{source_dir}/{filename}"))
        cols = raw.columns
        raw = raw.select([F.coalesce(F.col(c), F.lit("")).alias(c) for c in cols])
        bronze = (raw.withColumn("source_file", F.col("_metadata.file_path"))
                  .withColumn("ingested_at", F.current_timestamp())
                  .withColumn("batch_id", F.lit(batch_id))
                  .withColumn("record_hash", F.sha2(F.concat_ws("|", *[F.col(c) for c in cols]), 256))
                  .withColumn("_mono", F.monotonically_increasing_id()))
        bronze = bronze.withColumn("source_row_number", F.row_number().over(Window.orderBy("_mono"))).drop("_mono")
        bronze.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(fq(settings, table))
        spark.sql(f"COMMENT ON TABLE {fq(settings, table)} IS '{TABLE_COMMENT}'")
        counts[table] = bronze.count()
    return {"batch_id": batch_id, "counts": counts}


# ---- 03 silver ---------------------------------------------------------------------------
def build_silver_tables(spark, settings) -> dict:
    from src.repositories.spark_repo import SparkRepository
    from src.services.state import OperationalState
    from src.transformations.silver import apply_system_of_record_updates, build_silver, overlay_operational

    bronze = {t: spark.table(fq(settings, t)).toPandas().fillna("") for t in SOURCE_FILES}
    silver = build_silver(bronze, settings)
    repo = SparkRepository(spark, settings)
    ops = OperationalState.from_tables(repo.load_ops())
    silver = apply_system_of_record_updates(silver, ops.sor_frame(), ops.refresh_cycle, settings)
    silver = overlay_operational(silver, ops.actions_frame(), ops.decisions_frame())
    counts = {}
    for name, frame in silver.tables().items():
        counts[name] = write_table(spark, settings, name, frame)
    return counts


# ---- 04 gold -----------------------------------------------------------------------------
def build_gold(spark, settings, sql_dir: str | None = None) -> dict:
    from src.repositories.spark_repo import SparkRepository
    from src.services.servicing_service import LoanServicingService
    from src.transformations import gold

    service = LoanServicingService(settings, SparkRepository(spark, settings), agent_mode="deterministic").load()
    tables = gold.build_gold_tables(service.evaluation, list(service.ops.recommendations.values()),
                                    list(service.ops.actions.values()), service.review_status_map())
    counts = {name: write_table(spark, settings, name, frame) for name, frame in tables.items() if not frame.empty}
    if sql_dir:
        run_sql_file(spark, settings, Path(sql_dir) / "portfolio_views.sql")
        run_sql_file(spark, settings, Path(sql_dir) / "monitoring_views.sql")
    counts["ops_recommendations"] = len(service.ops.recommendations)
    return counts


def run_sql_file(spark, settings, path: Path) -> int:
    text = path.read_text(encoding="utf-8").replace("${catalog}", settings.catalog).replace("${schema}", settings.schema)
    # Statements are separated by a semicolon at end of line (string literals must not end a line with ';').
    body = "\n".join(line for line in text.splitlines() if not line.strip().startswith("--"))
    statements = [s.strip() for s in re.split(r";\s*(?:\n|$)", body) if s.strip()]
    for statement in statements:
        spark.sql(statement)
    return len(statements)


# ---- 06 evaluation -----------------------------------------------------------------------
def run_evaluation(spark, settings, agent_mode: str = "deterministic", sql_dir: str | None = None) -> dict:
    from src.evaluation.evaluator import evaluation_rows
    from src.repositories.spark_repo import SparkRepository
    from src.services.servicing_service import LoanServicingService

    service = LoanServicingService(settings, SparkRepository(spark, settings), agent_mode=agent_mode).load()
    service.run_agent_evaluation(agent_mode)
    summary = service.evaluation_summary()
    rows = evaluation_rows({"rows": summary["scenarios"]}, {"rows": summary["agent_rows"]},
                           settings.processing_date.isoformat())
    sdf = to_spark(spark, pd.DataFrame(rows))
    sdf.write.mode("append").option("mergeSchema", "true").saveAsTable(fq(settings, "gold_agent_evaluation"))
    if sql_dir:
        run_sql_file(spark, settings, Path(sql_dir) / "evaluation_views.sql")
    return summary


# ---- 07 reset ----------------------------------------------------------------------------
def reset_demo(spark, settings) -> None:
    from src.repositories.spark_repo import SparkRepository

    SparkRepository(spark, settings).reset_ops()


# ---- servicing monitor (recurring backend workflow) ------------------------------------------
def _service(spark, settings, agent_mode: str = "deterministic"):
    from src.repositories.spark_repo import SparkRepository
    from src.services.servicing_service import LoanServicingService

    return LoanServicingService(settings, SparkRepository(spark, settings), agent_mode=agent_mode).load()


def refresh_and_verify(spark, settings) -> dict:
    """Advance the refresh cycle: apply System-of-Record updates and verify submitted actions."""
    result = _service(spark, settings).refresh()
    return {k: v for k, v in result.items() if k != "results"}


def agent_triage(spark, settings, limit: int = 10, agent_mode: str = "auto", max_workers: int = 4) -> dict:
    """Agent investigates the highest-priority loans without a current LLM proposal; proposals await review."""
    service = _service(spark, settings, agent_mode=agent_mode)
    return service.triage(limit=limit, agent_mode=agent_mode, max_workers=max_workers, actor="workflow")


AI_LOAN_PROMPT = (
    "You summarize SYNTHETIC loan-servicing data for a servicing specialist. In one sentence of at most 30 words, "
    "state why this loan needs attention and what to look at first. Use only these facts and do not give legal "
    "or financial advice. Facts: "
)
AI_BRIEFING_PROMPT = (
    "Write a 3-sentence morning briefing for servicing managers from these SYNTHETIC portfolio facts. Use only "
    "numbers present in the facts. Facts (JSON): "
)


def ai_insights(spark, settings, endpoint: str | None = None, limit: int = 25) -> dict:
    """Databricks AI Functions (ai_query) over Gold tables: per-loan summaries and a portfolio briefing."""
    endpoint = endpoint or settings.agent.get("ai_functions_endpoint") or settings.agent["model_endpoint"]
    t = lambda name: fq(settings, name)  # noqa: E731
    spark.sql(f"""
        CREATE OR REPLACE TABLE {t('gold_ai_loan_insights')}
        COMMENT 'AI Functions (ai_query) loan summaries - SYNTHETIC DEMONSTRATION DATA' AS
        SELECT loan_id, priority, primary_condition, CAST(attention_score AS INT) AS attention_score,
               ai_query('{endpoint}', CONCAT('{AI_LOAN_PROMPT}', why_prioritized, ' | Score drivers: ',
                        top_drivers_text, ' | Milestone: ', COALESCE(current_milestone, 'none'))) AS ai_summary,
               '{endpoint}' AS model_endpoint, current_timestamp() AS generated_at
        FROM {t('gold_priority_queue')}
        WHERE priority IN ('CRITICAL', 'HIGH')
        ORDER BY CAST(queue_rank AS INT)
        LIMIT {int(limit)}
    """)
    spark.sql(f"""
        CREATE OR REPLACE TABLE {t('gold_ai_portfolio_briefing')}
        COMMENT 'AI Functions (ai_query) portfolio briefing - SYNTHETIC DEMONSTRATION DATA' AS
        SELECT ai_query('{endpoint}', CONCAT('{AI_BRIEFING_PROMPT}', facts_json)) AS briefing,
               '{endpoint}' AS model_endpoint, current_timestamp() AS generated_at
        FROM (SELECT to_json(collect_list(named_struct('group', fact_group, 'name', fact_name,
                                                       'value', fact_value))) AS facts_json
              FROM {t('gold_portfolio_briefing_facts')})
    """)
    return {"loan_insights": spark.table(t("gold_ai_loan_insights")).count(), "endpoint": endpoint}
