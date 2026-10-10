# Agent Tools — Loan Servicing Intelligence

> Synthetic demonstration. All tools are deterministic, read-only (except the explicitly preparatory tools,
> which still never write to the System of Record), typed, logged, and independently testable.

Implementation: `src/tools/servicing_tools.py` (functions), `src/tools/registry.py` (schemas, descriptions),
`src/tools/executor.py` (validation, timing, logging). Each tool takes a `ToolContext` (portfolio evaluation,
silver dataset, operational state, config, processing date) plus typed parameters, and returns a JSON-safe dict.
The executor wraps results as:

```json
{"tool_name": "check_followup_status", "success": true, "data": {...}, "error": null,
 "duration_ms": 1.4, "called_at": "2026-10-12T14:03:22Z", "input": {"loan_id": "LSI-SYN-000005"}}
```

Unknown loans return `success: false, error: "LOAN_NOT_FOUND"` — never fabricated defaults.

Unity Catalog SQL functions (`notebooks/05_register_agent_tools.py`, prefix `lsi_`) expose read-only
structured tools over Gold tables for SQL clients, Genie, or MCP; the Python implementations remain the
reference used by the app and tests.

## Loan context and history

| Tool | Input | Output (key fields) | UC function |
|------|-------|--------------------|-------------|
| `get_loan_context` | loan_id | loan attributes, balances, statuses, portfolio, specialist, party, is_active | `lsi_get_loan_context` |
| `get_event_history` | loan_id, limit=50, include_payments=false | chronological events (id, type, milestone, dates, status, source, note) | `lsi_get_event_history` |
| `get_current_milestone` | loan_id | milestone_type, sequence, event_id, dates, status, rule_id RULE-MILESTONE-001 | `lsi_get_current_milestone` |
| `check_milestone_completion` | loan_id | is_complete, completed_date, conflicts[], rule_id | — |
| `check_followup_status` | loan_id | effective_followup_date, source_event_id, days_to_followup, days_overdue, followup_condition, rule_ids | `lsi_check_followup_status` |
| `calculate_days_to_followup` | loan_id or followup_date | days_to_followup, days_overdue | — |
| `get_next_required_milestone` | loan_id | next_milestone_type, exists_already, default_followup_days | — |
| `get_milestone_rule` | milestone_type | rule row or `found: false` (RULE-DATA-001) | `lsi_get_milestone_rule` |

## Duplicate, pending, and review checks

| Tool | Input | Output |
|------|-------|--------|
| `check_existing_event` | loan_id, event_type, milestone_type? | open_equivalent_events[], duplicate_risk, rule_id RULE-DUPLICATE-001/002 |
| `check_pending_recommendation` | loan_id | pending_recommendations[] (PENDING_REVIEW/DEFERRED) |
| `check_pending_action` | loan_id | pending_actions[] (status, verification_status), has_pending |
| `check_previous_rejection` | loan_id | rejected_actions[], within_lookback, rule_id RULE-REVIEW-001 |
| `get_assigned_party` | loan_id | specialist {id, name, active}, party {id, name, type, active}, required_party_type, party_ok |

## Escalation, scoring, actions

| Tool | Input | Output |
|------|-------|--------|
| `calculate_escalation_state` | loan_id | escalation_state, escalation_reasons[{rule_id, reason}], required_role, allowed_actions |
| `calculate_loan_attention_score` | loan_id | score, priority, score_drivers, calculated_at, scoring_version |
| `get_attention_score_drivers` | loan_id | score_drivers sorted by points, plain-language summary |
| `get_allowed_actions` | loan_id | allowed_actions[], default_action, removed_actions[{action, reason}] |
| `calculate_followup_date` | loan_id, action_type | followup_date, basis (days, source, business-day roll), rule_id RULE-FOLLOWUP-006 |

## Action preparation and validation (never writes to the System of Record)

| Tool | Input | Output |
|------|-------|--------|
| `prepare_followup_event` | loan_id, action_type, followup_date?, note? | uncommitted outbound event draft (event_type, milestone, dates, party, idempotency_key) |
| `prepare_escalation` | loan_id, reason?, target_role? | uncommitted ESCALATION draft with required role |
| `validate_proposed_event` | loan_id, action_type, event_type, followup_date, note?, recommendation_fingerprint? | valid, errors[{code, message}], warnings[] |

## Verification

| Tool | Input | Output |
|------|-------|--------|
| `verify_servicing_event_created` | action_id | verification_status, matched_event_ids, rule_id RULE-VERIFICATION-003 |
| `compare_approved_to_actual` | action_id | approved{}, actual{}, differences[{field, approved, actual}] |

## Portfolio tools

| Tool | Input | Output | UC function |
|------|-------|--------|-------------|
| `get_portfolio_health_summary` | — | KPI counts, health segments, condition counts | `lsi_portfolio_health_summary` |
| `get_priority_queue` | limit=20, priority?, condition? | ranked queue rows with drivers | `lsi_priority_queue` |
| `get_portfolio_exceptions` | limit=50 | DATA_EXCEPTION / DUPLICATE_RISK loans with detail | — |
| `get_specialist_workload_summary` | — | per specialist: assigned, needs attention, critical, high | `lsi_specialist_workload` |
| `get_recommendations_awaiting_approval` | limit=50 | PENDING_REVIEW recommendations | — |
| `get_failed_verifications` | limit=50 | actions with FAILED/NOT_FOUND/MISMATCH/DUPLICATE | — |

## Agent-only tool

| Tool | Purpose |
|------|---------|
| `submit_recommendation` | Ends the LLM loop with the model's choice and narrative (schema in `docs/AGENT_DESIGN.md` §3). Not a servicing tool; it does not persist or execute anything by itself. |

## Logging

Every call produces an activity record (`run_id`, `loan_id`, `step`, `tool_name`, `input_summary`,
`output_summary` (≤ 400 chars), `duration_ms`, `success`, `error`, `created_at`). Summaries never contain
credentials or prompts.

## Testing

`tests/unit/test_tools.py` covers each tool on scenario loans, unknown loans, and schema validation;
`tests/integration/test_agent_tools_interaction.py` covers agent ↔ tool sequences with a scripted LLM.
