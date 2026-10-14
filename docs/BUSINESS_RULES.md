# Business Rule Catalog — Loan Servicing Intelligence

> **Synthetic, configurable assumptions.** These rules, thresholds, and mappings exist only to demonstrate
> deterministic, explainable servicing monitoring. They do not represent any lender's servicing policy, legal
> process, or regulated decision framework. All values live in `config/*.yml` and can be changed without code.

Versions: rules `rules-2026.10.1`, scoring `scoring-2026.10.1`, escalation `escalation-2026.10.1`,
actions `actions-2026.10.1`. Processing date in demo mode: **2026-10-12**.

Implementation map: facts `src/rules.py`, conditions `src/rules.py`, escalation
`src/rules.py`, allowed actions `src/rules.py`, follow-up dates
`src/rules.py`, validation `src/rules.py`, scoring `src/rules.py`,
verification `src/rules.py`.

## 1. Definitions

- **Processing date (P):** the date the portfolio is evaluated.
- **Current milestone:** see RULE-MILESTONE-001.
- **Follow-up-type events:** `FOLLOWUP`, `CONTACT`, `ESCALATION`, `INFO_REQUEST`, `DATA_REVIEW`.
- **Open:** status `OPEN`.
- **Effective follow-up date:** see RULE-FOLLOWUP-001.
- **days_to_followup** = effective follow-up − P; **days_overdue** = max(0, P − effective follow-up) for incomplete milestones.
- **Active loan:** `loan_status = ACTIVE`. Inactive loans are excluded from KPIs and the queue.

## 2. Milestone rules

RULE-NOACTION-001: when no raw condition is raised, the loan is `NO_ACTION` (on track, or no servicing track).

| ID | Rule | Logic |
|----|------|-------|
| RULE-MILESTONE-001 | Current milestone | Among non-cancelled `MILESTONE` events, highest `milestone_sequence` (unknown types rank −1); ties → latest `event_date`, then `created_at`. Loans without milestone events have no servicing track. |
| RULE-MILESTONE-002 | Completion | Complete when `status = COMPLETED` **and** `completed_date` populated. |
| RULE-MILESTONE-003 | `COMPLETED_NEEDS_NEXT` | Current milestone complete, rule has `next_milestone_type`, and no event for that next milestone exists. |
| RULE-MILESTONE-004 | `COMPLETED` | Current milestone complete and rule has no next milestone (terminal). |

## 3. Follow-up rules

| ID | Rule | Logic |
|----|------|-------|
| RULE-FOLLOWUP-001 | Effective follow-up | Latest (by `event_date`, `created_at`) open follow-up-type event for the current milestone with a follow-up date; otherwise the milestone event's own `followup_date`. |
| RULE-FOLLOWUP-002 | `MISSING_FOLLOWUP` | Incomplete milestone, active rule `requires_followup = true`, no effective follow-up date. |
| RULE-FOLLOWUP-003 | `OVERDUE` | Incomplete milestone and effective follow-up < P. |
| RULE-FOLLOWUP-004 | `DUE` | Incomplete milestone and effective follow-up = P. |
| RULE-FOLLOWUP-005 | `UPCOMING` | Incomplete milestone and 1 ≤ days_to_followup ≤ rule `lookahead_days` (default 7 if rule missing). |
| RULE-FOLLOWUP-006 | Follow-up date calculation | P + action `followup_days` (or milestone `default_followup_days`; next milestone default for `CREATE_NEXT_MILESTONE`), rolled to Monday if it lands on a weekend (`business_days_only`). |

An incomplete milestone with a follow-up beyond the look-ahead is on track → `NO_ACTION`.

## 4. Duplicate, pending, and review rules

| ID | Rule | Logic |
|----|------|-------|
| RULE-DUPLICATE-001 | `DUPLICATE_RISK` | ≥ 2 open follow-up-type events with the same `event_type` for the current milestone. |
| RULE-DUPLICATE-002 | Proposed duplicate | A proposed event duplicates an existing one if an open, not-overdue event with the same `event_type` and milestone exists, or a pending action with the same action type exists. Used by `check_existing_event` and validation. |
| RULE-PENDING-001 | `PENDING_ACTION` | Latest action for the loan inside the failure lookback (30 d) has verification status `PENDING`. |
| RULE-PENDING-002 | `ALREADY_ACTIONED` | An actionable condition (`OVERDUE`, `DUE`, `MISSING_FOLLOWUP`, `COMPLETED_NEEDS_NEXT`) exists and RULE-PENDING-001 holds. |
| RULE-PENDING-003 | `PENDING_REVIEW` | Latest reviewer decision for the loan inside 14 days is `DEFER`. |
| RULE-REVIEW-001 | Prior rejection | Actions rejected inside 14 days are removed from allowed actions unless escalation is `ESCALATE`/`CRITICAL`; contributes a score driver. |

## 5. Data-exception rules (`DATA_EXCEPTION`)

| ID | Rule | Logic |
|----|------|-------|
| RULE-DATA-001 | Missing milestone rule | Current milestone type has no **active** rule. |
| RULE-DATA-002 | Conflicting dates | `completed_date < event_date`, `COMPLETED` without `completed_date`, or `OPEN` with `completed_date`. |
| RULE-DATA-003 | Missing assigned party | Current rule's `overdue_action` requires a party type (`CONTACT_ATTORNEY` → ATTORNEY, `CONTACT_SERVICING_VENDOR` → VENDOR) and the assigned party is missing, inactive, or of another type. |
| RULE-DATA-004 | Missing specialist | Loan with a servicing track has no active assigned specialist. |
| RULE-DATA-005 | Invalid source values | Silver flagged DQ issues on the loan or its current milestone event. |

## 6. Verification rules

| ID | Rule | Logic |
|----|------|-------|
| RULE-VERIFICATION-001 | `VERIFICATION_FAILURE` | Latest action inside the failure lookback has status `FAILED`, `NOT_FOUND`, `MISMATCH`, or `DUPLICATE`. |
| RULE-VERIFICATION-002 | Matching | Candidate events: same `loan_id` and `event_type`, `source = SERVICING_SYSTEM_ADAPTER`, not cancelled. If the event note carries a reference token `[ref <action_id>]` it must equal the action; otherwise `created_at ≥ submitted_at`. |
| RULE-VERIFICATION-003 | Status | Adapter failure → `FAILED`; 0 matches → `PENDING` if P − submission business date (the action `event_date`) < 2 days else `NOT_FOUND`; `APPROVED` (not yet submitted) → `PENDING`; 1 match → `VERIFIED` when `followup_date`, `event_date`, and `milestone_type` (when set) equal the approved values, else `MISMATCH` with differences; ≥ 2 matches → `DUPLICATE`. Actions recorded as `VERIFIED` in history are final. |

## 7. Primary condition precedence

`VERIFICATION_FAILURE > DATA_EXCEPTION > ALREADY_ACTIONED > DUPLICATE_RISK > OVERDUE > MISSING_FOLLOWUP > DUE >
COMPLETED_NEEDS_NEXT > PENDING_REVIEW > PENDING_ACTION > UPCOMING > COMPLETED > NO_ACTION`

All other raw conditions become `secondary_conditions`. Precedence is configurable
(`business_rules.yml: condition_precedence`).

## 8. Escalation (`config/escalation_rules.yml`)

Every matching rule adds a reason; the highest state wins (`NONE < WATCH < FOLLOW_UP < ESCALATE < CRITICAL`).
Rules 001–003 and 005 do not apply when the primary condition is `ALREADY_ACTIONED` or `PENDING_ACTION`.

| ID | State | When |
|----|-------|------|
| RULE-ESCALATION-001 | CRITICAL | days_overdue ≥ 60 |
| RULE-ESCALATION-002 | CRITICAL | severity ≥ 5 and days_overdue ≥ 15 |
| RULE-ESCALATION-003 | CRITICAL | severity ≥ 5, incomplete, days_to_followup ≤ 5 (critical-date proximity) |
| RULE-ESCALATION-004 | CRITICAL | ≥ 2 failed/unverified actions in lookback |
| RULE-ESCALATION-005 | ESCALATE | days_overdue ≥ 30 |
| RULE-ESCALATION-006 | ESCALATE | `VERIFICATION_FAILURE` present |
| RULE-ESCALATION-007 | ESCALATE | Missing assigned party (RULE-DATA-003) |
| RULE-ESCALATION-008 | ESCALATE | Prior rejection and days_overdue ≥ 15 |
| RULE-ESCALATION-009 | FOLLOW_UP | Primary in OVERDUE, DUE, MISSING_FOLLOWUP, COMPLETED_NEEDS_NEXT, DUPLICATE_RISK, DATA_EXCEPTION, VERIFICATION_FAILURE |
| RULE-ESCALATION-010 | WATCH | Primary in UPCOMING, PENDING_ACTION, PENDING_REVIEW, ALREADY_ACTIONED |

Required role: NONE→none, WATCH/FOLLOW_UP→`LOAN_SERVICING_SPECIALIST`, ESCALATE→`SENIOR_SPECIALIST`,
CRITICAL→`SERVICING_MANAGER`. Health segment: NONE→Healthy, WATCH→Watch, FOLLOW_UP/ESCALATE→Action Required,
CRITICAL→Critical. `needs_attention` = escalation ∈ {FOLLOW_UP, ESCALATE, CRITICAL}.

## 9. Allowed actions (`config/allowed_actions.yml`) — RULE-ACTIONS-001

1. Start from the ordered list for the primary condition (`MILESTONE_OVERDUE_ACTION` → the current rule's
   `overdue_action`; duplicates removed). For `VERIFICATION_FAILURE`, a `MISMATCH`/`DUPLICATE` verification
   status uses the override list.
2. Escalation adjustment (not for NO_ACTION, COMPLETED, PENDING_ACTION, ALREADY_ACTIONED, PENDING_REVIEW):
   ESCALATE appends `ESCALATE_TO_SPECIALIST`; CRITICAL prepends it.
3. Remove contact actions whose required party is not assigned/active.
4. Remove prior-rejected actions (RULE-REVIEW-001) unless escalation ≥ ESCALATE.
5. If the list becomes empty, use `[REQUEST_INFORMATION]`.

The first entry is the **deterministic default** recommendation.

| Condition | Ordered allowed actions |
|-----------|------------------------|
| NO_ACTION, COMPLETED, PENDING_REVIEW, PENDING_ACTION, ALREADY_ACTIONED | NO_ACTION |
| UPCOMING | NO_ACTION, milestone overdue action |
| DUE | milestone overdue action, CREATE_FOLLOWUP, NO_ACTION |
| OVERDUE | milestone overdue action, CREATE_FOLLOWUP, REQUEST_INFORMATION |
| MISSING_FOLLOWUP | CREATE_FOLLOWUP, REQUEST_INFORMATION |
| COMPLETED_NEEDS_NEXT | CREATE_NEXT_MILESTONE, REQUEST_INFORMATION |
| DUPLICATE_RISK | REVIEW_DATA_EXCEPTION, NO_ACTION |
| DATA_EXCEPTION | REVIEW_DATA_EXCEPTION, REQUEST_INFORMATION |
| VERIFICATION_FAILURE | RETRY_FAILED_ACTION, REVIEW_DATA_EXCEPTION (MISMATCH: REVIEW_DATA_EXCEPTION, RETRY_FAILED_ACTION; DUPLICATE: REVIEW_DATA_EXCEPTION) |

Action → outbound event type: CREATE_FOLLOWUP→FOLLOWUP, CREATE_NEXT_MILESTONE→MILESTONE (next milestone),
ESCALATE_TO_SPECIALIST→ESCALATION (+3 d), CONTACT_ATTORNEY / CONTACT_SERVICING_VENDOR→CONTACT (+7 d),
REQUEST_INFORMATION→INFO_REQUEST (+5 d), REVIEW_DATA_EXCEPTION→DATA_REVIEW (+2 d),
RETRY_FAILED_ACTION→original action's event type (+5 d), NO_ACTION→no event.

## 10. Attention scoring (`config/attention_scoring.yml`) — RULE-SCORING-001

Score = clamp(0, 100, Σ drivers). Drivers:

| Driver | Points |
|--------|--------|
| Primary condition | VERIFICATION_FAILURE 40, OVERDUE 30, DATA_EXCEPTION 25, MISSING_FOLLOWUP 25, DUPLICATE_RISK 20, DUE 20, COMPLETED_NEEDS_NEXT 20, PENDING_REVIEW 10, UPCOMING 8, PENDING_ACTION 5, ALREADY_ACTIONED 5, COMPLETED/NO_ACTION 0 |
| Days overdue | 1 per day, max 30 |
| Milestone severity | 3 × severity, max 15 (not for NO_ACTION/COMPLETED; missing rule → severity 3) |
| Secondary conditions | 5 each, max 15 |
| Failed/unverified actions (lookback) | 10 each, max 20 |
| Missing assigned party | 10 |
| Prior rejection | 5 |
| Critical-date proximity | 15 (severity ≥ 5 and days_to_followup ≤ 5, incomplete) |
| Covered by pending action | −30 (primary ALREADY_ACTIONED) |

Priority: CRITICAL ≥ 70, HIGH ≥ 45, MEDIUM ≥ 20, LOW otherwise. Output: `score`, `priority`, `score_drivers`
(factor, points, detail), `calculated_at`, `scoring_version`.

## 11. Validation (RULE-VALIDATION-001)

Before an outbound event is produced, the proposed event must pass all checks; failures are returned as
codes and the action is not created:

| Code | Check |
|------|-------|
| ACTION_NOT_ALLOWED | Action in the loan's current allowed actions (edits included) |
| LOAN_INACTIVE | Loan is active |
| EVENT_TYPE_MISMATCH | Event type matches the action catalog |
| FOLLOWUP_OUT_OF_RANGE | P ≤ follow-up ≤ P + 120 days |
| PARTY_REQUIRED | Contact actions have an active party of the required type |
| NOTE_TOO_LONG | Note ≤ 1,000 characters |
| DUPLICATE_EVENT | RULE-DUPLICATE-002 |
| PENDING_ACTION_EXISTS | No pending action (except RETRY_FAILED_ACTION) |
| STALE_RECOMMENDATION | Loan `state_fingerprint` and rule version unchanged since the recommendation |
| NO_EVENT_FOR_ACTION | Informational: NO_ACTION produces no outbound event |

## 12. Scenario manifest (expected outcomes)

Loan IDs `LSI-SYN-000001`…`000020`. These drive `tests/integration/test_scenario_manifest.py` and the Evaluation page.

| Scenario | Type | Setup (relative to P) | Condition | Priority | Action | Verification |
|----------|------|-----------------------|-----------|----------|--------|--------------|
| S01 | HEALTHY_NO_ACTION | Performing loan | NO_ACTION | LOW | NO_ACTION | NOT_APPLICABLE |
| S02 | UPCOMING | DEMAND_LETTER follow-up P+5 | UPCOMING | LOW | NO_ACTION | NOT_APPLICABLE |
| S03 | DUE_TODAY | DEMAND_LETTER follow-up P | DUE | MEDIUM | CREATE_FOLLOWUP | NOT_APPLICABLE |
| S04 | ONE_DAY_OVERDUE | REFERRAL_TO_ATTORNEY follow-up P−1 (adapter: FAIL) | OVERDUE | MEDIUM | CONTACT_ATTORNEY | NOT_APPLICABLE |
| S05 | MATERIALLY_OVERDUE | TITLE_REVIEW follow-up P−18 | OVERDUE | HIGH | CONTACT_ATTORNEY | NOT_APPLICABLE |
| S06 | SEVERELY_OVERDUE | JUDGMENT_HEARING follow-up P−75 | OVERDUE | CRITICAL | ESCALATE_TO_SPECIALIST | NOT_APPLICABLE |
| S07 | COMPLETED_NEEDS_NEXT | TITLE_REVIEW completed P−3, no COMPLAINT_FILED | COMPLETED_NEEDS_NEXT | MEDIUM | CREATE_NEXT_MILESTONE | NOT_APPLICABLE |
| S08 | MISSING_FOLLOWUP | COMPLAINT_FILED open, no follow-up | MISSING_FOLLOWUP | MEDIUM | CREATE_FOLLOWUP | NOT_APPLICABLE |
| S09 | DUPLICATE_RISK | Two open FOLLOWUP events (P+20, P+21) | DUPLICATE_RISK | MEDIUM | REVIEW_DATA_EXCEPTION | NOT_APPLICABLE |
| S10 | CONFLICTING_DATES | DEMAND_LETTER completed before opened | DATA_EXCEPTION | MEDIUM | REVIEW_DATA_EXCEPTION | NOT_APPLICABLE |
| S11 | MISSING_RULE | LEGACY_REVIEW milestone (inactive rule) | DATA_EXCEPTION | MEDIUM | REVIEW_DATA_EXCEPTION | NOT_APPLICABLE |
| S12 | MISSING_ASSIGNED_PARTY | COMPLAINT_FILED P−5, no attorney | DATA_EXCEPTION | HIGH | REVIEW_DATA_EXCEPTION | NOT_APPLICABLE |
| S13 | PRIOR_REJECTION | REFERRAL_TO_ATTORNEY P−10, CONTACT_ATTORNEY rejected P−3 | OVERDUE | HIGH | CREATE_FOLLOWUP | NOT_APPLICABLE |
| S14 | APPROVED_ACTION_PENDING | Action submitted P, follow-up P+4 | PENDING_ACTION | LOW | NO_ACTION | PENDING |
| S15 | SUCCESSFUL_VERIFICATION | Action submitted P−3, matching event | NO_ACTION | LOW | NO_ACTION | VERIFIED |
| S16 | FAILED_VERIFICATION | Action submitted P−5, no event | VERIFICATION_FAILURE | CRITICAL | RETRY_FAILED_ACTION | NOT_FOUND |
| S17 | MISMATCHED_VERIFICATION | Event follow-up differs by 7 days | VERIFICATION_FAILURE | HIGH | REVIEW_DATA_EXCEPTION | MISMATCH |
| S18 | MULTIPLE_UNRESOLVED | Overdue 38 d + duplicate follow-ups + no attorney | DATA_EXCEPTION | CRITICAL | REVIEW_DATA_EXCEPTION | NOT_APPLICABLE |
| S19 | URGENT_COVERED_BY_PENDING | Overdue 20 d, action submitted P | ALREADY_ACTIONED | LOW | NO_ACTION | PENDING |
| S20 | DEFERRED_PENDING_REVIEW | Upcoming P+6, DEFER decision P−2 | PENDING_REVIEW | MEDIUM | NO_ACTION | NOT_APPLICABLE |

Worked example (S05): primary OVERDUE 30 + days overdue 18 + severity 2×3 = 54 → HIGH; escalation FOLLOW_UP
(RULE-ESCALATION-009); allowed [CONTACT_ATTORNEY, CREATE_FOLLOWUP, REQUEST_INFORMATION]; default CONTACT_ATTORNEY.

## 13. Change control

Rule changes are made in `config/*.yml`, bump the relevant `version`, update this document and
`docs/DECISIONS.md` when behavior changes, and must pass the scenario-manifest tests. Reviewer feedback never
changes rules automatically.
