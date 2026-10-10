"""Unity Catalog SQL table functions exposing read-only structured agent tools over Gold tables.

Usable from SQL, Genie, or a Unity Catalog MCP server. Registered by notebooks/05_register_agent_tools.py.
"""
from __future__ import annotations


def uc_function_statements(catalog: str, schema: str) -> list[tuple[str, str]]:
    t = f"`{catalog}`.`{schema}`"

    def fn(name: str, params: str, returns: str, comment: str, body: str) -> tuple[str, str]:
        return name, (f"CREATE OR REPLACE FUNCTION {t}.`{name}`({params}) RETURNS TABLE ({returns}) "
                      f"COMMENT '{comment} (synthetic demonstration)' RETURN {body}")

    return [
        fn("lsi_get_loan_context", "p_loan_id STRING",
           "loan_id STRING, borrower_display_name STRING, portfolio_id STRING, property_state STRING, "
           "current_balance DOUBLE, payment_status STRING, days_delinquent BIGINT, loan_status STRING, "
           "foreclosure_status STRING, specialist_name STRING, party_name STRING, party_type STRING",
           "Loan attributes and assigned parties",
           f"SELECT loan_id, borrower_display_name, portfolio_id, property_state, CAST(current_balance AS DOUBLE), "
           f"payment_status, CAST(days_delinquent AS BIGINT), loan_status, foreclosure_status, specialist_name, "
           f"party_name, party_type FROM {t}.gold_loan_servicing_state WHERE loan_id = upper(p_loan_id)"),
        fn("lsi_get_event_history", "p_loan_id STRING",
           "event_id STRING, event_type STRING, milestone_type STRING, event_date DATE, followup_date DATE, "
           "completed_date DATE, status STRING, source STRING, event_note STRING",
           "Chronological servicing events (payments excluded)",
           f"SELECT event_id, event_type, milestone_type, CAST(event_date AS DATE), CAST(followup_date AS DATE), "
           f"CAST(completed_date AS DATE), status, source, event_note FROM {t}.silver_loan_events "
           f"WHERE loan_id = upper(p_loan_id) AND event_type <> 'PAYMENT_RECEIVED'"),
        fn("lsi_get_current_milestone", "p_loan_id STRING",
           "loan_id STRING, milestone_type STRING, event_id STRING, event_date STRING, followup_date STRING, "
           "completed_date STRING, status STRING",
           "Current milestone per RULE-MILESTONE-001",
           f"SELECT loan_id, milestone_type, event_id, CAST(event_date AS STRING), CAST(followup_date AS STRING), "
           f"CAST(completed_date AS STRING), status FROM {t}.gold_loan_milestone_state "
           f"WHERE loan_id = upper(p_loan_id) AND is_current"),
        fn("lsi_check_followup_status", "p_loan_id STRING",
           "loan_id STRING, current_milestone STRING, effective_followup_date STRING, days_to_followup STRING, "
           "days_overdue BIGINT, primary_condition STRING, secondary_conditions STRING, condition_rule_ids STRING",
           "Effective follow-up and condition facts",
           f"SELECT loan_id, current_milestone, CAST(effective_followup_date AS STRING), "
           f"CAST(days_to_followup AS STRING), CAST(days_overdue AS BIGINT), primary_condition, "
           f"secondary_conditions, condition_rule_ids FROM {t}.gold_loan_servicing_state "
           f"WHERE loan_id = upper(p_loan_id)"),
        fn("lsi_get_milestone_rule", "p_milestone_type STRING",
           "milestone_type STRING, milestone_sequence BIGINT, default_followup_days BIGINT, lookahead_days BIGINT, "
           "requires_followup BOOLEAN, overdue_action STRING, next_milestone_type STRING, severity BIGINT",
           "Active synthetic milestone rule",
           f"SELECT milestone_type, CAST(milestone_sequence AS BIGINT), CAST(default_followup_days AS BIGINT), "
           f"CAST(lookahead_days AS BIGINT), requires_followup, overdue_action, next_milestone_type, "
           f"CAST(severity AS BIGINT) FROM {t}.silver_milestone_rules "
           f"WHERE milestone_type = upper(p_milestone_type) AND active"),
        fn("lsi_portfolio_health_summary", "",
           "health_segment STRING, loan_count BIGINT, share_of_active DOUBLE",
           "Portfolio health segments",
           f"SELECT health_segment, CAST(loan_count AS BIGINT), CAST(share_of_active AS DOUBLE) "
           f"FROM {t}.gold_portfolio_health"),
        fn("lsi_priority_queue", "p_limit INT",
           "queue_rank BIGINT, priority STRING, loan_id STRING, primary_condition STRING, attention_score BIGINT, "
           "top_drivers_text STRING, recommended_action STRING, why_prioritized STRING",
           "Ranked attention queue",
           f"SELECT CAST(queue_rank AS BIGINT), priority, loan_id, primary_condition, CAST(attention_score AS BIGINT), "
           f"top_drivers_text, recommended_action, why_prioritized FROM {t}.gold_priority_queue "
           f"WHERE queue_rank <= p_limit"),
        fn("lsi_specialist_workload", "",
           "specialist_name STRING, assigned_loans BIGINT, need_attention BIGINT, critical BIGINT, high BIGINT",
           "Per-specialist workload",
           f"SELECT specialist_name, CAST(assigned_loans AS BIGINT), CAST(need_attention AS BIGINT), "
           f"CAST(critical AS BIGINT), CAST(high AS BIGINT) FROM {t}.v_lsi_specialist_workload"),
    ]
