# Implementation Plan — Loan Servicing Intelligence

Status legend: ✅ done · 🔄 in progress · ⏳ planned. Each stage keeps the repository runnable and tested.

| Stage | Scope | Deliverables | Tests | Status |
|-------|-------|--------------|-------|--------|
| 1 | Document and design | `README.md`, 16 docs, ADRs, config | — | ✅ |
| 2 | Synthetic data + manifest | `src/data_generation`, `data/generated/*.csv` | `tests/unit/test_data_generation.py` | ⏳ |
| 3 | Medallion foundation | `src/ingestion`, `src/transformations`, `sql/*.sql`, notebooks 01–04 | `tests/integration/test_pipeline.py` | ⏳ |
| 4 | Deterministic logic + tools | `src/rules`, `src/scoring`, `src/verification`, `src/tools`, engine | unit tests per module, `test_scenario_manifest.py` | ⏳ |
| 5 | Agent + tracing | `src/agents`, `src/services/activity.py`, `tracing.py` | `test_agents.py`, `test_agent_tools_interaction.py` | ⏳ |
| 6 | Review, adapter, verification | `review_service`, `action_service`, `refresh_service`, `src/adapters` | `test_review_action.py`, `test_adapter.py`, e2e | ⏳ |
| 7 | API + App | `src/api`, `app/` | `test_api.py` | ⏳ |
| 8 | Evaluation, reset, neutrality, deployment | `src/evaluation`, `src/quality`, notebooks 05–07, scripts, app deployment | `test_evaluation.py`, `test_customer_neutrality.py` | ⏳ |

## Engineering conventions

- Core logic in `src/`; notebooks are thin orchestrators.
- Pure functions over plain dicts/DataFrames for rules and scoring; Pydantic for API and agent schemas.
- Config read once per process via `src/config/settings.py`; environment overrides documented in `.env.example`.
- No new dependency without need: pandas, PyYAML, pydantic, FastAPI, Streamlit, httpx; databricks-sdk only for
  the Databricks backend and LLM client.
- Every rule ID referenced in code appears in `docs/BUSINESS_RULES.md`.

## Running the stages locally

```bash
python -m src.data_generation.generator
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
