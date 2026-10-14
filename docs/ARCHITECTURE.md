# Architecture — Loan Servicing Intelligence

> Synthetic demonstration. No production system is integrated.

## 1. Logical architecture

```text
Synthetic loan-servicing export files (src/synthetic_data.py)
        -> Databricks landing volume  (/Volumes/<catalog>/<schema>/landing)   | local: data/landing
        -> file ingestion             (src/medallion.py, notebooks/02)
        -> Bronze Delta tables        (bronze_*: raw strings + lineage columns)
        -> validation/standardization (src/medallion.py, notebooks/03)
        -> Silver Delta tables        (silver_*: typed, deduplicated, sequenced, DQ-flagged)
        -> business rules & portfolio calculations (src/rules, src/scoring, src/verification,
                                        src/rules.py, notebooks/04)
        -> Gold Delta tables/views    (gold_*)
        -> deterministic servicing tools (src/tools; UC SQL functions via notebooks/05)
        -> Loan Servicing Agent       (src/agent.py: tool-calling LLM agent + deterministic agent)
        -> agent REST API             (src/api.py: FastAPI)
        -> Databricks App             (app/: Streamlit, calls the API only)
        -> human review & authorization (src/service.py)
        -> SyntheticServicingSystemAdapter (src/service.py)
        -> outbound servicing event   (ops_actions.outbound_payload; data/outbound/*.json locally)
        -> simulated System of Record (sor_servicing_events)
        -> next source refresh        (src/service.py, notebooks/03)
        -> action verification        (src/rules.py)
        -> verified result or returned exception (VERIFICATION_FAILURE back in the queue)
```

## 2. Code layout (one module per concept)

The code is deliberately flat so a reader can follow a whole concept in one file.

| Module | What lives there |
|--------|------------------|
| `src/config.py` | YAML config loading with environment overrides |
| `src/synthetic_data.py` | Deterministic synthetic exports and the scenario manifest |
| `src/medallion.py` | Bronze (raw + lineage), Silver (typed, validated), Gold table assembly |
| `src/rules.py` | **The whole rules engine**: loan facts, conditions, escalation, scoring, allowed actions, follow-up dates, validation, verification, portfolio evaluation |
| `src/tools.py` | 29 agent tools, registry, executor; Unity Catalog SQL tool functions |
| `src/agent.py` | Prompts, LLM client, deterministic and tool-calling agents, recommendation guardrails, briefing |
| `src/service.py` | `LoanServicingService` facade: analysis, review, actions, synthetic adapter, refresh, activity |
| `src/storage.py` | Operational state and storage backends (local files, Databricks SQL, Spark) |
| `src/evaluation.py` | Rule / agent / reviewer / verification metrics |
| `src/databricks.py` | Workflow status, resource links, deployed-agent client, agent deployment |
| `src/pipeline.py` | Steps called by the Databricks notebooks |
| `src/api.py`, `src/models.py` | REST API and request schemas |
| `src/neutrality.py` | Customer-neutrality scanner |
| `agent_endpoint/loan_servicing_agent.py` | The deployable Databricks agent (self-contained) |
| `app/main.py`, `app/navigation.py` | Streamlit entry point, navigation, header, sidebar |
| `app/client.py` | REST client and in-process API server bootstrap |
| `app/ui.py` | Shared UI building blocks (loan lists, timeline, agent proposal, review panel, talk track) |
| `app/pages/*.py` | One file per page |

## 3. Physical architecture on Azure Databricks

```text
 Git folder (/Workspace/Users/<you>/AIWorkflowAutomationDemo)  <-- pull from GitHub
   |
   |-- Serverless Job "lsi-pipeline" (notebook tasks, serverless compute, scales to zero)
   |      01_generate_demo_data -> 02_ingest_bronze -> 03_build_silver -> 04_build_gold
   |      -> 05_register_agent_tools -> 06_run_evaluation        (07_reset_demo on demand)
   |      writes: UC volume  main.loan_servicing_intelligence.landing
   |              Delta      main.loan_servicing_intelligence.{bronze_*, silver_*, gold_*, ops_*, sor_*}
   |              UC funcs   main.loan_servicing_intelligence.lsi_*
   |
   |-- Databricks App "loan-servicing-intelligence" (Streamlit + in-process FastAPI)
   |      resources: serverless SQL warehouse (CAN_USE, auto-stop 10 min)
   |                 serving endpoint databricks-claude-sonnet-5-5 (CAN_QUERY, pay-per-token)
   |      auth: app service principal (UC grants on the schema)
   |
   '-- MLflow experiment (evaluation runs; optional tracing)
```

**Scale-to-zero posture.** Pipeline compute is serverless (billed only while tasks run). The SQL warehouse is
serverless with a 10-minute auto-stop. The LLM is a pay-per-token Foundation Model API endpoint (no
provisioned throughput). Databricks Apps do not auto-suspend, so the app is stopped when not presenting
(`databricks apps stop loan-servicing-intelligence`).

## 3a. Always-on backend workflow

```text
lsi-servicing-monitor (serverless, every 30 min; created paused)
  ingest (02) -> silver (03) -> refresh_verify (09) -> rules_and_scores (04) -> agent_triage (08)
                                                                           -> ai_insights (10, ai_query)
```

- **ingest / silver:** new servicing exports in the landing volume flow to Bronze and Silver.
- **refresh_verify:** advances the refresh cycle, applies System-of-Record events, verifies submitted actions.
- **rules_and_scores:** full re-evaluation into Gold (conditions, escalation, scores, queue, verification).
- **agent_triage:** the tool-calling agent (Claude via Foundation Model API) investigates the highest-priority
  loans without a current AI proposal; proposals wait for human approval.
- **ai_insights:** Databricks AI Functions (`ai_query`) write per-loan summaries and a portfolio briefing.

The app shows run status, can start a run (job resource with CAN_MANAGE_RUN), and syncs results.

## 4. Runtime topology of the app

The App container runs one Streamlit process. On first load, Streamlit starts the FastAPI app (uvicorn) on a
daemon thread bound to `127.0.0.1:${LSI_API_PORT}`. Pages call the API with `httpx` through `app/client.py`'s
`ApiClient`. Both share one `LoanServicingService` singleton, so the API boundary is real (serialization,
validation, status codes) while state stays consistent. If the server cannot bind, the client falls back to an
in-process ASGI transport against the same FastAPI app — the UI still goes through the API contract.

The API can also be run standalone: `uvicorn src.api.main:app --port 8001`.

## 5. State model

| Store | Written by | Contents |
|-------|-----------|----------|
| `bronze_*` | pipeline | Raw export rows with lineage |
| `silver_*` | pipeline | Standardized source data (+ applied System-of-Record events) |
| `gold_*` | pipeline | Analytic state (portfolio, queue, verification, evaluation, briefing facts) |
| `ops_recommendations` | pipeline (baseline batch), app | Agent recommendations |
| `ops_reviewer_decisions` | app | Human decisions |
| `ops_actions` | app | Approved actions, outbound payloads, adapter results |
| `ops_verification_results` | app, pipeline | Verification outcomes per refresh |
| `ops_agent_activity` | app, pipeline | Tool-call and step traces |
| `sor_servicing_events` | synthetic adapter | Simulated System of Record event writes (with availability cycle) |
| `ops_runtime_state` | app | Refresh cycle counter |

The app loads Silver + ops tables once, evaluates the portfolio in-process with the same engine the pipeline
uses, and writes through to Delta on every change. Locally the same interfaces persist to CSV/JSONL under
`data/processed/state`.

## 6. Key sequences

### 6.1 Agent assessment
```text
UI -> POST /api/agent {mode: assess, loan_id}
  -> LoanServicingService.analyze_loan
     -> agent.assess_loan (LLM chooses tools | deterministic plan)
        -> ToolExecutor.call(tool) x N  (each logged to activity)
     -> RecommendationBuilder: merge tool facts + narrative; enforce allowed action; prepare + validate event
  <- Recommendation (status PENDING_REVIEW, requires_human_approval = true)
```

### 6.2 Approval to verification
```text
POST /api/recommendations/{id}/decision {APPROVE|EDIT}
  -> ReviewService: persist decision -> ActionService.revalidate (currency, duplicate, pending, fields, allowed)
  -> persist action (APPROVED) + outbound event payload
POST /api/actions/{id}/submit -> SyntheticServicingSystemAdapter.submit -> SoR rows (mode: success/fail/
     mismatch/duplicate/delayed) -> action SUBMITTED | FAILED
POST /api/refresh -> cycle+1 -> overlay visible SoR rows onto events -> re-evaluate portfolio
     -> Verifier: VERIFIED | PENDING | NOT_FOUND | MISMATCH | DUPLICATE | FAILED
     -> non-verified -> VERIFICATION_FAILURE condition -> back in Priority Queue
```

## 7. Deterministic vs AI boundary

| Deterministic (tools/engine) | AI (agent) |
|------------------------------|-----------|
| Dates, day counts, statuses | Tool selection and investigation order |
| Milestone ordering and completion | Evidence synthesis and ambiguity handling |
| Duplicate / pending / rejection checks | Recommendation choice **within** allowed actions |
| Rule lookup, escalation, allowed actions | Rationale and explanation |
| Attention score, priority, drivers | Note and outreach drafting |
| Validation and verification | Portfolio briefing narrative (fact-checked) |

## 8. Portability

Core logic depends only on Python, pandas, PyYAML, and pydantic. The agent runtime is behind
`LlmClient` (Databricks Foundation Model API implementation; scripted client for tests). Storage is behind
`ServicingRepository`. The System of Record is behind `LoanServicingSystemAdapter`. Replacing any of these
does not change rules, scoring, tools, or UI.

## 9. Security considerations (demo)

- No credentials in code or config; Databricks SDK unified auth (profile locally, service principal in the App).
- App service principal receives least-privilege UC grants on one schema plus CAN_USE / CAN_QUERY on the
  warehouse and model endpoint.
- Activity traces store summarized tool inputs/outputs only; no prompts, secrets, or chain-of-thought.
- SQL writes from the app use escaped string literals in `MERGE` statements (all operational columns are strings); the pipeline writes through Spark DataFrames.
