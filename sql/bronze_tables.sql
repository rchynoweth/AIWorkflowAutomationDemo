-- Loan Servicing Intelligence: Bronze tables (SYNTHETIC DEMONSTRATION DATA).
-- Reference DDL. The pipeline (src/pipeline.py) writes these tables with overwriteSchema; ${catalog}/${schema} are placeholders.

CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`bronze_loans` (
  `loan_id` STRING,
  `borrower_display_name` STRING,
  `property_address` STRING,
  `property_city` STRING,
  `property_state` STRING,
  `property_postal_code` STRING,
  `property_county` STRING,
  `original_balance` STRING,
  `current_balance` STRING,
  `loan_status` STRING,
  `payment_status` STRING,
  `days_delinquent` STRING,
  `foreclosure_status` STRING,
  `assigned_specialist_id` STRING,
  `assigned_attorney_vendor_id` STRING,
  `boarding_date` STRING,
  `portfolio_id` STRING,
  `synthetic_data` STRING,
  `source_file` STRING,
  `ingested_at` TIMESTAMP,
  `batch_id` STRING,
  `record_hash` STRING,
  `source_row_number` INT
) USING DELTA COMMENT 'Raw loans.csv rows as strings with lineage (synthetic)';

CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`bronze_loan_events` (
  `event_id` STRING,
  `loan_id` STRING,
  `event_type` STRING,
  `milestone_type` STRING,
  `event_date` STRING,
  `followup_date` STRING,
  `completed_date` STRING,
  `status` STRING,
  `event_note` STRING,
  `source` STRING,
  `created_at` STRING,
  `updated_at` STRING,
  `synthetic_data` STRING,
  `source_file` STRING,
  `ingested_at` TIMESTAMP,
  `batch_id` STRING,
  `record_hash` STRING,
  `source_row_number` INT
) USING DELTA COMMENT 'Raw loan_events.csv rows as strings with lineage (synthetic)';

CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`bronze_milestone_rules` (
  `milestone_type` STRING,
  `milestone_sequence` STRING,
  `default_followup_days` STRING,
  `lookahead_days` STRING,
  `requires_followup` STRING,
  `overdue_action` STRING,
  `next_milestone_type` STRING,
  `severity` STRING,
  `active` STRING,
  `synthetic_data` STRING,
  `source_file` STRING,
  `ingested_at` TIMESTAMP,
  `batch_id` STRING,
  `record_hash` STRING,
  `source_row_number` INT
) USING DELTA COMMENT 'Raw milestone_rules.csv rows as strings with lineage (synthetic)';

CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`bronze_servicing_specialists` (
  `specialist_id` STRING,
  `display_name` STRING,
  `team` STRING,
  `active` STRING,
  `synthetic_data` STRING,
  `source_file` STRING,
  `ingested_at` TIMESTAMP,
  `batch_id` STRING,
  `record_hash` STRING,
  `source_row_number` INT
) USING DELTA COMMENT 'Raw servicing_specialists.csv rows as strings with lineage (synthetic)';

CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`bronze_attorneys_vendors` (
  `party_id` STRING,
  `display_name` STRING,
  `party_type` STRING,
  `state` STRING,
  `active` STRING,
  `synthetic_data` STRING,
  `source_file` STRING,
  `ingested_at` TIMESTAMP,
  `batch_id` STRING,
  `record_hash` STRING,
  `source_row_number` INT
) USING DELTA COMMENT 'Raw attorneys_vendors.csv rows as strings with lineage (synthetic)';

CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`bronze_servicing_action_history` (
  `action_id` STRING,
  `loan_id` STRING,
  `recommendation_id` STRING,
  `action_type` STRING,
  `event_type` STRING,
  `event_date` STRING,
  `followup_date` STRING,
  `status` STRING,
  `submitted_at` STRING,
  `verified_at` STRING,
  `failure_reason` STRING,
  `synthetic_data` STRING,
  `source_file` STRING,
  `ingested_at` TIMESTAMP,
  `batch_id` STRING,
  `record_hash` STRING,
  `source_row_number` INT
) USING DELTA COMMENT 'Raw servicing_action_history.csv rows as strings with lineage (synthetic)';

CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`bronze_reviewer_decisions` (
  `decision_id` STRING,
  `recommendation_id` STRING,
  `loan_id` STRING,
  `reviewer_id` STRING,
  `decision` STRING,
  `original_action` STRING,
  `final_action` STRING,
  `original_followup_date` STRING,
  `final_followup_date` STRING,
  `original_note` STRING,
  `final_note` STRING,
  `reason` STRING,
  `decided_at` STRING,
  `synthetic_data` STRING,
  `source_file` STRING,
  `ingested_at` TIMESTAMP,
  `batch_id` STRING,
  `record_hash` STRING,
  `source_row_number` INT
) USING DELTA COMMENT 'Raw reviewer_decisions.csv rows as strings with lineage (synthetic)';
