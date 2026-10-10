# Architecture — Loan Servicing Intelligence

> Synthetic demonstration. No production system is integrated.

## 1. Logical architecture

```text
Synthetic loan-servicing export files (src/data_generation)
        -> Databricks landing volume  (/Volumes/<catalog>/<schema>/landing)   | local: data/landing
        -> file ingestion             (src/ingestion/bronze.py, notebooks/02)
        -> Bronze Delta tables        (bronze_*: raw strings + lineage columns)
        -> validation/standardization (src/transformations/silver.py, notebooks/03)
        -> Silver Delta tables        (silver_*: typed, deduplicated, sequenced, DQ-flagged)
        -> business rules & portfolio calculations (src/rules, src/scoring, src/verification,
                                        src/services/portfolio_engine.py, notebooks/04)
        -> Gold Delta tables/views    (gold_*)
        -> deterministic servicing tools (src/tools; UC SQL functions via notebooks/05)
        -> Loan Servicing Agent       (src/agents: tool-calling LLM agent + deterministic agent)
        -> agent REST API             (src/api: FastAPI)
        -> Databricks App             (app/: Streamlit, calls the API only)
        -> human review & authorization (src/services/review_service.py)
        -> SyntheticServicingSystemAdapter (src/adapters)
        -> outbound servicing event   (ops_actions.outbound_payload; data/outbound/*.json locally)
        -> simulated System of Record (sor_servicing_events)
        -> next source refresh        (src/services/refresh_service.py, notebooks/03)
        -> action verification        (src/verification/verifier.py)
        -> verified result or returned exception (VERIFICATION_FAILURE back in the queue)
```

## 2. Layered component view

| Layer | Package | Responsibility |
|-------|---------|----------------|
| Configuration | `src/config` | Load YAML config with environment overrides; expose typed accessors |
| Models | `src/models` | Pydantic schemas: recommendations, evidence, decisions, actions, verification, tool calls, API payloads |
| Data generation | `src/data_generation` | Deterministic synthetic CSVs + scenario manifest |
| Ingestion | `src/ingestion` | Bronze construction (pandas locally; Spark in notebooks) with lineage columns |
| Transformations | `src/transformations` | Silver standardization/DQ; System-of-Record overlay; Gold table assembly |
| Rules | `src/rules` | Loan facts, conditions, escalation, allowed actions, validation, follow-up dates |
| Scoring | `src/scoring` | Attention score, priority, drivers |
| Verification | `src/verification` | Match approved actions to refreshed events; statuses and differences |
| Repositories | `src/repositories` | `ServicingRepository` interface; `LocalRepository`, `DatabricksSqlRepository` |
| Tools | `src/tools` | 29 typed tools + registry + executor with logging |
| Agents | `src/agents` | `LoanServicingAgent` interface, LLM client adapters, tool-calling agent, deterministic agent, recommendation builder, prompts |
| Services | `src/services` | Portfolio engine, servicing facade, review, action, refresh, briefing, activity/tracing |
| Adapters | `src/adapters` | `LoanServicingSystemAdapter` interface; `SyntheticServicingSystemAdapter` |
| Evaluation | `src/evaluation` | Rule and agent evaluation against the scenario manifest |
| Quality | `src/quality` | Customer-neutrality scanner |
| API | `src/api` | FastAPI app exposing the service facade |
| UI | `app/` | Streamlit pages/components; HTTP client to the API |

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

## 4. Runtime topology of the app

The App container runs one Streamlit process. On first load, Streamlit starts the FastAPI app (uvicorn) on a
daemon thread bound to `127.0.0.1:${LSI_API_PORT}`. Pages call the API with `httpx` through `app/state.py`'s
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
