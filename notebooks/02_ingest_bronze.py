# Databricks notebook source
# MAGIC %md
# MAGIC # 02 · Bronze: ingest the raw exports
# MAGIC
# MAGIC Bronze keeps an **exact copy** of every source file as a Delta table, plus lineage columns, so every
# MAGIC downstream fact can be traced back to the file and row it came from.

# COMMAND ----------

dbutils.widgets.text("catalog", "main")
dbutils.widgets.text("schema", "loan_servicing_intelligence")
catalog, schema = dbutils.widgets.get("catalog"), dbutils.widgets.get("schema")
spark.sql(f"USE {catalog}.{schema}")
landing = f"/Volumes/{catalog}/{schema}/landing/current"

# COMMAND ----------

from pyspark.sql import functions as F

SOURCES = ["loans", "loan_events", "milestone_rules", "servicing_specialists", "attorneys_vendors",
           "servicing_action_history", "reviewer_decisions"]

for name in SOURCES:
    raw = spark.read.option("header", True).option("multiLine", True).option("escape", '"').csv(f"{landing}/{name}.csv")
    bronze = (raw
              .withColumn("source_file", F.col("_metadata.file_path"))
              .withColumn("ingested_at", F.current_timestamp())
              .withColumn("record_hash", F.sha2(F.concat_ws("|", *raw.columns), 256)))
    bronze.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"bronze_{name}")
    print(f"bronze_{name:26s} {bronze.count():>7,} rows")

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT loan_id, event_type, milestone_type, event_date, followup_date, status, source_file, ingested_at
# MAGIC FROM bronze_loan_events
# MAGIC LIMIT 10
