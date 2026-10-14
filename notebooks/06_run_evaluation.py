# Databricks notebook source
# MAGIC %md
# MAGIC # Loan Servicing Intelligence — 06 · Run evaluation
# MAGIC
# MAGIC > **Synthetic demonstration data.** All loans, borrowers, rules, thresholds, and metrics are synthetic.
# MAGIC
# MAGIC Evaluates deterministic rules and the agent separately against the scenario manifest, appends row-level results to `gold_agent_evaluation`, and logs aggregate synthetic metrics to MLflow when available.
# MAGIC
# MAGIC Runs on **serverless** compute. Core logic lives in `src/`; this notebook only orchestrates.

# COMMAND ----------

# MAGIC %pip install -q -r ../requirements-pipeline.txt mlflow-skinny

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

import os
import sys

dbutils.widgets.text("catalog", "main", "Catalog")
dbutils.widgets.text("schema", "loan_servicing_intelligence", "Schema")
dbutils.widgets.text("processing_date", "2026-10-12", "Processing date (demo)")
dbutils.widgets.dropdown("agent_mode", "deterministic", ["deterministic", "llm", "auto"], "Agent mode")

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

agent_mode = dbutils.widgets.get("agent_mode")
summary = pipeline.run_evaluation(spark, settings, agent_mode, sql_dir=os.path.join(REPO_ROOT, "sql"))
print("Rule metrics:", summary["rule_metrics"])
print("Agent metrics:", summary["agent_metrics"])

# COMMAND ----------

try:
    import mlflow

    user = spark.sql("SELECT current_user()").first()[0]
    mlflow.set_experiment(f"/Users/{user}/loan-servicing-intelligence-evaluation")
    with mlflow.start_run(run_name=f"evaluation-{agent_mode}"):
        mlflow.set_tags({"synthetic_data": "true", "agent_mode": agent_mode, **settings.versions()})
        mlflow.log_metrics({f"rule_{k}": v for k, v in summary["rule_metrics"].items() if isinstance(v, (int, float))})
        mlflow.log_metrics({f"agent_{k}": v for k, v in summary["agent_metrics"].items() if isinstance(v, (int, float))})
    print("Logged to MLflow")
except Exception as exc:  # MLflow optional
    print(f"MLflow logging skipped: {exc}")

# COMMAND ----------

display(spark.sql(f"SELECT * FROM `{settings.catalog}`.`{settings.schema}`.v_lsi_evaluation_latest"))
