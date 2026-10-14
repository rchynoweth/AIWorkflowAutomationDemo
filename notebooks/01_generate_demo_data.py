# Databricks notebook source
# MAGIC %md
# MAGIC # Loan Servicing Intelligence — 01 · Generate synthetic demo data
# MAGIC
# MAGIC > **Synthetic demonstration data.** All loans, borrowers, rules, thresholds, and metrics are synthetic.
# MAGIC
# MAGIC Creates the schema and landing volume, then writes deterministic synthetic CSV exports (fixed seed) to `/Volumes/<catalog>/<schema>/landing/current` and an archive batch folder.
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

result = pipeline.generate_to_volume(spark, settings)
print(f"Batch {result['batch_id']} -> {result['path']}")
display(spark.createDataFrame([(k, v) for k, v in result["counts"].items()], "file string, rows long"))
dbutils.jobs.taskValues.set("batch_id", result["batch_id"])
