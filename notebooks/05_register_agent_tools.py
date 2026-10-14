# Databricks notebook source
# MAGIC %md
# MAGIC # Loan Servicing Intelligence — 05 · Register agent tools as Unity Catalog functions
# MAGIC
# MAGIC > **Synthetic demonstration data.** All loans, borrowers, rules, thresholds, and metrics are synthetic.
# MAGIC
# MAGIC Registers read-only, structured agent tools as Unity Catalog SQL table functions over Gold tables (`lsi_*`). The Python implementations in `src/tools` remain the reference used by the app and tests.
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
from src.tools import uc_function_statements

settings = load_settings()
print(f"Repository: {REPO_ROOT}")
print(f"Target: {settings.catalog}.{settings.schema} | processing date {settings.processing_date}")

# COMMAND ----------


for name, statement in uc_function_statements(settings.catalog, settings.schema):
    spark.sql(statement)
    print(f"Registered {settings.catalog}.{settings.schema}.{name}")

# COMMAND ----------

display(spark.sql(f"SELECT * FROM `{settings.catalog}`.`{settings.schema}`.lsi_get_loan_context('LSI-SYN-000005')"))

# COMMAND ----------

display(spark.sql(f"SELECT * FROM `{settings.catalog}`.`{settings.schema}`.lsi_priority_queue(10)"))
