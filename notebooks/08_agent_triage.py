# Databricks notebook source
# MAGIC %md
# MAGIC # Loan Servicing Intelligence — Agent triage
# MAGIC
# MAGIC > **Synthetic demonstration data.** All loans, borrowers, rules, thresholds, and metrics are synthetic.
# MAGIC
# MAGIC The Loan Servicing Agent (Claude via the Foundation Model API) investigates the highest-priority loans that do not yet have a current AI proposal, using the same approved tools as the app. Proposals are written to `ops_recommendations` with status PENDING_REVIEW: **nothing is executed without a specialist's approval.**
# MAGIC
# MAGIC Part of the recurring **lsi-servicing-monitor** workflow. Runs on **serverless** compute.

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

dbutils.widgets.text("triage_limit", "8", "Loans to triage")
dbutils.widgets.dropdown("agent_mode", "auto", ["auto", "llm", "deterministic"], "Agent mode")
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

limit = int(dbutils.widgets.get("triage_limit"))
agent_mode = dbutils.widgets.get("agent_mode")
result = pipeline.agent_triage(spark, settings, limit=limit, agent_mode=agent_mode)
print(f"Analyzed {result['analyzed']} loans in {result['seconds']}s")
display(spark.createDataFrame(result["results"]) if result["results"] else spark.createDataFrame([], "loan_id string"))
