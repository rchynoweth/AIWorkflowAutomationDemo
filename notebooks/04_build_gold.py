# Databricks notebook source
# MAGIC %md
# MAGIC # Loan Servicing Intelligence — 04 · Build Gold
# MAGIC
# MAGIC > **Synthetic demonstration data.** All loans, borrowers, rules, thresholds, and metrics are synthetic.
# MAGIC
# MAGIC Runs the deterministic rules engine (`src/rules.py`) over every loan: current milestone, follow-up status, conditions, escalation, attention score, allowed actions, and verification. Writes the `gold_*` tables the AI steps (06, 07) and the app read.
# MAGIC
# MAGIC Runs on **serverless** compute. Core logic lives in `src/`; this notebook only orchestrates.

# COMMAND ----------

# MAGIC %pip install -q -r ../requirements-pipeline.txt

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

import os
import sys

dbutils.widgets.text("catalog", "main", "Catalog")
dbutils.widgets.text("schema", "loan_servicing_intelligence", "Schema")
dbutils.widgets.text("processing_date", "2026-10-12", "Processing date (demo)")

os.environ["LSI_CATALOG"] = dbutils.widgets.get("catalog")
os.environ["LSI_SCHEMA"] = dbutils.widgets.get("schema")
os.environ["LSI_PROCESSING_DATE"] = dbutils.widgets.get("processing_date")
os.environ["LSI_REPOSITORY_BACKEND"] = "databricks"

REPO_ROOT = os.path.abspath(os.path.join(os.getcwd(), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src import pipeline  # noqa: E402
from src.config import load_settings  # noqa: E402

settings = load_settings()
print(f"Repository: {REPO_ROOT}")
print(f"Target: {settings.catalog}.{settings.schema} | processing date {settings.processing_date}")

# COMMAND ----------

counts = pipeline.build_gold(spark, settings, sql_dir=os.path.join(REPO_ROOT, "sql"))
display(spark.createDataFrame([(k, int(v)) for k, v in counts.items()], "table string, rows long"))

# COMMAND ----------

display(spark.sql(f"SELECT health_segment, loan_count, share_of_active FROM {pipeline.fq(settings, 'gold_portfolio_health')}"))

# COMMAND ----------

display(spark.sql(f"SELECT queue_rank, priority, loan_id, primary_condition, attention_score, top_drivers_text, recommended_action FROM {pipeline.fq(settings, 'gold_priority_queue')} ORDER BY queue_rank LIMIT 25"))
