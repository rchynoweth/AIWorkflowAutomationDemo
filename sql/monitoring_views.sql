-- Loan Servicing Intelligence: monitoring views (SYNTHETIC DEMONSTRATION DATA).

CREATE OR REPLACE VIEW `${catalog}`.`${schema}`.`v_lsi_overdue_loans` AS
SELECT loan_id, borrower_display_name, portfolio_id, current_milestone, effective_followup_date, days_overdue,
       attention_score, priority, escalation_state, specialist_name
FROM `${catalog}`.`${schema}`.`gold_loan_servicing_state`
WHERE is_active AND raw_conditions LIKE '%"OVERDUE"%'
ORDER BY days_overdue DESC;

CREATE OR REPLACE VIEW `${catalog}`.`${schema}`.`v_lsi_verification_failures` AS
SELECT action_id, loan_id, action_type, verification_status, detail, differences, evaluated_on
FROM `${catalog}`.`${schema}`.`gold_action_verification`
WHERE verification_status IN ('FAILED', 'NOT_FOUND', 'MISMATCH', 'DUPLICATE');

CREATE OR REPLACE VIEW `${catalog}`.`${schema}`.`v_lsi_specialist_workload` AS
SELECT specialist_name,
       COUNT(*) AS assigned_loans,
       SUM(CASE WHEN needs_attention THEN 1 ELSE 0 END) AS need_attention,
       SUM(CASE WHEN priority = 'CRITICAL' THEN 1 ELSE 0 END) AS critical,
       SUM(CASE WHEN priority = 'HIGH' THEN 1 ELSE 0 END) AS high
FROM `${catalog}`.`${schema}`.`gold_loan_servicing_state`
WHERE is_active
GROUP BY specialist_name;
