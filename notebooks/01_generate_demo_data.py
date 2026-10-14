# Databricks notebook source
# MAGIC %md
# MAGIC # 01 · Land the servicing exports
# MAGIC
# MAGIC In production, the servicing platform exports loans and servicing events every day. For this demo we
# MAGIC generate **synthetic** exports (1,500 loans, ~33,000 events) and land them as CSV files in a
# MAGIC **Unity Catalog volume**, exactly where real exports would arrive.

# COMMAND ----------

dbutils.widgets.text("catalog", "main")
dbutils.widgets.text("schema", "loan_servicing_intelligence")
catalog, schema = dbutils.widgets.get("catalog"), dbutils.widgets.get("schema")

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.{schema}")
spark.sql(f"CREATE VOLUME IF NOT EXISTS {catalog}.{schema}.landing")
spark.sql(f"USE {catalog}.{schema}")
landing = f"/Volumes/{catalog}/{schema}/landing/current"

# COMMAND ----------

# MAGIC %md ## 1. Generate today's synthetic exports and land them in the volume

# COMMAND ----------

import os

from synthetic_data import generate_dataset   # synthetic_data.py, next to this notebook

dataset = generate_dataset()   # fixed seed; dates relative to today
os.makedirs(landing, exist_ok=True)
for name, frame in dataset.tables().items():
    frame.to_csv(f"{landing}/{name}.csv", index=False)
    print(f"{name:28s} {len(frame):>7,} rows")

# COMMAND ----------

display(dbutils.fs.ls(landing))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Where the app writes back
# MAGIC When a specialist confirms an action in the app, the app records it in `app_actions` and the servicing
# MAGIC system's new event in `servicing_system_events`. The next pipeline run picks that event up and verifies it.

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE TABLE IF NOT EXISTS app_actions (
# MAGIC   action_id STRING, loan_id STRING, action_type STRING, event_type STRING, milestone_type STRING,
# MAGIC   followup_date DATE, note STRING, outreach STRING, submitted_by STRING, submitted_at TIMESTAMP
# MAGIC ) COMMENT 'Actions confirmed by a person in the app - SYNTHETIC DEMONSTRATION DATA';
# MAGIC
# MAGIC CREATE TABLE IF NOT EXISTS servicing_system_events (
# MAGIC   event_id STRING, loan_id STRING, event_type STRING, milestone_type STRING, event_date DATE,
# MAGIC   followup_date DATE, status STRING, event_note STRING, source STRING, created_at TIMESTAMP
# MAGIC ) COMMENT 'Events the servicing system created for confirmed actions - SYNTHETIC DEMONSTRATION DATA'

# COMMAND ----------

# MAGIC %md To reset the demo, clear what was confirmed in the app:

# COMMAND ----------

# MAGIC %sql
# MAGIC -- TRUNCATE TABLE app_actions; TRUNCATE TABLE servicing_system_events
