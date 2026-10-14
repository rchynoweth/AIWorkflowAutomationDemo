"""Unity Catalog SQL table functions: the governed toolset of the deployed Loan Servicing Agent.

Each function is read-only, documented (function and parameter comments become the tool description the model
sees), and executes against governed Gold/Silver/ops tables. Registered by notebooks/05_register_agent_tools.py
(and scripts/register_uc_tools.py). SYNTHETIC DEMONSTRATION DATA.
"""
from __future__ import annotations

LOAN_PARAM = "loan_id STRING COMMENT 'Synthetic loan identifier, for example LSI-SYN-000005'"


def tool_names() -> list[str]:
    return [name for name, _ in uc_function_statements("c", "s")]


def uc_function_statements(catalog: str, schema: str) -> list[tuple[str, str]]:
    t = f"`{catalog}`.`{schema}`"

    def fn(name: str, params: str, returns: str, comment: str, body: str) -> tuple[str, str]:
        safe = comment.replace("'", "")
        return name, (f"CREATE OR REPLACE FUNCTION {t}.`{name}`({params}) RETURNS TABLE ({returns}) "
                      f"COMMENT '{safe} (synthetic demonstration data)' RETURN {body}")

    def loan(name: str) -> str:
        return f"upper({name}.loan_id)"

    return [
        fn("lsi_get_loan_context", LOAN_PARAM,
           "loan_id STRING, borrower_display_name STRING, portfolio_id STRING, property_state STRING, "
           "current_balance DOUBLE, payment_status STRING, days_delinquent BIGINT, loan_status STRING, "
           "foreclosure_status STRING, specialist_name STRING, party_name STRING, party_type STRING",
           "Loan attributes, balances, statuses, assigned specialist and attorney or vendor",
           f"SELECT loan_id, borrower_display_name, portfolio_id, property_state, CAST(current_balance AS DOUBLE), "
           f"payment_status, CAST(days_delinquent AS BIGINT), loan_status, foreclosure_status, specialist_name, "
           f"party_name, party_type FROM {t}.gold_loan_servicing_state "
           f"WHERE loan_id = {loan('lsi_get_loan_context')}"),
        fn("lsi_get_event_history", LOAN_PARAM,
           "event_date STRING, event_type STRING, milestone_type STRING, followup_date STRING, completed_date STRING, "
           "status STRING, source STRING, event_id STRING, event_note STRING",
           "Chronological servicing events for a loan, payments excluded",
           f"SELECT CAST(event_date AS STRING), event_type, milestone_type, CAST(followup_date AS STRING), "
           f"CAST(completed_date AS STRING), status, source, event_id, event_note FROM {t}.silver_loan_events "
           f"WHERE loan_id = {loan('lsi_get_event_history')} AND event_type <> 'PAYMENT_RECEIVED' "
           f"ORDER BY event_date, event_id"),
        fn("lsi_get_current_milestone", LOAN_PARAM,
           "milestone_type STRING, status STRING, event_date STRING, followup_date STRING, completed_date STRING, "
           "event_id STRING",
           "Current servicing milestone of a loan (highest configured sequence, RULE-MILESTONE-001)",
           f"SELECT milestone_type, status, CAST(event_date AS STRING), CAST(followup_date AS STRING), "
           f"CAST(completed_date AS STRING), event_id FROM {t}.gold_loan_milestone_state "
           f"WHERE loan_id = {loan('lsi_get_current_milestone')} AND is_current"),
        fn("lsi_check_followup_status", LOAN_PARAM,
           "current_milestone STRING, milestone_complete BOOLEAN, effective_followup_date STRING, "
           "days_to_followup STRING, days_overdue BIGINT, primary_condition STRING, secondary_conditions STRING, "
           "conditions_detail STRING, rule_ids STRING",
           "Effective follow-up date, days overdue, and the deterministic conditions detected for a loan",
           f"SELECT current_milestone, CAST(milestone_complete AS BOOLEAN), CAST(effective_followup_date AS STRING), "
           f"CAST(days_to_followup AS STRING), CAST(days_overdue AS BIGINT), primary_condition, "
           f"secondary_conditions, raw_conditions, condition_rule_ids FROM {t}.gold_loan_servicing_state "
           f"WHERE loan_id = {loan('lsi_check_followup_status')}"),
        fn("lsi_get_open_followups", LOAN_PARAM,
           "event_id STRING, event_type STRING, milestone_type STRING, event_date STRING, followup_date STRING, "
           "source STRING",
           "Open follow-up type events for a loan; two or more of the same type for a milestone is a duplicate risk",
           f"SELECT event_id, event_type, milestone_type, CAST(event_date AS STRING), CAST(followup_date AS STRING), "
           f"source FROM {t}.silver_loan_events WHERE loan_id = {loan('lsi_get_open_followups')} AND status = 'OPEN' "
           f"AND event_type IN ('FOLLOWUP', 'CONTACT', 'ESCALATION', 'INFO_REQUEST', 'DATA_REVIEW') "
           f"ORDER BY event_date"),
        fn("lsi_get_milestone_rule",
           "milestone_type STRING COMMENT 'Milestone code, for example TITLE_REVIEW'",
           "milestone_type STRING, milestone_sequence BIGINT, default_followup_days BIGINT, lookahead_days BIGINT, "
           "requires_followup BOOLEAN, overdue_action STRING, next_milestone_type STRING, severity BIGINT",
           "Configured synthetic milestone rule: follow-up days, look-ahead, overdue action, next milestone, severity",
           f"SELECT milestone_type, CAST(milestone_sequence AS BIGINT), CAST(default_followup_days AS BIGINT), "
           f"CAST(lookahead_days AS BIGINT), requires_followup, overdue_action, next_milestone_type, "
           f"CAST(severity AS BIGINT) FROM {t}.silver_milestone_rules "
           f"WHERE milestone_type = upper(lsi_get_milestone_rule.milestone_type) AND active"),
        fn("lsi_get_escalation_state", LOAN_PARAM,
           "escalation_state STRING, required_role STRING, health_segment STRING, escalation_reasons STRING",
           "Deterministic escalation state, required approver role, and the escalation rules that matched",
           f"SELECT escalation_state, required_role, health_segment, escalation_reasons "
           f"FROM {t}.gold_loan_servicing_state WHERE loan_id = {loan('lsi_get_escalation_state')}"),
        fn("lsi_get_attention_score", LOAN_PARAM,
           "attention_score BIGINT, priority STRING, score_drivers STRING, drivers_summary STRING, "
           "scoring_version STRING",
           "Deterministic attention score, priority, and score drivers. The agent must report, never recalculate, it",
           f"SELECT CAST(attention_score AS BIGINT), priority, score_drivers, top_drivers_text, scoring_version "
           f"FROM {t}.gold_loan_servicing_state WHERE loan_id = {loan('lsi_get_attention_score')}"),
        fn("lsi_get_allowed_actions", LOAN_PARAM,
           "allowed_actions STRING, default_action STRING, removed_actions STRING",
           "Actions the agent may recommend for this loan, the deterministic default, and actions removed and why",
           f"SELECT allowed_actions, default_action, removed_actions FROM {t}.gold_loan_servicing_state "
           f"WHERE loan_id = {loan('lsi_get_allowed_actions')}"),
        fn("lsi_check_pending_actions", LOAN_PARAM,
           "action_id STRING, action_type STRING, status STRING, followup_date STRING, origin STRING",
           "Approved or submitted actions still awaiting verification; a pending action means do not duplicate it",
           f"SELECT action_id, action_type, status, followup_date, 'APP' FROM {t}.ops_actions "
           f"WHERE loan_id = {loan('lsi_check_pending_actions')} AND status IN ('APPROVED', 'SUBMITTED') "
           f"UNION ALL SELECT action_id, action_type, 'SUBMITTED', CAST(followup_date AS STRING), 'HISTORY' "
           f"FROM {t}.gold_pending_actions WHERE loan_id = {loan('lsi_check_pending_actions')}"),
        fn("lsi_check_prior_rejections", LOAN_PARAM,
           "decided_at STRING, original_action STRING, reason STRING, reviewer_id STRING",
           "Prior reviewer rejections for a loan; recently rejected actions should not be re-proposed",
           f"SELECT CAST(decided_at AS STRING), original_action, reason, reviewer_id FROM {t}.gold_reviewer_decisions "
           f"WHERE loan_id = {loan('lsi_check_prior_rejections')} AND decision = 'REJECT' ORDER BY decided_at DESC"),
        fn("lsi_get_agent_proposals", LOAN_PARAM,
           "created_at STRING, recommended_action STRING, recommended_followup_date STRING, confidence STRING, "
           "status STRING, agent_mode STRING",
           "Existing agent proposals for a loan and their review status",
           f"SELECT created_at, recommended_action, recommended_followup_date, confidence, status, agent_mode "
           f"FROM {t}.ops_recommendations WHERE loan_id = {loan('lsi_get_agent_proposals')} "
           f"AND status <> 'SUPERSEDED' ORDER BY created_at DESC"),
        fn("lsi_get_ai_loan_insight", LOAN_PARAM,
           "ai_summary STRING, generated_at STRING, model_endpoint STRING",
           "AI Functions (ai_query) summary written by the backend workflow, if one exists",
           f"SELECT ai_summary, CAST(generated_at AS STRING), model_endpoint FROM {t}.gold_ai_loan_insights "
           f"WHERE loan_id = {loan('lsi_get_ai_loan_insight')}"),
        fn("lsi_priority_queue",
           "max_rows INT COMMENT 'Number of queue rows to return, for example 10'",
           "queue_rank BIGINT, priority STRING, loan_id STRING, primary_condition STRING, attention_score BIGINT, "
           "top_drivers STRING, recommended_action STRING, why_prioritized STRING",
           "Ranked servicing work queue across the portfolio",
           f"SELECT CAST(queue_rank AS BIGINT), priority, loan_id, primary_condition, CAST(attention_score AS BIGINT), "
           f"top_drivers_text, recommended_action, why_prioritized FROM {t}.gold_priority_queue "
           f"WHERE CAST(queue_rank AS INT) <= lsi_priority_queue.max_rows"),
        fn("lsi_portfolio_health_summary", "",
           "health_segment STRING, loan_count BIGINT, share_of_active DOUBLE",
           "Portfolio health segments: Healthy, Watch, Action Required, Critical",
           f"SELECT health_segment, CAST(loan_count AS BIGINT), CAST(share_of_active AS DOUBLE) "
           f"FROM {t}.gold_portfolio_health"),
        fn("lsi_specialist_workload", "",
           "specialist_name STRING, assigned_loans BIGINT, need_attention BIGINT, critical BIGINT, high BIGINT",
           "Per-specialist assigned loans, loans needing attention, critical and high counts",
           f"SELECT specialist_name, CAST(assigned_loans AS BIGINT), CAST(need_attention AS BIGINT), "
           f"CAST(critical AS BIGINT), CAST(high AS BIGINT) FROM {t}.v_lsi_specialist_workload"),
        fn("lsi_get_failed_verifications", "",
           "action_id STRING, loan_id STRING, action_type STRING, verification_status STRING, detail STRING",
           "Approved actions that failed verification against the servicing system",
           f"SELECT action_id, loan_id, action_type, verification_status, detail "
           f"FROM {t}.v_lsi_verification_failures"),
    ]
