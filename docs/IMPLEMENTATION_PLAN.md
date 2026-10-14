# Implementation Plan — Loan Servicing Intelligence

Status legend: Done, In progress, Planned. Each stage keeps the repository runnable and tested.

| Stage | Scope | Deliverables | Tests | Status |
|-------|-------|--------------|-------|--------|
| 1 | Document and design | `README.md`, 16 docs, ADRs, config | — | Done |
| 2 | Synthetic data + manifest | `src/synthetic_data.py`, `data/generated/*.csv` | `tests/unit/test_data_generation.py` | Done |
| 3 | Medallion foundation | `src/medallion.py`, `src/medallion.py`, `sql/*.sql`, notebooks 01–04 | `tests/integration/test_pipeline.py` | Done |
| 4 | Deterministic logic + tools | `src/rules`, `src/scoring`, `src/verification`, `src/tools`, engine | unit tests per module, `test_scenario_manifest.py` | Done |
| 5 | Agent + tracing | `src/agent.py`, `src/service.py`, `tracing.py` | `test_agents.py`, `test_agent_tools_interaction.py` | Done |
| 6 | Review, adapter, verification | `review_service`, `action_service`, `refresh_service`, `src/service.py` | `test_review_action.py`, `test_adapter.py`, e2e | Done |
| 7 | API + App | `src/api.py`, `app/` | `test_api.py` | Done |
| 8 | Evaluation, reset, neutrality, deployment | `src/evaluation.py`, `src/neutrality.py`, notebooks 05–07, scripts, app deployment | `test_evaluation.py`, `test_customer_neutrality.py` | Done |

## Verification status (2026-10-10)

- `pytest`: 127 tests pass (unit, integration, end-to-end); scenario manifest rule accuracy 100%.
- Customer-neutrality scan: 0 findings.
- Databricks: serverless job `lsi-pipeline` succeeded end to end (generate, bronze, silver, gold, UC tools, evaluation).
- Databricks App `loan-servicing-intelligence` deployed from the Git folder (Databricks SQL backend, LLM agent in auto mode).
- LLM agent verified against `databricks-claude-sonnet-5-5` (tool selection, recommendation, Ask the Agent, briefing).

## Engineering conventions

- Core logic in `src/`; notebooks are thin orchestrators.
- Pure functions over plain dicts/DataFrames for rules and scoring; Pydantic for API and agent schemas.
- Config read once per process via `src/config.py`; environment overrides documented in `.env.example`.
- No new dependency without need: pandas, PyYAML, pydantic, FastAPI, Streamlit, httpx; databricks-sdk only for
  the Databricks backend and LLM client.
- Every rule ID referenced in code appears in `docs/BUSINESS_RULES.md`.

## Running the stages locally

```bash
python -m src.synthetic_data
pytest tests/unit
pytest tests/integration tests/end_to_end
streamlit run app/main.py
```

## Next increments (backlog)

1. Agent Bricks / Mosaic AI Agent Framework packaging of `ToolCallingLoanServicingAgent` behind a serving endpoint.
2. Lakeflow Declarative Pipelines for Bronze/Silver with expectations.
3. OBO user identity in the app and role enforcement.
4. Workload-balancing recommendations.
5. Lakeview dashboard over Gold tables.
