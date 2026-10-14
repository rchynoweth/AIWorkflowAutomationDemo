# Databricks notebook source
# MAGIC %md
# MAGIC # Loan Servicing Intelligence — 03 · Build Silver
# MAGIC
# MAGIC > **Synthetic demonstration data.** All loans, borrowers, rules, thresholds, and metrics are synthetic.
# MAGIC
# MAGIC Typing, validation, deduplication, normalization, joins, event ordering, milestone sequencing, active filtering, and data-quality flags via the shared `src/medallion.py`. Applies simulated System-of-Record events (`sor_servicing_events`) visible at the current refresh cycle.
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

counts = pipeline.build_silver_tables(spark, settings)
display(spark.createDataFrame([(k, v) for k, v in counts.items()], "table string, rows long"))

# COMMAND ----------

display(spark.sql(f"SELECT loan_id, event_id, dq_issues FROM {pipeline.fq(settings, 'silver_loan_events')} WHERE dq_issues <> '' LIMIT 20"))
