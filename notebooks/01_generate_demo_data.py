# Databricks notebook source
# MAGIC %md
# MAGIC # 01 · Land the servicing exports
# MAGIC
# MAGIC In production, the servicing platform exports loans and servicing events every day. For this demo we
# MAGIC generate **synthetic** exports (1,500 loans, ~33,000 events) and land them as CSV files in a
# MAGIC **Unity Catalog volume**, exactly where real exports would arrive.

# COMMAND ----------

# MAGIC %pip install -q pyyaml "pandas>=2.0,<3"

# COMMAND ----------

dbutils.widgets.text("catalog", "main")
dbutils.widgets.text("schema", "loan_servicing_intelligence")
catalog, schema = dbutils.widgets.get("catalog"), dbutils.widgets.get("schema")

# COMMAND ----------

# MAGIC %md ## 1. A governed home for the data

# COMMAND ----------

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.{schema}")
spark.sql(f"CREATE VOLUME IF NOT EXISTS {catalog}.{schema}.landing")
landing = f"/Volumes/{catalog}/{schema}/landing/current"

# COMMAND ----------

# MAGIC %md ## 2. Generate the synthetic exports and land them in the volume

# COMMAND ----------

import os
import sys

sys.path.insert(0, os.path.abspath(".."))  # the repository root: the synthetic data generator lives in src/
from src.synthetic_data import generate_dataset

dataset = generate_dataset()  # fixed seed: the same data every run
os.makedirs(landing, exist_ok=True)
for name, frame in dataset.tables().items():
    frame.to_csv(f"{landing}/{name}.csv", index=False)
    print(f"{name:28s} {len(frame):>7,} rows")

# COMMAND ----------

# MAGIC %md ## 3. What landed

# COMMAND ----------

display(dbutils.fs.ls(landing))

# COMMAND ----------

display(spark.read.option("header", True).csv(f"{landing}/loan_events.csv").limit(10))
