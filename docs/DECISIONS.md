# Architecture Decision Records — Loan Servicing Intelligence

Format: identifier, status, date documented, context, options, decision, rationale, consequences.

---

## ADR-001 — Azure Databricks as the primary platform, serverless-first
- **Status:** Accepted · **Documented:** 2026-10-10
- **Context:** The reference application targets Azure Databricks and must be cheap to keep around between demos.
- **Options:** (a) classic clusters + provisioned endpoints; (b) serverless Jobs, serverless SQL, pay-per-token model APIs, Databricks Apps.
- **Decision:** (b). Pipeline runs as a serverless job; the app uses a serverless SQL warehouse with 10-minute auto-stop; the LLM is a pay-per-token Foundation Model API endpoint.
- **Rationale:** Scales to zero for everything except the App, which is stopped when idle.
- **Consequences:** First query after idle waits for warehouse start; the App must be started before a demo.

## ADR-002 — Core logic in a plain Python package; notebooks orchestrate
- **Status:** Accepted · **Documented:** 2026-10-10
- **Context:** Logic must be testable locally and reused by notebooks, API, and app.
- **Options:** (a) logic in notebooks; (b) `src/` package imported by notebooks from the Git folder.
- **Decision:** (b).
- **Rationale:** Unit/integration tests without a cluster; single source of truth.
- **Consequences:** Notebooks add the repo root to `sys.path`; Git folder must be pulled after pushes.

## ADR-003 — pandas for Silver/Gold logic at demo scale; Spark for ingestion and persistence
- **Status:** Accepted · **Documented:** 2026-10-10
- **Context:** ~1,500 loans and ~30k events. Rules are row-wise and benefit from straightforward Python.
- **Options:** (a) all Spark SQL; (b) shared pandas functions used by both notebooks (via `toPandas`) and the app; (c) duplicate logic in Spark and Python.
- **Decision:** (b). Bronze ingestion uses Spark's CSV reader on the volume; Silver/Gold transformations call shared pandas functions and write Delta with Spark.
- **Rationale:** One implementation, identical results in pipeline, app, and tests.
- **Consequences:** Not suited to very large portfolios; documented as a limitation with a Spark/Lakeflow path in the backlog.

## ADR-004 — Framework-neutral `LoanServicingAgent` with an `LlmClient` adapter
- **Status:** Accepted · **Documented:** 2026-10-10
- **Context:** Avoid coupling business logic to one proprietary agent framework.
- **Options:** (a) LangGraph/other framework; (b) Agent Bricks only; (c) internal interface + thin OpenAI-compatible tool-calling loop + adapters.
- **Decision:** (c). `DatabricksFoundationModelClient` calls serving endpoints through the Databricks SDK; a scripted client supports tests. Agent Bricks / Mosaic AI deployment is a future adapter.
- **Rationale:** Portable, testable, minimal dependencies; Databricks endpoints speak the OpenAI chat format.
- **Consequences:** We maintain a small loop (iteration cap, guardrail completion) ourselves.

## ADR-005 — Deterministic facts, AI narrative; guardrail completion and enforcement
- **Status:** Accepted · **Documented:** 2026-10-10
- **Context:** Objective checks must be deterministic; the model must not invent data or choose disallowed actions.
- **Decision:** All conditions, scores, escalation, allowed actions, dates, validation, and verification come from tools. The model chooses among allowed actions and writes narrative. `RecommendationBuilder` runs any mandatory tool the model skipped and replaces disallowed choices with the deterministic default.
- **Consequences:** LLM variability is confined to choice-within-allowed and text.

## ADR-006 — Deterministic agent as fallback and pipeline baseline
- **Status:** Accepted · **Documented:** 2026-10-10
- **Context:** The demo must work when the model is slow/unavailable; the queue needs recommendations without paying for LLM calls on every loan.
- **Decision:** `DeterministicLoanServicingAgent` produces baseline recommendations for all attention candidates in the pipeline; the LLM agent runs on demand in Loan 360 (and optionally in batch). `auto` mode falls back per request.
- **Consequences:** Two agent versions appear in data (`lsa-0.1.0-deterministic`, `lsa-0.1.0-llm`); evaluation reports both.

## ADR-007 — In-process FastAPI inside the Databricks App
- **Status:** Accepted · **Documented:** 2026-10-10
- **Context:** The UI must call the agent through an API boundary; Databricks Apps expose one port.
- **Options:** (a) separate API app; (b) Streamlit calling services directly; (c) FastAPI on a daemon thread in the Streamlit process, UI uses HTTP.
- **Decision:** (c), with an in-process ASGI transport fallback.
- **Rationale:** Real API contract, shared state, single app to run and stop.
- **Consequences:** API not externally exposed in the demo; can be split into its own app later without UI changes.

## ADR-008 — Repository abstraction with local and Databricks SQL backends
- **Status:** Accepted · **Documented:** 2026-10-10
- **Context:** Same app must run locally (tests, offline) and on Databricks.
- **Decision:** `ServicingRepository` with `LocalRepository` (CSV/JSONL) and `DatabricksSqlRepository` (Statement Execution API via databricks-sdk against a serverless warehouse; parameterized writes to Delta).
- **Consequences:** The app loads Silver + ops tables once and evaluates in-process; writes are write-through.

## ADR-009 — Operational tables separate from analytic Gold
- **Status:** Accepted · **Documented:** 2026-10-10
- **Context:** The app writes recommendations, decisions, actions, verification, and activity; the pipeline rebuilds Gold.
- **Decision:** App writes `ops_*` and `sor_servicing_events`; Gold recommendation/decision/activity objects are built from history + ops tables.
- **Consequences:** Pipeline reruns never destroy human decisions (except explicit demo reset).

## ADR-010 — Verification by matching adapter events in the next refresh
- **Status:** Accepted · **Documented:** 2026-10-10
- **Context:** Approved actions must be verified against the System of Record, not against the adapter's own response.
- **Decision:** The adapter writes to a simulated SoR table with an availability cycle; the refresh overlays visible rows onto events (upsert by `event_id` + latest `updated_at`); the verifier matches on loan, event type, source, and time, then compares fields.
- **Consequences:** Supports VERIFIED/PENDING/NOT_FOUND/MISMATCH/DUPLICATE/FAILED deterministically.

## ADR-011 — Fixed processing date and seed in demo mode
- **Status:** Accepted · **Documented:** 2026-10-10
- **Decision:** Processing date 2026-10-12 and seed 20261012 (`config/application.yml`), overridable by env.
- **Consequences:** Scenario expectations are stable across days and environments.

## ADR-012 — Briefing number guard
- **Status:** Accepted · **Documented:** 2026-10-10
- **Context:** "No invented metrics" in the AI briefing.
- **Decision:** Reject any LLM briefing containing a number not present in the deterministic facts; fall back to the templated briefing.
- **Consequences:** Occasional fallback; zero invented numbers.

## ADR-014 — Recurring serverless "servicing monitor" workflow as the backend
- **Status:** Accepted · **Documented:** 2026-10-11
- **Context:** The demo needs automation that runs in Databricks without the app: continuous re-evaluation, verification, and agent work behind the scenes.
- **Options:** (a) app-only processing; (b) Lakeflow Declarative Pipelines; (c) a Databricks Workflow of notebook tasks reusing `src/`.
- **Decision:** (c) `lsi-servicing-monitor`: ingest -> silver -> refresh & verify -> rules & scores (gold) -> agent triage + AI Functions (parallel). Serverless, scheduled every 30 minutes (created paused; unpause for demo days). The setup pipeline `lsi-pipeline` remains for (re)generating data.
- **Rationale:** Same code as the app (one implementation); visible DAG and run history in the Databricks UI; scales to zero between runs.
- **Consequences:** The app reads workflow results on sync (`POST /api/reload`); the sidebar shows run status, Run now, and Sync. Agent triage skips demo spotlight loans so the live demo moment is preserved.

## ADR-015 — AI Functions for SQL-native summaries
- **Status:** Accepted · **Documented:** 2026-10-11
- **Decision:** `ai_query('<endpoint>', prompt)` in the workflow writes `gold_ai_loan_insights` and `gold_ai_portfolio_briefing` from deterministic Gold facts.
- **Rationale:** Shows Databricks AI Functions directly over governed tables, complementary to the tool-calling agent.
- **Consequences:** Outputs are informational only (labeled AI-generated); no decision depends on them.

## ADR-013 — Customer-neutrality scanner with external denylist
- **Status:** Accepted · **Documented:** 2026-10-10
- **Context:** The repository must be provably customer-neutral without embedding the terms it guards against.
- **Decision:** `src/quality/neutrality.py` scans for generic risk patterns (emails, non-allowlisted URLs/hosts, phone/SSN-like patterns, street addresses, production-claim phrases) plus an optional denylist supplied via `LSI_NEUTRALITY_DENYLIST` (env/file outside the repo).
- **Consequences:** Generic checks always run in tests; organization-specific terms can be checked privately.
