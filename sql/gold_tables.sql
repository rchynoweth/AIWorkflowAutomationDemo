-- Loan Servicing Intelligence: Gold tables (SYNTHETIC DEMONSTRATION DATA).
-- Reference DDL. The pipeline (src/pipeline.py) writes these tables with overwriteSchema; ${catalog}/${schema} are placeholders.
-- List/dict columns are JSON-encoded STRING columns.

CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`gold_loan_servicing_state` (
  `loan_id` STRING,
  `borrower_display_name` STRING,
  `property_state` STRING,
  `property_county` STRING,
  `portfolio_id` STRING,
  `current_balance` DOUBLE,
  `payment_status` STRING,
  `days_delinquent` BIGINT,
  `loan_status` STRING,
  `foreclosure_status` STRING,
  `is_active` BOOLEAN,
  `assigned_specialist_id` STRING,
  `specialist_name` STRING,
  `assigned_party_id` STRING,
  `party_name` STRING,
  `party_type` STRING,
  `current_milestone` STRING,
  `milestone_sequence` DOUBLE,
  `milestone_status` STRING,
  `milestone_event_id` STRING,
  `milestone_complete` BOOLEAN,
  `milestone_severity` DOUBLE,
  `effective_followup_date` STRING,
  `days_to_followup` DOUBLE,
  `days_overdue` BIGINT,
  `raw_conditions` STRING,
  `primary_condition` STRING,
  `secondary_conditions` STRING,
  `condition_rule_ids` STRING,
  `escalation_state` STRING,
  `escalation_reasons` STRING,
  `required_role` STRING,
  `health_segment` STRING,
  `needs_attention` BOOLEAN,
  `allowed_actions` STRING,
  `default_action` STRING,
  `removed_actions` STRING,
  `attention_score` BIGINT,
  `priority` STRING,
  `score_drivers` STRING,
  `top_drivers_text` STRING,
  `pending_action_id` STRING,
  `latest_action_id` STRING,
  `latest_verification_status` STRING,
  `failed_action_count` BIGINT,
  `prior_rejected_actions` STRING,
  `state_fingerprint` STRING,
  `processing_date` STRING,
  `rule_version` STRING,
  `scoring_version` STRING,
  `calculated_at` STRING
) USING DELTA COMMENT 'gold_loan_servicing_state (synthetic)';

CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`gold_loan_milestone_state` (
  `loan_id` STRING,
  `milestone_type` STRING,
  `milestone_sequence` BIGINT,
  `event_id` STRING,
  `event_date` STRING,
  `followup_date` STRING,
  `completed_date` STRING,
  `status` STRING,
  `is_current` BOOLEAN,
  `is_complete` BOOLEAN,
  `dq_issues` STRING
) USING DELTA COMMENT 'gold_loan_milestone_state (synthetic)';

CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`gold_attention_candidates` (
  `loan_id` STRING,
  `borrower_display_name` STRING,
  `property_state` STRING,
  `property_county` STRING,
  `portfolio_id` STRING,
  `current_balance` DOUBLE,
  `payment_status` STRING,
  `days_delinquent` BIGINT,
  `loan_status` STRING,
  `foreclosure_status` STRING,
  `is_active` BOOLEAN,
  `assigned_specialist_id` STRING,
  `specialist_name` STRING,
  `assigned_party_id` STRING,
  `party_name` STRING,
  `party_type` STRING,
  `current_milestone` STRING,
  `milestone_sequence` DOUBLE,
  `milestone_status` STRING,
  `milestone_event_id` STRING,
  `milestone_complete` BOOLEAN,
  `milestone_severity` DOUBLE,
  `effective_followup_date` STRING,
  `days_to_followup` DOUBLE,
  `days_overdue` BIGINT,
  `raw_conditions` STRING,
  `primary_condition` STRING,
  `secondary_conditions` STRING,
  `condition_rule_ids` STRING,
  `escalation_state` STRING,
  `escalation_reasons` STRING,
  `required_role` STRING,
  `health_segment` STRING,
  `needs_attention` BOOLEAN,
  `allowed_actions` STRING,
  `default_action` STRING,
  `removed_actions` STRING,
  `attention_score` BIGINT,
  `priority` STRING,
  `score_drivers` STRING,
  `top_drivers_text` STRING,
  `pending_action_id` STRING,
  `latest_action_id` STRING,
  `latest_verification_status` STRING,
  `failed_action_count` BIGINT,
  `prior_rejected_actions` STRING,
  `state_fingerprint` STRING,
  `processing_date` STRING,
  `rule_version` STRING,
  `scoring_version` STRING,
  `calculated_at` STRING
) USING DELTA COMMENT 'gold_attention_candidates (synthetic)';

CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`gold_priority_queue` (
  `priority` STRING,
  `loan_id` STRING,
  `borrower_display_name` STRING,
  `primary_condition` STRING,
  `secondary_conditions` STRING,
  `escalation_state` STRING,
  `severity` DOUBLE,
  `current_milestone` STRING,
  `effective_followup_date` STRING,
  `days_overdue` BIGINT,
  `attention_score` BIGINT,
  `score_drivers` STRING,
  `top_drivers_text` STRING,
  `recommended_action` STRING,
  `recommendation_id` STRING,
  `confidence` STRING,
  `specialist_name` STRING,
  `review_status` STRING,
  `why_prioritized` STRING,
  `queue_rank` BIGINT
) USING DELTA COMMENT 'gold_priority_queue (synthetic)';

CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`gold_portfolio_health` (
  `health_segment` STRING,
  `loan_count` BIGINT,
  `share_of_active` DOUBLE,
  `processing_date` STRING
) USING DELTA COMMENT 'gold_portfolio_health (synthetic)';

CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`gold_portfolio_briefing_facts` (
  `fact_group` STRING,
  `fact_name` STRING,
  `fact_value` STRING,
  `processing_date` STRING
) USING DELTA COMMENT 'gold_portfolio_briefing_facts (synthetic)';

CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`gold_action_verification` (
  `action_id` STRING,
  `loan_id` STRING,
  `matched_event_ids` STRING,
  `differences` STRING,
  `rule_id` STRING,
  `detail` STRING,
  `verification_status` STRING,
  `action_type` STRING,
  `event_type` STRING,
  `action_status` STRING,
  `submitted_at` STRING,
  `action_event_date` STRING,
  `followup_date` STRING,
  `evaluated_on` STRING
) USING DELTA COMMENT 'gold_action_verification (synthetic)';

CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`gold_pending_actions` (
  `action_id` STRING,
  `loan_id` STRING,
  `matched_event_ids` STRING,
  `differences` STRING,
  `rule_id` STRING,
  `detail` STRING,
  `verification_status` STRING,
  `action_type` STRING,
  `event_type` STRING,
  `action_status` STRING,
  `submitted_at` STRING,
  `action_event_date` STRING,
  `followup_date` STRING,
  `evaluated_on` STRING
) USING DELTA COMMENT 'gold_pending_actions (synthetic)';

CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`gold_agent_evaluation` (
  `evaluation_id` STRING, `scenario_id` STRING, `loan_id` STRING, `check_type` STRING, `metric` STRING,
  `expected` STRING, `actual` STRING, `passed` BOOLEAN, `processing_date` STRING
) USING DELTA COMMENT 'Rule and agent evaluation results (synthetic metrics)';

-- gold_agent_recommendations, gold_reviewer_decisions, gold_agent_activity: views in portfolio_views.sql.
