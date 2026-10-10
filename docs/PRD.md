# Product Requirements Document — Loan Servicing Intelligence

> **Synthetic demonstration.** Every borrower, loan, property, specialist, vendor, event, rule, threshold,
> score, and metric in this product is synthetic. Nothing here represents any lender's production schema,
> servicing policy, legal process, or regulated decision framework.

**Product:** Loan Servicing Intelligence
**Subtitle:** Agent-powered portfolio monitoring and loan-servicing workflow automation
**Status:** Reference implementation v0.1.0
**Primary platform:** Azure Databricks (Delta Lake, Unity Catalog, serverless Jobs, serverless SQL, Databricks Apps, Foundation Model APIs)

---

## 1. Vision

Loan-servicing teams should not have to search for work. Loan Servicing Intelligence continuously evaluates an
entire portfolio, tells specialists which loans need attention and why, lets an AI agent do the investigative
legwork, and keeps people accountable for every consequential decision. The operational loan-servicing platform
remains the System of Record; this product monitors, prioritizes, explains, prepares, and verifies.

## 2. Context

The reference business acquires, services, improves, bundles, and sells portfolios of loans. Broad (synthetic)
objectives include improving acquired loan performance, resolving delinquency and default conditions, working
with borrowers, helping borrowers remain in their homes where practical, completing required operational and
legal-process activities on time, and improving portfolio value and marketability.

### 2.1 Current state (synthetic assumption)

Specialists review loans one at a time: open a loan, read its event history, work out the current milestone,
check completion and follow-up dates, decide whether something is upcoming, due, or overdue, create follow-up
events by hand, contact an attorney or vendor, and move on. Pain points: one-loan-at-a-time review, manual
event entry, late discovery of dates, unresolved overdue conditions, duplicate actions, data exceptions,
effort that scales linearly with volume, little portfolio visibility, and specialists searching for work.

### 2.2 Target state

A governed loop: synthetic exports land in a Databricks volume → Bronze/Silver/Gold Delta tables →
deterministic rules, escalation, and scoring → prioritized work queue → agent investigation through approved
tools → human review (approve/edit/reject/defer/escalate) → revalidation → outbound event via an adapter →
simulated System of Record update → next refresh → verification → failures return to the queue.

**Operating principle:** Agents perform investigative work. People remain accountable for consequential
decisions. The loan-servicing platform remains the operational System of Record.

## 3. Goals

| ID | Goal | Measure (synthetic) |
|----|------|---------------------|
| G1 | Portfolio-wide monitoring replaces one-at-a-time review | 100% of active loans evaluated every cycle |
| G2 | Specialists receive prioritized work, not searches | Every attention loan appears in the queue with score drivers |
| G3 | Objective checks are deterministic and auditable | Rule accuracy against the scenario manifest = 100% |
| G4 | AI accelerates investigation and drafting | Agent recommendation produced with evidence for every candidate analyzed |
| G5 | No consequential action without authorization | 0 outbound events without an APPROVE/EDIT decision |
| G6 | Closed-loop verification | Every submitted action reaches a verification status |
| G7 | Agent quality is measured separately from rule quality | Evaluation page reports both independently |

## 4. Non-goals

- Making lending, borrower-eligibility, legal, foreclosure-authority, compliance, loss-mitigation, or other
  regulated decisions.
- Providing legal or financial advice.
- Integrating with a real servicing platform, browser automation, or any production system.
- Representing any real organization's data model or process.
- Automatically changing rules, prompts, or behavior from individual reviewer feedback.

## 5. Personas

| Persona | Role code | Needs |
|---------|-----------|-------|
| Loan Servicing Specialist | `LOAN_SERVICING_SPECIALIST` | A prioritized queue, clear reasons, fast investigation, safe action preparation |
| Senior Specialist | `SENIOR_SPECIALIST` | Escalated loans, data exceptions, verification failures |
| Servicing Manager | `SERVICING_MANAGER` | Portfolio health, critical loans, workload, approval and verification throughput |
| Data / Platform Engineer | — | Reliable ingestion, data quality, reproducible pipelines, observability |
| AI / Quality Lead | — | Agent traces, evaluation metrics, safe improvement process |

## 6. User journeys

1. **Morning portfolio check (Manager):** Home → KPIs and portfolio-health segments → Today's Portfolio
   Briefing → drill into Critical segment → Priority Queue filtered to CRITICAL.
2. **Work the queue (Specialist):** Priority Queue → highest-priority loan → Loan 360 → event timeline →
   Agent Analysis → review evidence → Approve or Edit → outbound event prepared → submitted via adapter.
3. **Investigate a question (Specialist):** Loan 360 → Ask the Agent ("Why is this loan prioritized?") →
   answer citing tool facts.
4. **Close the loop (Specialist/Manager):** Refresh source → verification → VERIFIED actions drop out;
   FAILED / NOT_FOUND / MISMATCH / DUPLICATE actions return to the queue as VERIFICATION_FAILURE.
5. **Quality review (AI Lead):** Evaluation → rule accuracy vs agent agreement vs reviewer acceptance →
   Agent Activity traces.

## 7. User stories

| ID | Story | Acceptance |
|----|-------|-----------|
| US-01 | As a manager I see live portfolio KPIs | KPIs computed from Gold state; no hard-coded values |
| US-02 | As a manager I read a daily briefing grounded in facts | Briefing text contains only numbers present in briefing facts |
| US-03 | As a specialist I see why each loan is prioritized | Every queue row shows primary condition and top score drivers |
| US-04 | As a specialist I open a full loan view | Loan 360 shows header, overview, timeline, analysis, recommendations, activity |
| US-05 | As a specialist I get an agent recommendation with evidence | Recommendation includes action from allowed list, evidence, rationale, confidence, uncertainty, missing info |
| US-06 | As a specialist I approve, edit, reject, defer, or escalate | Decision persisted with reviewer, role, time, original, final, reason |
| US-07 | As a specialist I can trust approved actions are safe | Approved actions are revalidated (currency, duplicates, pending, fields, allowed) before an outbound event is generated |
| US-08 | As a specialist I see whether the action landed | Verification status shown after refresh; failures return to the queue |
| US-09 | As a specialist I can ask governed questions about a loan | Ask the Agent answers using tools and shows tool calls |
| US-10 | As an AI lead I evaluate rules and agent separately | Evaluation page shows rule accuracy and agent metrics separately |
| US-11 | As a presenter I can reset the demo | Reset clears recommendations, decisions, actions, verification, activity, SoR updates |

## 8. Functional requirements

### 8.1 Data
- FR-D1 Generate reproducible synthetic CSV exports (fixed seed) for ~1,500 loans and tens of thousands of events.
- FR-D2 Land files in a Unity Catalog volume (Databricks) or `data/landing` (local).
- FR-D3 Ingest to Bronze with `source_file`, `ingested_at`, `batch_id`, `record_hash`, `source_row_number`, preserving source values as strings.
- FR-D4 Build Silver with typing, deduplication, validation, normalization, joins, event ordering, milestone sequencing, active filtering, and data-quality flags.
- FR-D5 Build Gold portfolio, loan, milestone, attention, queue, recommendation, decision, action, verification, activity, evaluation, and briefing objects.

### 8.2 Rules, escalation, scoring
- FR-R1 Detect all thirteen conditions using configuration (`config/business_rules.yml`), allowing multiple raw conditions with a configurable primary.
- FR-R2 Compute escalation (`NONE/WATCH/FOLLOW_UP/ESCALATE/CRITICAL`), reasons, required role, and allowed actions.
- FR-R3 Compute a deterministic attention score (0–100), priority (`LOW/MEDIUM/HIGH/CRITICAL`), drivers, timestamp, and scoring version.
- FR-R4 Every rule has a documented identifier (`docs/BUSINESS_RULES.md`).

### 8.3 Agent
- FR-A1 One primary `LoanServicingAgent` interface with an LLM tool-calling implementation and a deterministic implementation.
- FR-A2 29 typed, logged, independently testable tools.
- FR-A3 Recommendations select only from allowed actions; numeric score, dates, statuses, and verification come only from tools.
- FR-A4 Recommendations carry evidence, rationale, confidence, uncertainty, missing information, tool calls, versions.
- FR-A5 Ask-the-Agent answers governed loan questions; portfolio briefing generated only from deterministic facts.
- FR-A6 On agent/tool failure: no action, failure recorded, clear status, routed to specialist review.

### 8.4 Review, action, verification
- FR-V1 Review decisions `APPROVE/EDIT/REJECT/DEFER/ESCALATE`, with edits to action, event type, follow-up date, note, outreach, escalation target, all revalidated.
- FR-V2 Approved actions revalidated, persisted, converted to an outbound servicing event, and submitted via `LoanServicingSystemAdapter` (`SyntheticServicingSystemAdapter`).
- FR-V3 Adapter modes: success, configured failure, mismatch, duplicate, delayed completion.
- FR-V4 Verification statuses `VERIFIED/NOT_FOUND/MISMATCH/DUPLICATE/FAILED/PENDING` with field differences; non-verified actions return to the queue.

### 8.5 Application and API
- FR-U1 Streamlit Databricks App with Home, Portfolio, Priority Queue, Loan 360, Agent Activity, Evaluation.
- FR-U2 Visible "Synthetic Demonstration Data" label on every page.
- FR-U3 UI talks to the agent and services only through the REST API boundary.
- FR-API1 Endpoints in `docs/API_SPECIFICATION.md`.

### 8.6 Evaluation, observability, demo
- FR-E1 Scenario manifest drives rule and agent evaluation; results stored in Gold.
- FR-O1 Structured activity logging of runs, tools, durations, results, versions, decisions, actions, verification; optional MLflow tracing.
- FR-DM1 `DEMO_MODE=true` uses fixed seed/date, synthetic adapter, configurable failures, and full reset.

## 9. Nonfunctional requirements

| ID | Requirement |
|----|-------------|
| NFR-1 | Modular: core logic in `src/`, notebooks orchestrate only |
| NFR-2 | Testable: unit, integration, end-to-end tests runnable locally without Databricks |
| NFR-3 | Configuration-driven rules, scoring, escalation, actions, scenarios |
| NFR-4 | Explainable: every condition, score point, and escalation carries a rule ID or driver |
| NFR-5 | Auditable: decisions, actions, verification, and tool calls persisted |
| NFR-6 | Safe by default: agent cannot commit actions; failure → no action |
| NFR-7 | Resilient: LLM unavailable → deterministic agent; Databricks unavailable → local backend |
| NFR-8 | Cost-aware: serverless compute, auto-stopping warehouse, pay-per-token model endpoints, app stopped when idle |
| NFR-9 | Customer-neutral: automated neutrality scan passes |
| NFR-10 | Performance: full-portfolio evaluation of 1,500 loans in < 5 s in-process |
| NFR-11 | Privacy: no secrets, credentials, hidden prompts, or chain-of-thought in logs or UI |

## 10. Agent requirements

The agent must: receive a question or candidate; choose tools; call them; inspect structured results; gather
more context when needed; judge evidence sufficiency; choose only from allowed actions; explain and cite
evidence; state uncertainty and missing information; prepare an uncommitted action; wait for authorization;
preserve an activity trace. It must not: modify the System of Record, bypass validation, override escalation,
invent data or metrics, calculate the numeric score, recommend disallowed actions, execute without approval,
or change production behavior from individual feedback. Details: `docs/AGENT_DESIGN.md`.

## 11. Application requirements

See `docs/APP_UX_SPECIFICATION.md`. Summary: dynamic KPIs, interactive health segments, fact-grounded briefing,
priority preview, filterable portfolio and queue tables linking to Loan 360, Loan 360 tabs (Overview, Events,
Agent Analysis, Recommendations, Activity), review controls, Ask the Agent, Agent Activity traces, Evaluation.

## 12. Acceptance criteria

1. `pytest` passes locally (unit, integration, end-to-end).
2. All 20 scenario-manifest loans produce the expected condition, priority, action, and verification status.
3. The end-to-end test completes: files → ingestion → rules → score → recommendation → approval → outbound →
   adapter → refresh → verification.
4. The Databricks pipeline job runs on serverless compute and creates all Bronze/Silver/Gold tables.
5. The Databricks App renders all six pages with the synthetic label, reading from the Databricks backend.
6. No outbound event exists without a corresponding APPROVE or EDIT decision.
7. The customer-neutrality scan reports zero findings.

## 13. Assumptions

See `docs/ASSUMPTIONS_AND_LIMITATIONS.md`. Key: fixed processing date in demo mode (2026-10-12); generic
synthetic milestone sequence; single assigned external party per loan; one-way synthetic adapter.

## 14. Limitations

No real integrations, no browser automation, no regulated decisions, synthetic rules only, in-process API in
the app container, single-tenant demo authorization model (reviewer identity is selected, not authenticated
per role). Production use would require security, privacy, legal, compliance, operational, and integration review.

## 15. Future considerations

- Agent Bricks / Mosaic AI Agent Framework deployment of the agent behind a serving endpoint.
- Unity Catalog functions as the authoritative tool layer for SQL clients and MCP.
- Lakeflow Declarative Pipelines for incremental ingestion.
- Role-based authorization using Databricks App user identity (OBO) and UC row filters.
- Feedback-driven offline improvement loop with gated promotion.
- Workload balancing and specialist assignment recommendations.
