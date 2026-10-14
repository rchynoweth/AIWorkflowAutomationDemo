# Databricks notebook source
# MAGIC %md
# MAGIC # 04 · Gold: the servicing rules, in SQL
# MAGIC
# MAGIC Objective checks stay **deterministic**: which milestone each loan is on, whether its follow-up is overdue,
# MAGIC how urgent it is, and which actions are allowed. Every rule is plain SQL in this notebook, and the
# MAGIC condition settings live in a table you can edit. The AI steps that follow (notebooks 07 and 08) build on
# MAGIC these facts and never recalculate them.
# MAGIC
# MAGIC | Output | What it holds |
# MAGIC |---|---|
# MAGIC | `rule_conditions` | The conditions, their precedence, points, and allowed actions |
# MAGIC | `gold_action_verification` | Did each approved action land in the servicing system? |
# MAGIC | `gold_loan_state` | One row per loan: milestone, follow-up, conditions, score, priority, allowed actions |

# COMMAND ----------

dbutils.widgets.text("catalog", "main")
dbutils.widgets.text("schema", "loan_servicing_intelligence")
spark.sql(f"USE {dbutils.widgets.get('catalog')}.{dbutils.widgets.get('schema')}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. The rules are a table
# MAGIC Each condition has a **precedence** (when a loan has several, the lowest number is its primary condition),
# MAGIC **points** toward the attention score, and the **actions allowed** for it, in order of preference.
# MAGIC `OVERDUE_ACTION` means "the overdue action configured for the loan's current milestone".

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE TABLE rule_conditions
# MAGIC COMMENT 'Servicing conditions: precedence, score points, allowed actions - SYNTHETIC, editable' AS
# MAGIC SELECT * FROM VALUES
# MAGIC   ('VERIFICATION_FAILURE', 1,  40, array('RETRY_FAILED_ACTION', 'REVIEW_DATA_EXCEPTION'),        'An approved action did not land in the servicing system as approved'),
# MAGIC   ('DATA_EXCEPTION',       2,  25, array('REVIEW_DATA_EXCEPTION', 'REQUEST_INFORMATION'),        'A required rule, date, or assigned party is missing or conflicting'),
# MAGIC   ('ALREADY_ACTIONED',     3,   5, array('NO_ACTION'),                                           'Needs action, but an approved action is already on its way'),
# MAGIC   ('DUPLICATE_RISK',       4,  20, array('REVIEW_DATA_EXCEPTION', 'NO_ACTION'),                  'Two or more open follow-ups of the same type for the current milestone'),
# MAGIC   ('OVERDUE',              5,  30, array('OVERDUE_ACTION', 'CREATE_FOLLOWUP', 'REQUEST_INFORMATION'), 'Follow-up date has passed and the milestone is not complete'),
# MAGIC   ('MISSING_FOLLOWUP',     6,  25, array('CREATE_FOLLOWUP', 'REQUEST_INFORMATION'),              'The milestone requires a follow-up date and has none'),
# MAGIC   ('DUE',                  7,  20, array('OVERDUE_ACTION', 'CREATE_FOLLOWUP', 'NO_ACTION'),      'Follow-up is due today'),
# MAGIC   ('COMPLETED_NEEDS_NEXT', 8,  20, array('CREATE_NEXT_MILESTONE', 'REQUEST_INFORMATION'),        'Milestone complete, but the next milestone has not been opened'),
# MAGIC   ('PENDING_REVIEW',       9,  10, array('NO_ACTION'),                                           'A reviewer deferred the last recommendation'),
# MAGIC   ('PENDING_ACTION',      10,   5, array('NO_ACTION'),                                           'An approved action is waiting to be verified'),
# MAGIC   ('UPCOMING',            11,   8, array('NO_ACTION', 'OVERDUE_ACTION'),                         'Follow-up falls inside the milestone look-ahead window'),
# MAGIC   ('COMPLETED',           12,   0, array('NO_ACTION'),                                           'Final milestone complete'),
# MAGIC   ('NO_ACTION',           13,   0, array('NO_ACTION'),                                           'On track')
# MAGIC AS t(condition, precedence, points, allowed_actions, description)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Verify approved actions against the servicing system
# MAGIC When an action is approved, the servicing system creates an event that carries `[ref <action_id>]` in its
# MAGIC note. We look for that event in the latest export:
# MAGIC no event yet (within 2 days) = **PENDING**, no event after that = **NOT_FOUND**, two events = **DUPLICATE**,
# MAGIC different follow-up date = **MISMATCH**, otherwise **VERIFIED**.

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE TABLE gold_action_verification
# MAGIC COMMENT 'Approved actions checked against the servicing system export - SYNTHETIC DEMONSTRATION DATA' AS
# MAGIC WITH actions AS (
# MAGIC   SELECT action_id, loan_id, action_type, event_type, followup_date, CAST(submitted_at AS DATE) AS submitted_date,
# MAGIC          'History' AS origin
# MAGIC   FROM silver_servicing_action_history
# MAGIC   UNION ALL
# MAGIC   SELECT action_id, loan_id, action_type, event_type, followup_date, CAST(submitted_at AS DATE), 'App'
# MAGIC   FROM app_actions
# MAGIC ),
# MAGIC landed AS (
# MAGIC   SELECT a.action_id, count(e.event_id) AS events_found, max(e.followup_date) AS landed_followup_date
# MAGIC   FROM actions a
# MAGIC   LEFT JOIN silver_loan_events e
# MAGIC     ON e.loan_id = a.loan_id AND e.event_note LIKE concat('%[ref ', a.action_id, ']%')
# MAGIC   GROUP BY a.action_id
# MAGIC )
# MAGIC SELECT
# MAGIC   a.*,
# MAGIC   l.events_found,
# MAGIC   l.landed_followup_date,
# MAGIC   CASE
# MAGIC     WHEN l.events_found = 0 AND a.submitted_date >= current_date() - 2 THEN 'PENDING'
# MAGIC     WHEN l.events_found = 0                                             THEN 'NOT_FOUND'
# MAGIC     WHEN l.events_found > 1                                             THEN 'DUPLICATE'
# MAGIC     WHEN l.landed_followup_date <> a.followup_date                      THEN 'MISMATCH'
# MAGIC     ELSE 'VERIFIED'
# MAGIC   END AS verification_status
# MAGIC FROM actions a
# MAGIC JOIN landed l USING (action_id)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Facts for every loan
# MAGIC - **Current milestone** (RULE-MILESTONE-001): the milestone event with the highest configured sequence.
# MAGIC - **Follow-up date** (RULE-FOLLOWUP-001): the latest open follow-up for that milestone, otherwise the
# MAGIC   milestone's own follow-up date.
# MAGIC - **Next milestone**: from the milestone rule, and whether it has been opened yet.
# MAGIC - Latest approved action, prior rejections, deferrals, and whether the right attorney or vendor is assigned.

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE TEMP VIEW loan_facts AS
# MAGIC WITH current_milestone AS (
# MAGIC   SELECT loan_id, event_id AS milestone_event_id, milestone_type AS current_milestone, status AS milestone_status,
# MAGIC          event_date AS milestone_date, followup_date AS milestone_followup_date, completed_date AS milestone_completed_date
# MAGIC   FROM silver_loan_events
# MAGIC   WHERE event_type = 'MILESTONE' AND status <> 'CANCELLED'
# MAGIC   QUALIFY row_number() OVER (PARTITION BY loan_id ORDER BY milestone_sequence DESC, event_date DESC, created_at DESC) = 1
# MAGIC ),
# MAGIC open_followups AS (   -- open follow-up type events for the current milestone
# MAGIC   SELECT e.loan_id, e.event_type, e.followup_date, e.event_sequence,
# MAGIC          count(*) OVER (PARTITION BY e.loan_id, e.event_type) AS open_of_same_type
# MAGIC   FROM silver_loan_events e
# MAGIC   JOIN current_milestone m ON m.loan_id = e.loan_id AND m.current_milestone = e.milestone_type
# MAGIC   WHERE e.is_followup_type AND e.status = 'OPEN'
# MAGIC ),
# MAGIC followups AS (
# MAGIC   SELECT loan_id,
# MAGIC          max_by(followup_date, event_sequence) FILTER (WHERE followup_date IS NOT NULL) AS latest_open_followup,
# MAGIC          max(open_of_same_type) AS max_open_of_same_type
# MAGIC   FROM open_followups
# MAGIC   GROUP BY loan_id
# MAGIC ),
# MAGIC milestones_opened AS (
# MAGIC   SELECT loan_id, collect_set(milestone_type) AS milestones FROM silver_loan_events GROUP BY loan_id
# MAGIC ),
# MAGIC latest_action AS (    -- the most recent approved action in the last 30 days
# MAGIC   SELECT loan_id, action_id AS latest_action_id, action_type AS latest_action_type,
# MAGIC          verification_status AS latest_action_status,
# MAGIC          sum(CASE WHEN verification_status IN ('NOT_FOUND', 'MISMATCH', 'DUPLICATE') THEN 1 ELSE 0 END)
# MAGIC            OVER (PARTITION BY loan_id) AS failed_actions
# MAGIC   FROM gold_action_verification
# MAGIC   WHERE submitted_date >= current_date() - 30
# MAGIC   QUALIFY row_number() OVER (PARTITION BY loan_id ORDER BY submitted_date DESC, action_id DESC) = 1
# MAGIC ),
# MAGIC decisions AS (
# MAGIC   SELECT loan_id,
# MAGIC          collect_set(original_action) FILTER (WHERE decision = 'REJECT' AND decided_at >= current_date() - 14)
# MAGIC            AS rejected_actions,
# MAGIC          max_by(decision, decided_at) = 'DEFER' AND max(decided_at) >= current_date() - 14 AS deferred
# MAGIC   FROM silver_reviewer_decisions
# MAGIC   GROUP BY loan_id
# MAGIC )
# MAGIC SELECT
# MAGIC   l.loan_id, l.borrower_display_name, l.portfolio_id, l.property_state, l.property_county, l.current_balance,
# MAGIC   l.payment_status, l.days_delinquent, l.loan_status, l.foreclosure_status, l.is_active,
# MAGIC   l.specialist_name, l.party_name, l.party_type,
# MAGIC   m.milestone_event_id, m.current_milestone, m.milestone_status, m.milestone_date, m.milestone_followup_date,
# MAGIC   m.milestone_completed_date,
# MAGIC   m.loan_id IS NOT NULL AS has_track,
# MAGIC   r.milestone_type IS NOT NULL AS rule_found,
# MAGIC   r.severity, r.lookahead_days, r.requires_followup, r.default_followup_days,
# MAGIC   IF(coalesce(r.overdue_action, 'NO_ACTION') = 'NO_ACTION', 'CREATE_FOLLOWUP', r.overdue_action) AS overdue_action,
# MAGIC   r.next_milestone_type AS next_milestone,
# MAGIC   nr.default_followup_days AS next_milestone_followup_days,
# MAGIC   array_contains(o.milestones, r.next_milestone_type) AS next_milestone_opened,
# MAGIC   m.milestone_status = 'COMPLETED' AND m.milestone_completed_date IS NOT NULL AS milestone_complete,
# MAGIC   m.milestone_completed_date < m.milestone_date
# MAGIC     OR (m.milestone_status = 'COMPLETED' AND m.milestone_completed_date IS NULL) AS conflicting_dates,
# MAGIC   coalesce(f.latest_open_followup, m.milestone_followup_date) AS followup_date,
# MAGIC   coalesce(f.max_open_of_same_type, 0) AS max_open_of_same_type,
# MAGIC   CASE r.overdue_action WHEN 'CONTACT_ATTORNEY' THEN 'ATTORNEY' WHEN 'CONTACT_SERVICING_VENDOR' THEN 'VENDOR' END
# MAGIC     AS required_party_type,
# MAGIC   coalesce(p.active AND p.party_type = 'ATTORNEY', false) AS has_attorney,
# MAGIC   coalesce(p.active AND p.party_type = 'VENDOR', false) AS has_vendor,
# MAGIC   a.latest_action_id, a.latest_action_type, a.latest_action_status, coalesce(a.failed_actions, 0) AS failed_actions,
# MAGIC   coalesce(d.rejected_actions, array()) AS rejected_actions,
# MAGIC   coalesce(d.deferred, false) AS deferred
# MAGIC FROM silver_loans l
# MAGIC LEFT JOIN current_milestone m      ON m.loan_id = l.loan_id
# MAGIC LEFT JOIN silver_milestone_rules r ON r.milestone_type = m.current_milestone AND r.active
# MAGIC LEFT JOIN silver_milestone_rules nr ON nr.milestone_type = r.next_milestone_type AND nr.active
# MAGIC LEFT JOIN followups f              ON f.loan_id = l.loan_id
# MAGIC LEFT JOIN milestones_opened o      ON o.loan_id = l.loan_id
# MAGIC LEFT JOIN silver_attorneys_vendors p ON p.party_id = l.assigned_attorney_vendor_id
# MAGIC LEFT JOIN latest_action a          ON a.loan_id = l.loan_id
# MAGIC LEFT JOIN decisions d              ON d.loan_id = l.loan_id

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Detect conditions
# MAGIC Each line below is one rule. A loan can raise several conditions; the one with the lowest precedence in
# MAGIC `rule_conditions` becomes its **primary condition**.

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE TEMP VIEW loan_conditions AS
# MAGIC WITH dates AS (
# MAGIC   SELECT *,
# MAGIC          IF(milestone_complete, NULL, datediff(followup_date, current_date())) AS days_to_followup,
# MAGIC          has_track AND (required_party_type = 'ATTORNEY' AND NOT has_attorney
# MAGIC                         OR required_party_type = 'VENDOR' AND NOT has_vendor) AS missing_party
# MAGIC   FROM loan_facts
# MAGIC ),
# MAGIC detected AS (
# MAGIC   SELECT *, filter(array(
# MAGIC     IF(latest_action_status IN ('NOT_FOUND', 'MISMATCH', 'DUPLICATE'),
# MAGIC        named_struct('code', 'VERIFICATION_FAILURE', 'rule_id', 'RULE-VERIFICATION-001', 'detail', concat('Action ', latest_action_id, ' (', latest_action_type, ') verification ', latest_action_status)), NULL),
# MAGIC     IF(latest_action_status = 'PENDING',
# MAGIC        named_struct('code', 'PENDING_ACTION', 'rule_id', 'RULE-PENDING-001', 'detail', concat('Action ', latest_action_id, ' (', latest_action_type, ') is waiting to be verified')), NULL),
# MAGIC     IF(deferred,
# MAGIC        named_struct('code', 'PENDING_REVIEW', 'rule_id', 'RULE-PENDING-003', 'detail', 'A reviewer deferred the last recommendation'), NULL),
# MAGIC     IF(has_track AND NOT rule_found,
# MAGIC        named_struct('code', 'DATA_EXCEPTION', 'rule_id', 'RULE-DATA-001', 'detail', concat('No active milestone rule for ', current_milestone)), NULL),
# MAGIC     IF(has_track AND conflicting_dates,
# MAGIC        named_struct('code', 'DATA_EXCEPTION', 'rule_id', 'RULE-DATA-002', 'detail', concat('Conflicting dates on ', current_milestone)), NULL),
# MAGIC     IF(missing_party,
# MAGIC        named_struct('code', 'DATA_EXCEPTION', 'rule_id', 'RULE-DATA-003', 'detail', concat(current_milestone, ' needs an assigned ', lower(required_party_type), '; none assigned')), NULL),
# MAGIC     IF(max_open_of_same_type >= 2,
# MAGIC        named_struct('code', 'DUPLICATE_RISK', 'rule_id', 'RULE-DUPLICATE-001', 'detail', concat(max_open_of_same_type, ' open follow-ups of the same type for ', current_milestone)), NULL),
# MAGIC     IF(milestone_complete AND next_milestone IS NOT NULL AND NOT next_milestone_opened,
# MAGIC        named_struct('code', 'COMPLETED_NEEDS_NEXT', 'rule_id', 'RULE-MILESTONE-003', 'detail', concat(current_milestone, ' completed; next milestone ', next_milestone, ' not opened')), NULL),
# MAGIC     IF(milestone_complete AND rule_found AND next_milestone IS NULL,
# MAGIC        named_struct('code', 'COMPLETED', 'rule_id', 'RULE-MILESTONE-004', 'detail', concat('Final milestone ', current_milestone, ' complete')), NULL),
# MAGIC     IF(has_track AND NOT milestone_complete AND followup_date IS NULL AND requires_followup,
# MAGIC        named_struct('code', 'MISSING_FOLLOWUP', 'rule_id', 'RULE-FOLLOWUP-002', 'detail', concat(current_milestone, ' requires a follow-up date; none exists')), NULL),
# MAGIC     IF(days_to_followup < 0,
# MAGIC        named_struct('code', 'OVERDUE', 'rule_id', 'RULE-FOLLOWUP-003', 'detail', concat(current_milestone, ' follow-up ', followup_date, ' is ', -days_to_followup, ' days overdue')), NULL),
# MAGIC     IF(days_to_followup = 0,
# MAGIC        named_struct('code', 'DUE', 'rule_id', 'RULE-FOLLOWUP-004', 'detail', concat(current_milestone, ' follow-up is due today')), NULL),
# MAGIC     IF(days_to_followup BETWEEN 1 AND coalesce(lookahead_days, 7),
# MAGIC        named_struct('code', 'UPCOMING', 'rule_id', 'RULE-FOLLOWUP-005', 'detail', concat(current_milestone, ' follow-up in ', days_to_followup, ' days')), NULL)
# MAGIC   ), c -> c IS NOT NULL) AS found
# MAGIC   FROM dates
# MAGIC ),
# MAGIC with_already_actioned AS (   -- needs action, but an approved action is already pending
# MAGIC   SELECT *,
# MAGIC     IF(latest_action_status = 'PENDING'
# MAGIC          AND exists(found, c -> c.code IN ('OVERDUE', 'DUE', 'MISSING_FOLLOWUP', 'COMPLETED_NEEDS_NEXT')),
# MAGIC        array_append(found, named_struct('code', 'ALREADY_ACTIONED', 'rule_id', 'RULE-PENDING-002', 'detail', concat('Covered by pending action ', latest_action_id))),
# MAGIC        found) AS conditions
# MAGIC   FROM detected
# MAGIC ),
# MAGIC ranked AS (   -- one row per condition, with its precedence from the rules table
# MAGIC   SELECT c.loan_id, x.code, x.rule_id, x.detail, r.precedence, r.points
# MAGIC   FROM with_already_actioned c
# MAGIC   LATERAL VIEW explode(c.conditions) AS x
# MAGIC   JOIN rule_conditions r ON r.condition = x.code
# MAGIC ),
# MAGIC primary AS (
# MAGIC   SELECT loan_id,
# MAGIC          min_by(code, precedence) AS primary_condition,
# MAGIC          min_by(points, precedence) AS primary_points,
# MAGIC          array_sort(collect_list(named_struct('precedence', precedence, 'code', code, 'rule_id', rule_id, 'detail', detail)))
# MAGIC            AS condition_list
# MAGIC   FROM ranked
# MAGIC   GROUP BY loan_id
# MAGIC )
# MAGIC SELECT
# MAGIC   c.* EXCEPT (found, conditions),
# MAGIC   greatest(0, coalesce(-c.days_to_followup, 0)) AS days_overdue,
# MAGIC   coalesce(p.primary_condition, 'NO_ACTION') AS primary_condition,
# MAGIC   coalesce(p.primary_points, 0) AS primary_points,
# MAGIC   coalesce(transform(p.condition_list, x -> named_struct('code', x.code, 'rule_id', x.rule_id, 'detail', x.detail)),
# MAGIC            array(named_struct('code', 'NO_ACTION', 'rule_id', 'RULE-NOACTION-001',
# MAGIC                               'detail', IF(c.has_track, 'On track', 'No servicing track')))) AS conditions
# MAGIC FROM with_already_actioned c
# MAGIC LEFT JOIN primary p ON p.loan_id = c.loan_id

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Score, priority, and allowed actions
# MAGIC The **attention score** adds up explainable points (the drivers are stored with the score):
# MAGIC primary condition + 1 per day overdue (max 30) + 3 per milestone severity (max 15) + 5 per other condition
# MAGIC (max 15) + 10 per failed action (max 20) + 10 if the required attorney or vendor is missing + 5 after a recent
# MAGIC rejection - 30 if a pending action already covers it. **Priority**: 70+ Critical, 45+ High, 20+ Medium.
# MAGIC
# MAGIC **Allowed actions** start from `rule_conditions`, then: contact actions need the right party assigned,
# MAGIC recently rejected actions are removed, and Critical loans can be escalated (first, when 60+ days overdue).

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE TABLE gold_loan_state
# MAGIC COMMENT 'One row per loan: milestone, follow-up, conditions, score, priority, allowed actions - SYNTHETIC DEMONSTRATION DATA' AS
# MAGIC WITH drivers AS (
# MAGIC   SELECT *, filter(array(
# MAGIC     named_struct('points', primary_points, 'detail', primary_condition),
# MAGIC     named_struct('points', least(days_overdue, 30), 'detail', concat(days_overdue, ' days overdue')),
# MAGIC     named_struct('points', IF(has_track AND primary_condition NOT IN ('NO_ACTION', 'COMPLETED'), least(coalesce(severity, 3) * 3, 15), 0),
# MAGIC                  'detail', concat(current_milestone, ' severity ', coalesce(severity, 3))),
# MAGIC     named_struct('points', least((size(conditions) - 1) * 5, 15),
# MAGIC                  'detail', concat('Also: ', array_join(filter(transform(conditions, x -> x.code), x -> x <> primary_condition), ', '))),
# MAGIC     named_struct('points', least(failed_actions * 10, 20), 'detail', concat(failed_actions, ' failed action(s)')),
# MAGIC     named_struct('points', IF(missing_party, 10, 0), 'detail', 'Required attorney or vendor missing'),
# MAGIC     named_struct('points', IF(size(rejected_actions) > 0, 5, 0), 'detail', concat('Rejected recently: ', array_join(rejected_actions, ', '))),
# MAGIC     named_struct('points', IF(primary_condition = 'ALREADY_ACTIONED', -30, 0), 'detail', 'Covered by a pending action')
# MAGIC   ), d -> d.points <> 0) AS score_drivers
# MAGIC   FROM loan_conditions
# MAGIC ),
# MAGIC scored AS (
# MAGIC   SELECT *,
# MAGIC          greatest(0, least(100, aggregate(score_drivers, 0, (total, d) -> total + d.points))) AS attention_score
# MAGIC   FROM drivers
# MAGIC ),
# MAGIC prioritized AS (
# MAGIC   SELECT s.*,
# MAGIC          CASE WHEN attention_score >= 70 THEN 'CRITICAL' WHEN attention_score >= 45 THEN 'HIGH'
# MAGIC               WHEN attention_score >= 20 THEN 'MEDIUM' ELSE 'LOW' END AS priority,
# MAGIC          IF(primary_condition = 'VERIFICATION_FAILURE' AND latest_action_status = 'MISMATCH',
# MAGIC             array('REVIEW_DATA_EXCEPTION', 'RETRY_FAILED_ACTION'), r.allowed_actions) AS base_actions
# MAGIC   FROM scored s
# MAGIC   JOIN rule_conditions r ON r.condition = s.primary_condition
# MAGIC ),
# MAGIC allowed AS (
# MAGIC   SELECT *, filter(
# MAGIC     transform(base_actions, a -> IF(a = 'OVERDUE_ACTION', overdue_action, a)),
# MAGIC     a -> NOT (a = 'CONTACT_ATTORNEY' AND NOT has_attorney)
# MAGIC          AND NOT (a = 'CONTACT_SERVICING_VENDOR' AND NOT has_vendor)
# MAGIC          AND NOT array_contains(rejected_actions, a)) AS checked_actions
# MAGIC   FROM prioritized
# MAGIC ),
# MAGIC escalated AS (
# MAGIC   SELECT *, array_distinct(CASE
# MAGIC     WHEN priority <> 'CRITICAL' OR primary_condition IN ('NO_ACTION', 'COMPLETED', 'PENDING_ACTION', 'ALREADY_ACTIONED', 'PENDING_REVIEW')
# MAGIC       THEN checked_actions
# MAGIC     WHEN days_overdue >= 60 THEN array_prepend(checked_actions, 'ESCALATE_TO_SPECIALIST')
# MAGIC     ELSE array_append(checked_actions, 'ESCALATE_TO_SPECIALIST')
# MAGIC   END) AS final_actions
# MAGIC   FROM allowed
# MAGIC )
# MAGIC SELECT
# MAGIC   * EXCEPT (primary_points, base_actions, checked_actions, final_actions),
# MAGIC   IF(size(final_actions) = 0, array('REQUEST_INFORMATION'), final_actions) AS allowed_actions,
# MAGIC   IF(size(final_actions) = 0, 'REQUEST_INFORMATION', final_actions[0]) AS recommended_action,
# MAGIC   array_join(transform(slice(array_sort(score_drivers, (a, b) -> b.points - a.points), 1, 3),
# MAGIC                        d -> concat(d.detail, ' (', IF(d.points > 0, '+', ''), d.points, ')')), '; ') AS top_drivers,
# MAGIC   IF(is_active, row_number() OVER (PARTITION BY is_active ORDER BY attention_score DESC, loan_id), NULL) AS queue_rank,
# MAGIC   current_date() AS processing_date
# MAGIC FROM escalated

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Walk one loan through the rules
# MAGIC `LSI-SYN-000007`: Title Review was completed, but Complaint Filed was never opened (RULE-MILESTONE-003).

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT loan_id, current_milestone, milestone_status, next_milestone, next_milestone_opened, primary_condition,
# MAGIC        conditions, attention_score, score_drivers, priority, allowed_actions, recommended_action
# MAGIC FROM gold_loan_state
# MAGIC WHERE loan_id IN ('LSI-SYN-000007', 'LSI-SYN-000005')

# COMMAND ----------

# MAGIC %md ## 7. The work queue

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT queue_rank, priority, loan_id, primary_condition, attention_score, top_drivers, recommended_action
# MAGIC FROM gold_loan_state
# MAGIC WHERE is_active
# MAGIC ORDER BY queue_rank
# MAGIC LIMIT 15

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT priority, count(*) AS loans
# MAGIC FROM gold_loan_state
# MAGIC WHERE is_active
# MAGIC GROUP BY priority
# MAGIC ORDER BY min(queue_rank)
