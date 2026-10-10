# Databricks notebook source
# MAGIC %md
# MAGIC # Loan Servicing Intelligence — 07 · Reset demo
# MAGIC
# MAGIC > **Synthetic demonstration data.** All loans, borrowers, rules, thresholds, and metrics are synthetic.
# MAGIC
# MAGIC Clears operational state (recommendations, decisions, actions, verification, activity, simulated System-of-Record events), then rebuilds Silver and Gold, which regenerates baseline recommendations.
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
from src.config.settings import load_settings  # noqa: E402

settings = load_settings()
print(f"Repository: {REPO_ROOT}")
print(f"Target: {settings.catalog}.{settings.schema} | processing date {settings.processing_date}")

# COMMAND ----------

pipeline.reset_demo(spark, settings)
print("Operational state cleared")
print(pipeline.build_silver_tables(spark, settings))
print(pipeline.build_gold(spark, settings, sql_dir=os.path.join(REPO_ROOT, "sql")))
