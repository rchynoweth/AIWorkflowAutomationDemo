# Databricks notebook source
# MAGIC %md
# MAGIC # 04 · Gold: the rules engine scores every loan
# MAGIC
# MAGIC Objective checks stay **deterministic**: what milestone a loan is on, whether its follow-up is overdue,
# MAGIC how urgent it is, and which actions are allowed. The rules are **configuration** (`config/*.yml`) and the
# MAGIC engine is plain Python (`src/rules.py`). The AI steps that follow build on these facts.

# COMMAND ----------

# MAGIC %pip install -q pyyaml pydantic "pandas>=2.0,<3"

# COMMAND ----------

import os
import sys
from pathlib import Path

dbutils.widgets.text("catalog", "main")
dbutils.widgets.text("schema", "loan_servicing_intelligence")
os.environ["LSI_CATALOG"], os.environ["LSI_SCHEMA"] = dbutils.widgets.get("catalog"), dbutils.widgets.get("schema")
sys.path.insert(0, os.path.abspath(".."))

import pandas as pd
from src.config import load_settings
from src.medallion import build_gold_tables
from src.rules import (compute_allowed_actions, compute_attention_score, compute_escalation, evaluate_conditions,
                       evaluate_portfolio)
from src.storage import SparkRepository
from src import pipeline

settings = load_settings()
spark.sql(f"USE {settings.catalog}.{settings.schema}")

# COMMAND ----------

# MAGIC %md ## 1. The rules are configuration
# MAGIC Points per condition and factor, and the priority thresholds (synthetic, editable):

# COMMAND ----------

scoring = settings.attention_scoring
display(pd.DataFrame([{"condition": k, "points": v} for k, v in scoring["condition_points"].items()]))
display(pd.DataFrame([{"priority": k, "minimum score": v} for k, v in scoring["priority_thresholds"].items()]))

# COMMAND ----------

# MAGIC %md ## 2. Walk one loan through the engine

# COMMAND ----------

silver = SparkRepository(spark, settings).load_source_silver()   # Silver tables -> Python
evaluation = evaluate_portfolio(silver, settings)                  # every loan, about one second
facts = evaluation.facts["LSI-SYN-000005"]
ctx = evaluation.ctx

print("Current milestone:", facts.current_milestone["milestone_type"])
print("Follow-up date:   ", facts.effective_followup_date, f"({facts.days_overdue} days overdue)")

conditions = evaluate_conditions(facts, ctx)
print("\nConditions:")
for c in conditions["raw_conditions"]:
    print(f"  {c['code']:<22} {c['rule_id']:<20} {c['detail']}")

escalation = compute_escalation(facts, conditions, ctx)
print("\nEscalation:", escalation["escalation_state"], "->", escalation["required_role"])

score = compute_attention_score(facts, conditions, ctx)
print(f"\nAttention score {score['score']} ({score['priority']}):")
for d in score["score_drivers"]:
    print(f"  {d['points']:+4d}  {d['detail']}")

allowed = compute_allowed_actions(facts, conditions, escalation, ctx)
print("\nAllowed actions:", allowed["allowed_actions"])

# COMMAND ----------

# MAGIC %md ## 3. Every loan, written to Gold

# COMMAND ----------

for name, frame in build_gold_tables(evaluation).items():
    if not frame.empty:
        pipeline.write_table(spark, settings, name, frame)
        print(f"{name:32s} {len(frame):>6,} rows")
SparkRepository(spark, settings).ensure_ops_tables()
for views in ("../sql/portfolio_views.sql", "../sql/monitoring_views.sql"):
    pipeline.run_sql_file(spark, settings, Path(views))

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT queue_rank, priority, loan_id, primary_condition, attention_score, top_drivers_text
# MAGIC FROM gold_priority_queue
# MAGIC ORDER BY CAST(queue_rank AS INT)
# MAGIC LIMIT 15

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT health_segment, loan_count FROM gold_portfolio_health
