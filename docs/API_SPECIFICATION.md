# API Specification — Loan Servicing Intelligence Agent API

> Synthetic demonstration. All example values are synthetic.

- Implementation: FastAPI, `src/api.py`; service facade `src/service.py`.
- Base URL (in the App container): `http://127.0.0.1:8001` (env `LSI_API_PORT`). Standalone:
  `uvicorn src.api.main:app --port 8001`. Interactive docs at `/docs`.
- Content type: `application/json`. Dates `YYYY-MM-DD`; timestamps ISO-8601 UTC.
- Reviewer identity: request body fields `reviewer_id` / `reviewer_role` (demo authorization model; see
  limitations). Every response from loan endpoints includes `"synthetic_data": true`.

## Errors

| Status | Body | When |
|--------|------|------|
| 404 | `{"detail": "LOAN_NOT_FOUND"}` | Unknown loan / recommendation / action |
| 409 | `{"detail": {"code": "VALIDATION_FAILED", "errors": [...]}}` | Revalidation failed on approval/submit |
| 409 | `{"detail": {"code": "INVALID_STATE", ...}}` | e.g. deciding a non-pending recommendation |
| 422 | FastAPI validation error | Malformed request |
| 503 | `{"detail": "AGENT_UNAVAILABLE"}` | `llm` mode with the model unreachable |

## Agent

### `POST /api/agent`
Request:
```json
{"mode": "assess", "loan_id": "LSI-SYN-000005", "question": null, "user_id": "SPEC-01"}
```
`mode`: `assess` (create a recommendation), `ask` (governed question; `question` required, `loan_id`
optional), `briefing` (portfolio briefing).

Response (`assess`/`ask`):
```json
{
  "run_id": "RUN-20261012-6f1c2a",
  "mode": "assess",
  "agent_mode": "llm",
  "answer": "Loan LSI-SYN-000005 is 18 days past its TITLE_REVIEW follow-up...",
  "loan_id": "LSI-SYN-000005",
  "condition": "OVERDUE",
  "secondary_conditions": [],
  "priority": "HIGH",
  "score": 54,
  "score_drivers": [{"factor": "primary_condition", "points": 30, "detail": "OVERDUE"},
                    {"factor": "days_overdue", "points": 18, "detail": "18 days overdue"},
                    {"factor": "milestone_severity", "points": 6, "detail": "TITLE_REVIEW severity 2"}],
  "evidence": [{"source_type": "TOOL", "source_identifier": "check_followup_status",
                "description": "Effective follow-up date", "value": "2026-09-24", "observed_at": "2026-10-12T14:03:22Z"}],
  "recommendation": { "...": "Recommendation object (see below)" },
  "confidence": "HIGH",
  "uncertainty": "None material.",
  "missing_information": [],
  "tool_calls": [{"tool_name": "get_loan_context", "success": true, "duration_ms": 0.8, "input_summary": "...", "output_summary": "..."}],
  "requires_human_approval": true,
  "synthetic_data": true
}
```
Response (`briefing`): `{"run_id", "text", "source": "llm"|"deterministic", "facts": {...}, "rejected_reason": null}`.

## Portfolio

### `GET /api/portfolio/summary`
KPIs (`active_loans`, `need_attention`, `upcoming`, `overdue`, `missing_followup`, `critical`,
`recommendations_awaiting_approval`, `approved_today`, `verification_failures`), `health_segments`
(`[{segment, loan_count, share}]`), `condition_counts`, `processing_date`, `refresh_cycle`, versions.

### `GET /api/portfolio/loans`
Portfolio table rows. Query: `state, portfolio, loan_status, payment_status, foreclosure_status, milestone,
health, priority, specialist, agent_status, search, limit (default 2000)`.

### `GET /api/portfolio/priority-queue`
Query: `priority, condition, review_status, specialist, limit (default 200)`. Rows: `queue_rank, priority,
loan_id, borrower_display_name, primary_condition, secondary_conditions, severity, current_milestone,
effective_followup_date, days_overdue, attention_score, score_drivers, top_drivers_text,
recommended_action, confidence, specialist_name, review_status, why_prioritized`.

### `GET /api/portfolio/briefing-facts`
Deterministic facts used by the briefing.

## Loans

### `GET /api/loans/{loan_id}`
Loan detail: loan attributes, servicing state (conditions, escalation, score, drivers, allowed actions),
assigned parties, pending actions, latest verification, milestone state.

### `GET /api/loans/{loan_id}/events`
Chronological timeline including proposed (pending recommendation), submitted (pending action), failed and
verified markers: `[{event_id, event_type, milestone_type, event_date, followup_date, completed_date, status,
display_state, source, event_note}]`. `display_state` ∈ `COMPLETED, CURRENT, UPCOMING, SCHEDULED, DUE, OVERDUE,
PROPOSED, SUBMITTED, FAILED, VERIFIED, HISTORY`.

### `GET /api/loans/{loan_id}/recommendations`
All recommendations for the loan, newest first.

### `GET /api/loans/{loan_id}/activity`
Activity records for the loan.

## Recommendations and decisions

### `POST /api/recommendations/{recommendation_id}/decision`
```json
{"decision": "EDIT", "reviewer_id": "SPEC-01", "reviewer_role": "LOAN_SERVICING_SPECIALIST",
 "reason": "Shorter follow-up requested", "comment": "Attorney indicated filing this week",
 "edits": {"action_type": "CONTACT_ATTORNEY", "followup_date": "2026-10-16",
           "note": "Requested status update from assigned synthetic legal vendor.",
           "outreach": "Please confirm current status...", "event_type": null, "escalation_target": null}}
```
`decision` ∈ `APPROVE, EDIT, REJECT, DEFER, ESCALATE`. APPROVE/EDIT trigger revalidation and create an
action with status `APPROVED` and an outbound event payload. ESCALATE creates an `ESCALATE_TO_SPECIALIST`
action (revalidated against allowed actions + escalation override). Response:
`{"decision": {...}, "recommendation": {...}, "action": {...} | null, "validation": {...}}`.

### `GET /api/recommendations/awaiting-approval`
PENDING_REVIEW recommendations.

## Actions and verification

### `GET /api/actions/pending`
Actions with status `APPROVED` (not yet submitted) or `SUBMITTED` awaiting verification.

### `GET /api/actions/{action_id}`
Action with `outbound_payload`, `adapter_result`, latest verification.

### `POST /api/actions/{action_id}/submit`
Submits the outbound event through the synthetic adapter. Response: action with `status` `SUBMITTED` or
`FAILED` and `adapter_result` (`mode`, `accepted`, `system_reference`, `message`).

### `GET /api/actions/verification`
Verification results for all actions: `action_id, loan_id, action_type, verification_status,
matched_event_ids, differences, evaluated_on, cycle`.

### `POST /api/refresh`
Runs the next source refresh: increments the cycle, overlays visible System-of-Record events, re-evaluates the
portfolio, verifies submitted actions. Response: `{"refresh_cycle", "verification": {status: count},
"returned_to_queue": [action_id...], "evaluated_loans"}`.

## Evaluation and activity

### `GET /api/evaluation/summary`
`{"rule_metrics": {...}, "agent_metrics": {...}, "reviewer_metrics": {...}, "verification_metrics": {...},
"scenarios": [{scenario_id, loan_id, scenario_type, expected_*, actual_*, passed_*}], "synthetic": true}`.

### `GET /api/agent/activity`
Query: `loan_id, run_id, limit (default 300)`.

## Backend workflow

| Endpoint | Purpose |
|----------|---------|
| `POST /api/agent/batch` | `{"loan_ids": [...]}` or `{"limit": n}`: agent triage of several loans in parallel; proposals persist as PENDING_REVIEW. Response `{analyzed, seconds, results: [{loan_id, priority, condition, agent_mode, recommended_action, confidence, error}]}` |
| `GET /api/backend/status` | Schedule and recent runs of `lsi-pipeline` (Jobs API), `newer_than_app` |
| `POST /api/backend/run-pipeline` | Starts a run of `lsi-pipeline` (app service principal has CAN_MANAGE_RUN) |
| `GET /api/ai/backend` | AI created in Databricks: `insights` and `reviews` keyed by loan, and the portfolio `briefing` |
| `POST /api/agent/deployed/chat` | `{"messages": [...]}` to the deployed agent; returns answer, tool steps with rows, seconds |
| `GET /api/agent/deployment` | Endpoint status, model version, links, Unity Catalog tool catalog |
| `GET /api/backend/resources` | Inventory of Databricks resource links built from the runtime workspace host |
| `POST /api/reload` | Re-reads Silver and operational tables (after the workflow ran) |

## Operations

| Endpoint | Purpose |
|----------|---------|
| `GET /api/health` | `{"status": "ok", "backend": "local"|"databricks", "agent_mode", "processing_date"}` |
| `POST /api/demo/reset` | Demo mode only: clears recommendations, decisions, actions, verification, activity, SoR events; regenerates baseline recommendations |
| `GET /api/config/versions` | Rule, scoring, escalation, action, agent versions |
