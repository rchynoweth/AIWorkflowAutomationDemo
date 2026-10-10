-- Loan Servicing Intelligence: Silver tables (SYNTHETIC DEMONSTRATION DATA).
-- Reference DDL. The pipeline (src/pipeline.py) writes these tables with overwriteSchema; ${catalog}/${schema} are placeholders.

CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`silver_loans` (
  `loan_id` STRING,
  `borrower_display_name` STRING,
  `property_address` STRING,
  `property_city` STRING,
  `property_state` STRING,
  `property_postal_code` STRING,
  `property_county` STRING,
  `original_balance` DOUBLE,
  `current_balance` DOUBLE,
  `loan_status` STRING,
  `payment_status` STRING,
  `days_delinquent` BIGINT,
  `foreclosure_status` STRING,
  `assigned_specialist_id` STRING,
  `assigned_attorney_vendor_id` STRING,
  `boarding_date` DATE,
  `portfolio_id` STRING,
  `synthetic_data` BOOLEAN,
  `dq_issues` STRING,
  `specialist_name` STRING,
  `specialist_active` BOOLEAN,
  `team` STRING,
  `party_name` STRING,
  `party_type` STRING,
  `party_active` BOOLEAN,
  `is_active` BOOLEAN
) USING DELTA COMMENT 'Standardized loans (synthetic)';

CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`silver_loan_events` (
  `event_id` STRING,
  `loan_id` STRING,
  `event_type` STRING,
  `milestone_type` STRING,
  `event_date` DATE,
  `followup_date` DATE,
  `completed_date` DATE,
  `status` STRING,
  `event_note` STRING,
  `source` STRING,
  `created_at` TIMESTAMP,
  `updated_at` TIMESTAMP,
  `synthetic_data` BOOLEAN,
  `dq_issues` STRING,
  `milestone_sequence` BIGINT,
  `is_open` BOOLEAN,
  `is_followup_type` BOOLEAN,
  `event_sequence` BIGINT
) USING DELTA COMMENT 'Standardized loan_events (synthetic)';

CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`silver_milestone_rules` (
  `milestone_type` STRING,
  `milestone_sequence` BIGINT,
  `default_followup_days` BIGINT,
  `lookahead_days` BIGINT,
  `requires_followup` BOOLEAN,
  `overdue_action` STRING,
  `next_milestone_type` STRING,
  `severity` BIGINT,
  `active` BOOLEAN,
  `synthetic_data` BOOLEAN,
  `dq_issues` STRING
) USING DELTA COMMENT 'Standardized milestone_rules (synthetic)';

CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`silver_servicing_specialists` (
  `specialist_id` STRING,
  `display_name` STRING,
  `team` STRING,
  `active` BOOLEAN,
  `synthetic_data` BOOLEAN
) USING DELTA COMMENT 'Standardized servicing_specialists (synthetic)';

CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`silver_attorneys_vendors` (
  `party_id` STRING,
  `display_name` STRING,
  `party_type` STRING,
  `state` STRING,
  `active` BOOLEAN,
  `synthetic_data` BOOLEAN
) USING DELTA COMMENT 'Standardized attorneys_vendors (synthetic)';

CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`silver_active_foreclosures` (
  `loan_id` STRING,
  `portfolio_id` STRING,
  `property_state` STRING,
  `foreclosure_status` STRING,
  `days_delinquent` BIGINT,
  `assigned_specialist_id` STRING,
  `assigned_attorney_vendor_id` STRING,
  `current_milestone` STRING,
  `milestone_opened` DATE,
  `milestone_followup_date` DATE,
  `milestone_status` STRING
) USING DELTA COMMENT 'Standardized active_foreclosures (synthetic)';

CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`silver_servicing_action_history` (
  `action_id` STRING,
  `loan_id` STRING,
  `recommendation_id` STRING,
  `action_type` STRING,
  `event_type` STRING,
  `event_date` DATE,
  `followup_date` DATE,
  `status` STRING,
  `submitted_at` TIMESTAMP,
  `verified_at` TIMESTAMP,
  `failure_reason` STRING,
  `synthetic_data` BOOLEAN,
  `milestone_type` STRING,
  `dq_issues` STRING
) USING DELTA COMMENT 'Standardized servicing_action_history (synthetic)';

CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`silver_reviewer_decisions` (
  `decision_id` STRING,
  `recommendation_id` STRING,
  `loan_id` STRING,
  `reviewer_id` STRING,
  `decision` STRING,
  `original_action` STRING,
  `final_action` STRING,
  `original_followup_date` DATE,
  `final_followup_date` DATE,
  `original_note` STRING,
  `final_note` STRING,
  `reason` STRING,
  `decided_at` TIMESTAMP,
  `synthetic_data` BOOLEAN,
  `dq_issues` STRING
) USING DELTA COMMENT 'Standardized reviewer_decisions (synthetic)';
