# Databricks notebook source
# MAGIC %md
# MAGIC # 03 · Silver: clean, typed, trustworthy data
# MAGIC
# MAGIC Plain SQL. Each cell turns a raw Bronze table into a typed, de-duplicated Silver table:
# MAGIC strings become dates, numbers, and booleans; blanks become NULL; duplicates keep the latest version;
# MAGIC every event knows its milestone order; bad dates are flagged, not dropped.

# COMMAND ----------

dbutils.widgets.text("catalog", "main")
dbutils.widgets.text("schema", "loan_servicing_intelligence")
spark.sql(f"USE {dbutils.widgets.get('catalog')}.{dbutils.widgets.get('schema')}")

# COMMAND ----------

# MAGIC %md ### Milestone rules (the configured servicing sequence)

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE TABLE silver_milestone_rules AS
# MAGIC SELECT
# MAGIC   upper(milestone_type)                  AS milestone_type,
# MAGIC   CAST(milestone_sequence AS INT)        AS milestone_sequence,
# MAGIC   CAST(default_followup_days AS INT)     AS default_followup_days,
# MAGIC   CAST(lookahead_days AS INT)            AS lookahead_days,
# MAGIC   requires_followup = 'true'             AS requires_followup,
# MAGIC   upper(overdue_action)                  AS overdue_action,
# MAGIC   nullif(upper(next_milestone_type), '') AS next_milestone_type,
# MAGIC   CAST(severity AS INT)                  AS severity,
# MAGIC   active = 'true'                        AS active,
# MAGIC   true                                   AS synthetic_data
# MAGIC FROM bronze_milestone_rules

# COMMAND ----------

# MAGIC %md ### People and parties

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE TABLE silver_servicing_specialists AS
# MAGIC SELECT upper(specialist_id) AS specialist_id, display_name, team, active = 'true' AS active, true AS synthetic_data
# MAGIC FROM bronze_servicing_specialists;
# MAGIC
# MAGIC CREATE OR REPLACE TABLE silver_attorneys_vendors AS
# MAGIC SELECT upper(party_id) AS party_id, display_name, upper(party_type) AS party_type, upper(state) AS state,
# MAGIC        active = 'true' AS active, true AS synthetic_data
# MAGIC FROM bronze_attorneys_vendors

# COMMAND ----------

# MAGIC %md ### Loans

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE TABLE silver_loans AS
# MAGIC SELECT
# MAGIC   upper(l.loan_id) AS loan_id, l.borrower_display_name, l.property_address, l.property_city,
# MAGIC   upper(l.property_state) AS property_state, l.property_postal_code, l.property_county,
# MAGIC   CAST(l.original_balance AS DOUBLE) AS original_balance, CAST(l.current_balance AS DOUBLE) AS current_balance,
# MAGIC   upper(l.loan_status) AS loan_status, upper(l.payment_status) AS payment_status,
# MAGIC   CAST(l.days_delinquent AS INT) AS days_delinquent, upper(l.foreclosure_status) AS foreclosure_status,
# MAGIC   upper(l.assigned_specialist_id) AS assigned_specialist_id,
# MAGIC   nullif(upper(l.assigned_attorney_vendor_id), '') AS assigned_attorney_vendor_id,
# MAGIC   to_date(l.boarding_date) AS boarding_date, upper(l.portfolio_id) AS portfolio_id,
# MAGIC   s.display_name AS specialist_name, p.display_name AS party_name, p.party_type,
# MAGIC   upper(l.loan_status) = 'ACTIVE' AS is_active,
# MAGIC   true AS synthetic_data
# MAGIC FROM bronze_loans l
# MAGIC LEFT JOIN silver_servicing_specialists s ON s.specialist_id = upper(l.assigned_specialist_id)
# MAGIC LEFT JOIN silver_attorneys_vendors p     ON p.party_id = upper(l.assigned_attorney_vendor_id)

# COMMAND ----------

# MAGIC %md ### Servicing events
# MAGIC Typed dates, latest version of each event, milestone order from the rules, and data-quality flags.

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE TABLE silver_loan_events AS
# MAGIC WITH typed AS (
# MAGIC   SELECT
# MAGIC     upper(event_id) AS event_id, upper(loan_id) AS loan_id, upper(event_type) AS event_type,
# MAGIC     nullif(upper(milestone_type), '') AS milestone_type,
# MAGIC     to_date(nullif(event_date, '')) AS event_date,
# MAGIC     to_date(nullif(followup_date, '')) AS followup_date,
# MAGIC     to_date(nullif(completed_date, '')) AS completed_date,
# MAGIC     upper(status) AS status, event_note, upper(source) AS source,
# MAGIC     to_timestamp(created_at) AS created_at, to_timestamp(updated_at) AS updated_at
# MAGIC   FROM bronze_loan_events
# MAGIC ),
# MAGIC latest AS (   -- keep the most recent version of each event
# MAGIC   SELECT * FROM typed QUALIFY row_number() OVER (PARTITION BY event_id ORDER BY updated_at DESC) = 1
# MAGIC )
# MAGIC SELECT
# MAGIC   e.*,
# MAGIC   coalesce(r.milestone_sequence, -1) AS milestone_sequence,
# MAGIC   row_number() OVER (PARTITION BY e.loan_id ORDER BY e.event_date, e.created_at, e.event_id) AS event_sequence,
# MAGIC   e.status = 'OPEN' AS is_open,
# MAGIC   e.event_type IN ('FOLLOWUP', 'CONTACT', 'ESCALATION', 'INFO_REQUEST', 'DATA_REVIEW') AS is_followup_type,
# MAGIC   concat_ws(';',
# MAGIC     CASE WHEN e.event_type = 'MILESTONE' AND e.completed_date < e.event_date THEN 'COMPLETED_BEFORE_EVENT' END,
# MAGIC     CASE WHEN e.event_type = 'MILESTONE' AND e.status = 'COMPLETED' AND e.completed_date IS NULL
# MAGIC          THEN 'COMPLETED_WITHOUT_DATE' END) AS dq_issues,
# MAGIC   true AS synthetic_data
# MAGIC FROM latest e
# MAGIC LEFT JOIN silver_milestone_rules r ON r.milestone_type = e.milestone_type AND r.active

# COMMAND ----------

# MAGIC %md ### Prior actions and reviewer decisions

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE TABLE silver_servicing_action_history AS
# MAGIC SELECT upper(action_id) AS action_id, upper(loan_id) AS loan_id, recommendation_id, upper(action_type) AS action_type,
# MAGIC        upper(event_type) AS event_type, to_date(event_date) AS event_date, to_date(nullif(followup_date, '')) AS followup_date,
# MAGIC        upper(status) AS status, to_timestamp(nullif(submitted_at, '')) AS submitted_at,
# MAGIC        to_timestamp(nullif(verified_at, '')) AS verified_at, nullif(failure_reason, '') AS failure_reason,
# MAGIC        true AS synthetic_data
# MAGIC FROM bronze_servicing_action_history;
# MAGIC
# MAGIC CREATE OR REPLACE TABLE silver_reviewer_decisions AS
# MAGIC SELECT upper(decision_id) AS decision_id, recommendation_id, upper(loan_id) AS loan_id, reviewer_id,
# MAGIC        upper(decision) AS decision, upper(original_action) AS original_action,
# MAGIC        nullif(upper(final_action), '') AS final_action,
# MAGIC        to_date(nullif(original_followup_date, '')) AS original_followup_date,
# MAGIC        to_date(nullif(final_followup_date, '')) AS final_followup_date,
# MAGIC        original_note, final_note, reason, to_timestamp(decided_at) AS decided_at, true AS synthetic_data
# MAGIC FROM bronze_reviewer_decisions

# COMMAND ----------

# MAGIC %md ### Data quality at a glance

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT 'silver_loans' AS table_name, count(*) AS rows FROM silver_loans
# MAGIC UNION ALL SELECT 'silver_loan_events', count(*) FROM silver_loan_events
# MAGIC UNION ALL SELECT 'events with data-quality issues', count(*) FROM silver_loan_events WHERE dq_issues <> ''
