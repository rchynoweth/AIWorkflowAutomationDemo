# Databricks notebook source
# MAGIC %md
# MAGIC # 05 · The agent's tools: Unity Catalog functions
# MAGIC
# MAGIC **This notebook is where every agent tool is defined and registered.**
# MAGIC
# MAGIC Each tool is an ordinary SQL function in Unity Catalog. That gives the agent tools that are:
# MAGIC - **governed** - permissions, lineage, and audit come from Unity Catalog;
# MAGIC - **self-describing** - the `COMMENT` on the function and on each parameter is exactly what the model reads
# MAGIC   when it decides which tool to call;
# MAGIC - **reusable** - the same functions work in SQL, in the AI Playground, in Genie, and for any agent.
# MAGIC
# MAGIC Run this once (and again whenever a tool changes, followed by notebook 06 to redeploy the agent).

# COMMAND ----------

dbutils.widgets.text("catalog", "main")
dbutils.widgets.text("schema", "loan_servicing_intelligence")
spark.sql(f"USE {dbutils.widgets.get('catalog')}.{dbutils.widgets.get('schema')}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Loan facts
# MAGIC What the agent can look up about a loan.

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE FUNCTION lsi_get_loan_context(loan_id STRING COMMENT 'Synthetic loan identifier, for example LSI-SYN-000005')
# MAGIC RETURNS TABLE (
# MAGIC   loan_id STRING, borrower_display_name STRING, portfolio_id STRING, property_state STRING,
# MAGIC   current_balance DOUBLE, payment_status STRING, days_delinquent INT, loan_status STRING,
# MAGIC   foreclosure_status STRING, specialist_name STRING, party_name STRING, party_type STRING
# MAGIC )
# MAGIC COMMENT 'Loan attributes, balance, statuses, assigned specialist and attorney or vendor'
# MAGIC RETURN
# MAGIC   SELECT loan_id, borrower_display_name, portfolio_id, property_state, current_balance, payment_status,
# MAGIC          days_delinquent, loan_status, foreclosure_status, specialist_name, party_name, party_type
# MAGIC   FROM gold_loan_state
# MAGIC   WHERE loan_id = upper(lsi_get_loan_context.loan_id)

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE FUNCTION lsi_get_event_history(loan_id STRING COMMENT 'Synthetic loan identifier, for example LSI-SYN-000005')
# MAGIC RETURNS TABLE (
# MAGIC   event_date DATE, event_type STRING, milestone_type STRING, followup_date DATE, completed_date DATE,
# MAGIC   status STRING, source STRING, event_note STRING
# MAGIC )
# MAGIC COMMENT 'Chronological servicing events for a loan (payments excluded)'
# MAGIC RETURN
# MAGIC   SELECT event_date, event_type, milestone_type, followup_date, completed_date, status, source, event_note
# MAGIC   FROM silver_loan_events
# MAGIC   WHERE loan_id = upper(lsi_get_event_history.loan_id) AND event_type <> 'PAYMENT_RECEIVED'
# MAGIC   ORDER BY event_date, event_sequence

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE FUNCTION lsi_get_current_milestone(loan_id STRING COMMENT 'Synthetic loan identifier, for example LSI-SYN-000005')
# MAGIC RETURNS TABLE (
# MAGIC   current_milestone STRING, milestone_status STRING, milestone_date DATE, milestone_completed_date DATE,
# MAGIC   followup_date DATE, next_milestone STRING, next_milestone_opened BOOLEAN
# MAGIC )
# MAGIC COMMENT 'Current servicing milestone of a loan, its follow-up date, and the next milestone in the sequence'
# MAGIC RETURN
# MAGIC   SELECT current_milestone, milestone_status, milestone_date, milestone_completed_date, followup_date,
# MAGIC          next_milestone, next_milestone_opened
# MAGIC   FROM gold_loan_state
# MAGIC   WHERE loan_id = upper(lsi_get_current_milestone.loan_id)

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE FUNCTION lsi_get_milestone_rule(milestone_type STRING COMMENT 'Milestone code, for example TITLE_REVIEW')
# MAGIC RETURNS TABLE (
# MAGIC   milestone_type STRING, milestone_sequence INT, default_followup_days INT, lookahead_days INT,
# MAGIC   requires_followup BOOLEAN, overdue_action STRING, next_milestone_type STRING, severity INT
# MAGIC )
# MAGIC COMMENT 'Configured milestone rule: follow-up days, look-ahead, overdue action, next milestone, severity'
# MAGIC RETURN
# MAGIC   SELECT milestone_type, milestone_sequence, default_followup_days, lookahead_days, requires_followup,
# MAGIC          overdue_action, next_milestone_type, severity
# MAGIC   FROM silver_milestone_rules
# MAGIC   WHERE milestone_type = upper(lsi_get_milestone_rule.milestone_type) AND active

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE FUNCTION lsi_get_ai_loan_insight(loan_id STRING COMMENT 'Synthetic loan identifier, for example LSI-SYN-000005')
# MAGIC RETURNS TABLE (ai_summary STRING, generated_at TIMESTAMP)
# MAGIC COMMENT 'AI Functions (ai_query) summary written by the backend workflow, if one exists'
# MAGIC RETURN
# MAGIC   SELECT ai_summary, generated_at
# MAGIC   FROM gold_ai_loan_insights
# MAGIC   WHERE loan_id = upper(lsi_get_ai_loan_insight.loan_id)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Rules and scoring
# MAGIC The deterministic facts from notebook 04 - the agent reports them, never recalculates them.

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE FUNCTION lsi_check_followup_status(loan_id STRING COMMENT 'Synthetic loan identifier, for example LSI-SYN-000005')
# MAGIC RETURNS TABLE (
# MAGIC   followup_date DATE, days_to_followup INT, days_overdue INT, primary_condition STRING, conditions STRING
# MAGIC )
# MAGIC COMMENT 'Follow-up date, days overdue, and every condition the rules detected for a loan, with rule IDs'
# MAGIC RETURN
# MAGIC   SELECT followup_date, days_to_followup, days_overdue, primary_condition, to_json(conditions)
# MAGIC   FROM gold_loan_state
# MAGIC   WHERE loan_id = upper(lsi_check_followup_status.loan_id)

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE FUNCTION lsi_get_attention_score(loan_id STRING COMMENT 'Synthetic loan identifier, for example LSI-SYN-000005')
# MAGIC RETURNS TABLE (attention_score INT, priority STRING, queue_rank INT, score_drivers STRING)
# MAGIC COMMENT 'Attention score, priority, queue rank, and the points behind the score. Report it; never recalculate it'
# MAGIC RETURN
# MAGIC   SELECT attention_score, priority, queue_rank, to_json(score_drivers)
# MAGIC   FROM gold_loan_state
# MAGIC   WHERE loan_id = upper(lsi_get_attention_score.loan_id)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Safeguards
# MAGIC Checks the agent runs before recommending anything: allowed actions, pending work, prior rejections.

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE FUNCTION lsi_get_allowed_actions(loan_id STRING COMMENT 'Synthetic loan identifier, for example LSI-SYN-000005')
# MAGIC RETURNS TABLE (allowed_actions STRING, default_action STRING, recently_rejected STRING)
# MAGIC COMMENT 'The only actions that may be recommended for this loan, the rules default, and recently rejected actions'
# MAGIC RETURN
# MAGIC   SELECT array_join(allowed_actions, ', '), recommended_action, array_join(rejected_actions, ', ')
# MAGIC   FROM gold_loan_state
# MAGIC   WHERE loan_id = upper(lsi_get_allowed_actions.loan_id)

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE FUNCTION lsi_check_pending_actions(loan_id STRING COMMENT 'Synthetic loan identifier, for example LSI-SYN-000005')
# MAGIC RETURNS TABLE (
# MAGIC   action_id STRING, action_type STRING, followup_date DATE, submitted_date DATE, verification_status STRING
# MAGIC )
# MAGIC COMMENT 'Approved actions for a loan and whether they landed in the servicing system; PENDING means do not duplicate'
# MAGIC RETURN
# MAGIC   SELECT action_id, action_type, followup_date, submitted_date, verification_status
# MAGIC   FROM gold_action_verification
# MAGIC   WHERE loan_id = upper(lsi_check_pending_actions.loan_id)
# MAGIC   UNION ALL   -- confirmed in the app since the last pipeline run
# MAGIC   SELECT action_id, action_type, followup_date, CAST(submitted_at AS DATE), 'PENDING'
# MAGIC   FROM app_actions
# MAGIC   WHERE loan_id = upper(lsi_check_pending_actions.loan_id)
# MAGIC     AND action_id NOT IN (SELECT action_id FROM gold_action_verification)

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE FUNCTION lsi_check_prior_rejections(loan_id STRING COMMENT 'Synthetic loan identifier, for example LSI-SYN-000005')
# MAGIC RETURNS TABLE (decided_at TIMESTAMP, original_action STRING, reason STRING)
# MAGIC COMMENT 'Reviewer rejections for a loan; recently rejected actions should not be proposed again'
# MAGIC RETURN
# MAGIC   SELECT decided_at, original_action, reason
# MAGIC   FROM silver_reviewer_decisions
# MAGIC   WHERE loan_id = upper(lsi_check_prior_rejections.loan_id) AND decision = 'REJECT'
# MAGIC   ORDER BY decided_at DESC

# COMMAND ----------

# MAGIC %md
# MAGIC ## Portfolio
# MAGIC Questions about the whole book of loans.

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE FUNCTION lsi_priority_queue(max_rows INT COMMENT 'Number of loans to return, for example 10')
# MAGIC RETURNS TABLE (
# MAGIC   queue_rank INT, loan_id STRING, priority STRING, attention_score INT, primary_condition STRING,
# MAGIC   top_drivers STRING, recommended_action STRING
# MAGIC )
# MAGIC COMMENT 'The ranked work queue: active loans, highest attention score first'
# MAGIC RETURN
# MAGIC   SELECT queue_rank, loan_id, priority, attention_score, primary_condition, top_drivers, recommended_action
# MAGIC   FROM gold_loan_state
# MAGIC   WHERE queue_rank <= lsi_priority_queue.max_rows
# MAGIC   ORDER BY queue_rank

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE FUNCTION lsi_portfolio_summary()
# MAGIC RETURNS TABLE (priority STRING, primary_condition STRING, loans BIGINT, total_balance DOUBLE)
# MAGIC COMMENT 'Active loans by priority and primary condition, with total balance'
# MAGIC RETURN
# MAGIC   SELECT priority, primary_condition, count(*), round(sum(current_balance), 2)
# MAGIC   FROM gold_loan_state
# MAGIC   WHERE is_active
# MAGIC   GROUP BY priority, primary_condition
# MAGIC   ORDER BY min(queue_rank)

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE FUNCTION lsi_get_failed_verifications()
# MAGIC RETURNS TABLE (
# MAGIC   action_id STRING, loan_id STRING, action_type STRING, submitted_date DATE, verification_status STRING
# MAGIC )
# MAGIC COMMENT 'Approved actions that did not land in the servicing system as approved'
# MAGIC RETURN
# MAGIC   SELECT action_id, loan_id, action_type, submitted_date, verification_status
# MAGIC   FROM gold_action_verification
# MAGIC   WHERE verification_status IN ('NOT_FOUND', 'MISMATCH', 'DUPLICATE')
# MAGIC   ORDER BY submitted_date DESC

# COMMAND ----------

# MAGIC %md
# MAGIC ## Try the tools
# MAGIC These are exactly the calls the agent makes.

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT * FROM lsi_get_attention_score('LSI-SYN-000005')

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT * FROM lsi_get_allowed_actions('LSI-SYN-000007')

# COMMAND ----------

# MAGIC %sql
# MAGIC SHOW USER FUNCTIONS LIKE 'lsi_*'
