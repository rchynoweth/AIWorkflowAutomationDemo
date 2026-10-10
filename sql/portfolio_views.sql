-- Loan Servicing Intelligence: portfolio/agent views over operational tables (SYNTHETIC DEMONSTRATION DATA).
-- ${catalog} and ${schema} are substituted by src/pipeline.py.

CREATE OR REPLACE VIEW `${catalog}`.`${schema}`.`gold_agent_recommendations`
COMMENT 'Agent recommendations (synthetic). JSON-encoded list columns.' AS
SELECT recommendation_id, loan_id, primary_condition, secondary_conditions,
       CAST(attention_score AS INT) AS attention_score, priority, score_drivers, recommended_action,
       recommended_event_type, recommended_followup_date, suggested_note, suggested_outreach, rationale, evidence,
       confidence, uncertainty, missing_information, tool_calls, CAST(created_at AS TIMESTAMP) AS created_at,
       agent_version, rule_version, scoring_version, status, requires_human_approval, allowed_actions,
       escalation_state, agent_mode, run_id
FROM `${catalog}`.`${schema}`.`ops_recommendations`;

CREATE OR REPLACE VIEW `${catalog}`.`${schema}`.`gold_reviewer_decisions`
COMMENT 'Reviewer decisions: live (ops) plus synthetic history.' AS
SELECT decision_id, recommendation_id, loan_id, reviewer_id, reviewer_role, decision, original_action, final_action,
       original_followup_date, final_followup_date, reason, CAST(decided_at AS TIMESTAMP) AS decided_at, 'APP' AS origin
FROM `${catalog}`.`${schema}`.`ops_reviewer_decisions`
UNION ALL
SELECT decision_id, recommendation_id, loan_id, reviewer_id, NULL AS reviewer_role, decision, original_action,
       final_action, CAST(original_followup_date AS STRING), CAST(final_followup_date AS STRING), reason,
       CAST(decided_at AS TIMESTAMP), 'HISTORY' AS origin
FROM `${catalog}`.`${schema}`.`silver_reviewer_decisions`
WHERE decision_id NOT IN (SELECT decision_id FROM `${catalog}`.`${schema}`.`ops_reviewer_decisions`);

CREATE OR REPLACE VIEW `${catalog}`.`${schema}`.`gold_agent_activity`
COMMENT 'Agent, tool, reviewer, adapter, and system activity (summaries only; no prompts or reasoning).' AS
SELECT activity_id, run_id, loan_id, actor, step, tool_name, input_summary, output_summary,
       CAST(duration_ms AS DOUBLE) AS duration_ms, CAST(success AS BOOLEAN) AS success, error,
       CAST(created_at AS TIMESTAMP) AS created_at
FROM `${catalog}`.`${schema}`.`ops_agent_activity`;
