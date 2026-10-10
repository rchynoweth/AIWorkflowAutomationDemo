-- Loan Servicing Intelligence: evaluation views (SYNTHETIC METRICS).

CREATE OR REPLACE VIEW `${catalog}`.`${schema}`.`v_lsi_evaluation_latest` AS
WITH latest AS (
  SELECT evaluation_id FROM `${catalog}`.`${schema}`.`gold_agent_evaluation`
  ORDER BY evaluation_id DESC LIMIT 1
)
SELECT e.check_type, e.metric, COUNT(*) AS checks, SUM(CASE WHEN e.passed THEN 1 ELSE 0 END) AS passed,
       ROUND(AVG(CASE WHEN e.passed THEN 1.0 ELSE 0.0 END), 4) AS pass_rate, MAX(e.evaluation_id) AS evaluation_id
FROM `${catalog}`.`${schema}`.`gold_agent_evaluation` e JOIN latest l ON e.evaluation_id = l.evaluation_id
GROUP BY e.check_type, e.metric;
