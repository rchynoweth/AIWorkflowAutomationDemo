# Databricks notebook source
# MAGIC %md
# MAGIC # Loan Servicing Intelligence — Deploy the Loan Servicing Agent
# MAGIC
# MAGIC > **Synthetic demonstration data.**
# MAGIC
# MAGIC Logs the agent (`agent_endpoint/loan_servicing_agent.py`, an MLflow **ResponsesAgent**) with its Unity Catalog
# MAGIC tool functions as declared resources, registers it in **Unity Catalog** as
# MAGIC `<catalog>.<schema>.loan_servicing_agent`, and deploys it with the **Mosaic AI Agent Framework** to a Model
# MAGIC Serving endpoint (`loan-servicing-agent`, scale-to-zero) with tracing and a review app.

# COMMAND ----------

# MAGIC %pip install -q -r ../requirements-pipeline.txt "mlflow>=3.1" databricks-agents "databricks-sdk>=0.50"

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

import os
import sys

dbutils.widgets.text("catalog", "main", "Catalog")
dbutils.widgets.text("schema", "loan_servicing_intelligence", "Schema")
dbutils.widgets.text("processing_date", "2026-10-12", "Processing date (demo)")

dbutils.widgets.text("warehouse_id", "", "SQL warehouse ID")
dbutils.widgets.text("llm_endpoint", "databricks-claude-sonnet-5-5", "LLM endpoint")
os.environ["LSI_CATALOG"] = dbutils.widgets.get("catalog")
os.environ["LSI_SCHEMA"] = dbutils.widgets.get("schema")
os.environ["LSI_PROCESSING_DATE"] = dbutils.widgets.get("processing_date")
os.environ["LSI_REPOSITORY_BACKEND"] = "databricks"

REPO_ROOT = os.path.abspath(os.path.join(os.getcwd(), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src import pipeline  # noqa: E402
from src.config import load_settings  # noqa: E402
from src.databricks import deploy_agent

settings = load_settings()
print(f"Repository: {REPO_ROOT}")
print(f"Target: {settings.catalog}.{settings.schema} | processing date {settings.processing_date}")

# COMMAND ----------


result = deploy_agent(
    agent_path=os.path.join(REPO_ROOT, "agent_endpoint", "loan_servicing_agent.py"),
    catalog=settings.catalog,
    schema=settings.schema,
    warehouse_id=dbutils.widgets.get("warehouse_id"),
    llm_endpoint=dbutils.widgets.get("llm_endpoint"),
)
print(result)
