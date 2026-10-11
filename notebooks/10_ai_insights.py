# Databricks notebook source
# MAGIC %md
# MAGIC # Loan Servicing Intelligence — AI Functions insights
# MAGIC
# MAGIC > **Synthetic demonstration data.** All loans, borrowers, rules, thresholds, and metrics are synthetic.
# MAGIC
# MAGIC Uses Databricks **AI Functions** (`ai_query`) in SQL to write a one-sentence summary for each CRITICAL/HIGH loan (`gold_ai_loan_insights`) and a portfolio briefing (`gold_ai_portfolio_briefing`) from deterministic Gold facts.
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

result = pipeline.ai_insights(spark, settings)
print(result)

# COMMAND ----------

display(spark.sql(f"SELECT loan_id, priority, ai_summary FROM {pipeline.fq(settings, 'gold_ai_loan_insights')} ORDER BY attention_score DESC"))

# COMMAND ----------

display(spark.sql(f"SELECT briefing, generated_at FROM {pipeline.fq(settings, 'gold_ai_portfolio_briefing')}"))
