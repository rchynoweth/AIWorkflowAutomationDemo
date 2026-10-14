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
# MAGIC   current_balance DOUBLE, payment_status STRING, days_delinquent BIGINT, loan_status STRING,
# MAGIC   foreclosure_status STRING, specialist_name STRING, party_name STRING, party_type STRING
# MAGIC )
# MAGIC COMMENT 'Loan attributes, balances, statuses, assigned specialist and attorney or vendor'
# MAGIC RETURN
# MAGIC   SELECT
# MAGIC     loan_id, borrower_display_name, portfolio_id, property_state, CAST(current_balance AS DOUBLE),
# MAGIC     payment_status, CAST(days_delinquent AS BIGINT), loan_status, foreclosure_status, specialist_name,
# MAGIC     party_name, party_type
# MAGIC   FROM gold_loan_servicing_state
# MAGIC   WHERE loan_id = upper(lsi_get_loan_context.loan_id)

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE FUNCTION lsi_get_event_history(loan_id STRING COMMENT 'Synthetic loan identifier, for example LSI-SYN-000005')
# MAGIC RETURNS TABLE (
# MAGIC   event_date STRING, event_type STRING, milestone_type STRING, followup_date STRING,
# MAGIC   completed_date STRING, status STRING, source STRING, event_id STRING, event_note STRING
# MAGIC )
# MAGIC COMMENT 'Chronological servicing events for a loan, payments excluded'
# MAGIC RETURN
# MAGIC   SELECT
# MAGIC     CAST(event_date AS STRING), event_type, milestone_type, CAST(followup_date AS STRING),
# MAGIC     CAST(completed_date AS STRING), status, source, event_id, event_note
# MAGIC   FROM silver_loan_events
# MAGIC   WHERE loan_id = upper(lsi_get_event_history.loan_id)
# MAGIC   AND event_type <> 'PAYMENT_RECEIVED'
# MAGIC   ORDER BY event_date, event_id

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE FUNCTION lsi_get_current_milestone(loan_id STRING COMMENT 'Synthetic loan identifier, for example LSI-SYN-000005')
# MAGIC RETURNS TABLE (
# MAGIC   milestone_type STRING, status STRING, event_date STRING, followup_date STRING, completed_date STRING,
# MAGIC   event_id STRING
# MAGIC )
# MAGIC COMMENT 'Current servicing milestone of a loan (highest configured sequence, RULE-MILESTONE-001)'
# MAGIC RETURN
# MAGIC   SELECT
# MAGIC     milestone_type, status, CAST(event_date AS STRING), CAST(followup_date AS STRING),
# MAGIC     CAST(completed_date AS STRING), event_id
# MAGIC   FROM gold_loan_milestone_state
# MAGIC   WHERE loan_id = upper(lsi_get_current_milestone.loan_id)
# MAGIC   AND is_current

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE FUNCTION lsi_get_agent_proposals(loan_id STRING COMMENT 'Synthetic loan identifier, for example LSI-SYN-000005')
# MAGIC RETURNS TABLE (
# MAGIC   created_at STRING, recommended_action STRING, recommended_followup_date STRING, confidence STRING,
# MAGIC   status STRING, agent_mode STRING
# MAGIC )
# MAGIC COMMENT 'Existing agent proposals for a loan and their review status'
# MAGIC RETURN
# MAGIC   SELECT
# MAGIC     created_at, recommended_action, recommended_followup_date, confidence, status, agent_mode
# MAGIC   FROM ops_recommendations
# MAGIC   WHERE loan_id = upper(lsi_get_agent_proposals.loan_id)
# MAGIC   AND status <> 'SUPERSEDED'
# MAGIC   ORDER BY created_at DESC

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE FUNCTION lsi_get_ai_loan_insight(loan_id STRING COMMENT 'Synthetic loan identifier, for example LSI-SYN-000005')
# MAGIC RETURNS TABLE (
# MAGIC   ai_summary STRING, generated_at STRING, model_endpoint STRING
# MAGIC )
# MAGIC COMMENT 'AI Functions (ai_query) summary written by the backend workflow, if one exists'
# MAGIC RETURN
# MAGIC   SELECT
# MAGIC     ai_summary, CAST(generated_at AS STRING), model_endpoint
# MAGIC   FROM gold_ai_loan_insights
# MAGIC   WHERE loan_id = upper(lsi_get_ai_loan_insight.loan_id)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Rules and scoring
# MAGIC The deterministic facts from the rules engine - the agent reports them, never recalculates them.

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE FUNCTION lsi_check_followup_status(loan_id STRING COMMENT 'Synthetic loan identifier, for example LSI-SYN-000005')
# MAGIC RETURNS TABLE (
# MAGIC   current_milestone STRING, milestone_complete BOOLEAN, effective_followup_date STRING,
# MAGIC   days_to_followup STRING, days_overdue BIGINT, primary_condition STRING, secondary_conditions STRING,
# MAGIC   conditions_detail STRING, rule_ids STRING
# MAGIC )
# MAGIC COMMENT 'Effective follow-up date, days overdue, and the deterministic conditions detected for a loan'
# MAGIC RETURN
# MAGIC   SELECT
# MAGIC     current_milestone, CAST(milestone_complete AS BOOLEAN), CAST(effective_followup_date AS STRING),
# MAGIC     CAST(days_to_followup AS STRING), CAST(days_overdue AS BIGINT), primary_condition,
# MAGIC     secondary_conditions, raw_conditions, condition_rule_ids
# MAGIC   FROM gold_loan_servicing_state
# MAGIC   WHERE loan_id = upper(lsi_check_followup_status.loan_id)

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE FUNCTION lsi_get_milestone_rule(milestone_type STRING COMMENT 'Milestone code, for example TITLE_REVIEW')
# MAGIC RETURNS TABLE (
# MAGIC   milestone_type STRING, milestone_sequence BIGINT, default_followup_days BIGINT,
# MAGIC   lookahead_days BIGINT, requires_followup BOOLEAN, overdue_action STRING, next_milestone_type STRING,
# MAGIC   severity BIGINT
# MAGIC )
# MAGIC COMMENT 'Configured synthetic milestone rule: follow-up days, look-ahead, overdue action, next milestone, severity'
# MAGIC RETURN
# MAGIC   SELECT
# MAGIC     milestone_type, CAST(milestone_sequence AS BIGINT), CAST(default_followup_days AS BIGINT),
# MAGIC     CAST(lookahead_days AS BIGINT), requires_followup, overdue_action, next_milestone_type,
# MAGIC     CAST(severity AS BIGINT)
# MAGIC   FROM silver_milestone_rules
# MAGIC   WHERE milestone_type = upper(lsi_get_milestone_rule.milestone_type)
# MAGIC   AND active

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE FUNCTION lsi_get_escalation_state(loan_id STRING COMMENT 'Synthetic loan identifier, for example LSI-SYN-000005')
# MAGIC RETURNS TABLE (
# MAGIC   escalation_state STRING, required_role STRING, health_segment STRING, escalation_reasons STRING
# MAGIC )
# MAGIC COMMENT 'Deterministic escalation state, required approver role, and the escalation rules that matched'
# MAGIC RETURN
# MAGIC   SELECT
# MAGIC     escalation_state, required_role, health_segment, escalation_reasons
# MAGIC   FROM gold_loan_servicing_state
# MAGIC   WHERE loan_id = upper(lsi_get_escalation_state.loan_id)

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE FUNCTION lsi_get_attention_score(loan_id STRING COMMENT 'Synthetic loan identifier, for example LSI-SYN-000005')
# MAGIC RETURNS TABLE (
# MAGIC   attention_score BIGINT, priority STRING, score_drivers STRING, drivers_summary STRING,
# MAGIC   scoring_version STRING
# MAGIC )
# MAGIC COMMENT 'Deterministic attention score, priority, and score drivers. The agent must report, never recalculate, it'
# MAGIC RETURN
# MAGIC   SELECT
# MAGIC     CAST(attention_score AS BIGINT), priority, score_drivers, top_drivers_text, scoring_version
# MAGIC   FROM gold_loan_servicing_state
# MAGIC   WHERE loan_id = upper(lsi_get_attention_score.loan_id)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Safeguards
# MAGIC Checks the agent runs before recommending anything: allowed actions, duplicates, pending work, prior rejections.

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE FUNCTION lsi_get_open_followups(loan_id STRING COMMENT 'Synthetic loan identifier, for example LSI-SYN-000005')
# MAGIC RETURNS TABLE (
# MAGIC   event_id STRING, event_type STRING, milestone_type STRING, event_date STRING, followup_date STRING,
# MAGIC   source STRING
# MAGIC )
# MAGIC COMMENT 'Open follow-up type events for a loan; two or more of the same type for a milestone is a duplicate risk'
# MAGIC RETURN
# MAGIC   SELECT
# MAGIC     event_id, event_type, milestone_type, CAST(event_date AS STRING), CAST(followup_date AS STRING),
# MAGIC     source
# MAGIC   FROM silver_loan_events
# MAGIC   WHERE loan_id = upper(lsi_get_open_followups.loan_id)
# MAGIC   AND status = 'OPEN'
# MAGIC   AND event_type IN ('FOLLOWUP', 'CONTACT', 'ESCALATION', 'INFO_REQUEST', 'DATA_REVIEW')
# MAGIC   ORDER BY event_date

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE FUNCTION lsi_get_allowed_actions(loan_id STRING COMMENT 'Synthetic loan identifier, for example LSI-SYN-000005')
# MAGIC RETURNS TABLE (
# MAGIC   allowed_actions STRING, default_action STRING, removed_actions STRING
# MAGIC )
# MAGIC COMMENT 'Actions the agent may recommend for this loan, the deterministic default, and actions removed and why'
# MAGIC RETURN
# MAGIC   SELECT
# MAGIC     allowed_actions, default_action, removed_actions
# MAGIC   FROM gold_loan_servicing_state
# MAGIC   WHERE loan_id = upper(lsi_get_allowed_actions.loan_id)

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE FUNCTION lsi_check_pending_actions(loan_id STRING COMMENT 'Synthetic loan identifier, for example LSI-SYN-000005')
# MAGIC RETURNS TABLE (
# MAGIC   action_id STRING, action_type STRING, status STRING, followup_date STRING, origin STRING
# MAGIC )
# MAGIC COMMENT 'Approved or submitted actions still awaiting verification; a pending action means do not duplicate it'
# MAGIC RETURN
# MAGIC   SELECT
# MAGIC     action_id, action_type, status, followup_date, 'APP'
# MAGIC   FROM ops_actions
# MAGIC   WHERE loan_id = upper(lsi_check_pending_actions.loan_id)
# MAGIC   AND status IN ('APPROVED', 'SUBMITTED')
# MAGIC   UNION ALL SELECT
# MAGIC     action_id, action_type, 'SUBMITTED', CAST(followup_date AS STRING), 'HISTORY'
# MAGIC   FROM gold_pending_actions
# MAGIC   WHERE loan_id = upper(lsi_check_pending_actions.loan_id)

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE FUNCTION lsi_check_prior_rejections(loan_id STRING COMMENT 'Synthetic loan identifier, for example LSI-SYN-000005')
# MAGIC RETURNS TABLE (
# MAGIC   decided_at STRING, original_action STRING, reason STRING, reviewer_id STRING
# MAGIC )
# MAGIC COMMENT 'Prior reviewer rejections for a loan; recently rejected actions should not be re-proposed'
# MAGIC RETURN
# MAGIC   SELECT
# MAGIC     CAST(decided_at AS STRING), original_action, reason, reviewer_id
# MAGIC   FROM gold_reviewer_decisions
# MAGIC   WHERE loan_id = upper(lsi_check_prior_rejections.loan_id)
# MAGIC   AND decision = 'REJECT'
# MAGIC   ORDER BY decided_at DESC

# COMMAND ----------

# MAGIC %md
# MAGIC ## Portfolio
# MAGIC Questions about the whole book of loans.

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE FUNCTION lsi_priority_queue(max_rows INT COMMENT 'Number of queue rows to return, for example 10')
# MAGIC RETURNS TABLE (
# MAGIC   queue_rank BIGINT, priority STRING, loan_id STRING, primary_condition STRING, attention_score BIGINT,
# MAGIC   top_drivers STRING, recommended_action STRING, why_prioritized STRING
# MAGIC )
# MAGIC COMMENT 'Ranked servicing work queue across the portfolio'
# MAGIC RETURN
# MAGIC   SELECT
# MAGIC     CAST(queue_rank AS BIGINT), priority, loan_id, primary_condition, CAST(attention_score AS BIGINT),
# MAGIC     top_drivers_text, recommended_action, why_prioritized
# MAGIC   FROM gold_priority_queue
# MAGIC   WHERE CAST(queue_rank AS INT) <= lsi_priority_queue.max_rows

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE FUNCTION lsi_portfolio_health_summary()
# MAGIC RETURNS TABLE (
# MAGIC   health_segment STRING, loan_count BIGINT, share_of_active DOUBLE
# MAGIC )
# MAGIC COMMENT 'Portfolio health segments: Healthy, Watch, Action Required, Critical'
# MAGIC RETURN
# MAGIC   SELECT
# MAGIC     health_segment, CAST(loan_count AS BIGINT), CAST(share_of_active AS DOUBLE)
# MAGIC   FROM gold_portfolio_health

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE FUNCTION lsi_specialist_workload()
# MAGIC RETURNS TABLE (
# MAGIC   specialist_name STRING, assigned_loans BIGINT, need_attention BIGINT, critical BIGINT, high BIGINT
# MAGIC )
# MAGIC COMMENT 'Per-specialist assigned loans, loans needing attention, critical and high counts'
# MAGIC RETURN
# MAGIC   SELECT
# MAGIC     specialist_name, CAST(assigned_loans AS BIGINT), CAST(need_attention AS BIGINT),
# MAGIC     CAST(critical AS BIGINT), CAST(high AS BIGINT)
# MAGIC   FROM v_lsi_specialist_workload

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE FUNCTION lsi_get_failed_verifications()
# MAGIC RETURNS TABLE (
# MAGIC   action_id STRING, loan_id STRING, action_type STRING, verification_status STRING, detail STRING
# MAGIC )
# MAGIC COMMENT 'Approved actions that failed verification against the servicing system'
# MAGIC RETURN
# MAGIC   SELECT
# MAGIC     action_id, loan_id, action_type, verification_status, detail
# MAGIC   FROM v_lsi_verification_failures

# COMMAND ----------

# MAGIC %md
# MAGIC ## Try the tools
# MAGIC These are exactly the calls the agent makes.

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT * FROM lsi_get_attention_score('LSI-SYN-000005')

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT * FROM lsi_get_allowed_actions('LSI-SYN-000005')

# COMMAND ----------

# MAGIC %sql
# MAGIC SHOW USER FUNCTIONS LIKE 'lsi_*'
