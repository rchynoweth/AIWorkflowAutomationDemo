# Databricks Deployment — Loan Servicing Intelligence

> Synthetic demonstration. Placeholders: `<workspace-host>`, `<you>`, `<warehouse-id>`. Do not commit real
> hosts, tokens, or identities.

## 1. Cost posture: serverless and scale-to-zero

| Component | Compute | Idle cost |
|-----------|---------|-----------|
| Pipeline job `lsi-pipeline` | Serverless Jobs compute | None (billed per run) |
| SQL warehouse (app reads/writes) | Serverless SQL, Small, max 1 cluster, **auto-stop 10 min** | None after auto-stop |
| LLM | Foundation Model API **pay-per-token** (`databricks-claude-sonnet-5-5`) | None |
| Databricks App | App compute (Medium) | **Runs while started** — stop when not presenting |
| Storage | Delta tables + one UC volume | Storage only |

Databricks Apps do not auto-suspend, so the app is deployed and then **stopped**; start it before a demo.

## 2. Prerequisites

- Unity Catalog-enabled Azure Databricks workspace with serverless compute for Jobs and SQL.
- Permission to create a schema in the target catalog (default `main`), a volume, tables, and functions.
- Databricks CLI ≥ 0.230 authenticated (`databricks auth login --host <workspace-host>`).
- A serverless SQL warehouse (the "Serverless Starter Warehouse" works).

## 3. Source: Git folder

The workspace runs code from a Databricks Git folder linked to the GitHub repository:

```
/Workspace/Users/<you>/AIWorkflowAutomationDemo
```

Workflow: develop locally → `git push` → in Databricks, open the Git folder and **Pull** (or
`databricks repos update <repo-id> --branch main`). Notebooks add the repository root to `sys.path` and import
`src/` modules directly.

## 4. Pipeline (serverless job)

Notebooks (Databricks source format, `notebooks/`), parameterized by widgets `catalog`, `schema`,
`processing_date`, `reset`:

| Task | Notebook | Output |
|------|----------|--------|
| generate | `01_generate_demo_data` | Creates schema + volume; writes synthetic CSVs to `/Volumes/<catalog>/<schema>/landing/<batch>` |
| bronze | `02_ingest_bronze` | `bronze_*` with lineage columns (Spark CSV reader, all strings) |
| silver | `03_build_silver` | `silver_*` (shared `src/medallion.py`; overlays `sor_servicing_events`) |
| gold | `04_build_gold` | `gold_*`, baseline recommendations in `ops_recommendations`, verification results |
| tools | `05_register_agent_tools` | UC SQL functions `lsi_*` |
| evaluate | `06_run_evaluation` | `gold_agent_evaluation`, MLflow run |
| reset (manual) | `07_reset_demo` | Truncates ops/SoR tables, rebuilds silver/gold |

Create the job (serverless — no cluster spec), pointing at the Git folder:

```bash
python scripts/create_pipeline_job.py --repo-path /Workspace/Users/<you>/AIWorkflowAutomationDemo \
       --catalog main --schema loan_servicing_intelligence
databricks jobs run-now <job-id>
```

Alternatively deploy with Databricks Asset Bundles (`databricks.yml`, also serverless):
`databricks bundle deploy -t dev && databricks bundle run lsi_pipeline -t dev`.

## 4a. The lsi-pipeline workflow

`python scripts/create_pipeline_job.py --repo-path ... [--run]` creates one serverless job:
`generate -> bronze -> silver -> gold -> (tools, ai_functions) -> agent_reviews`. Notebook 06 creates
`gold_ai_loan_insights` and `gold_ai_portfolio_briefing` with `ai_query`; notebook 07 calls the deployed agent and
writes `gold_agent_loan_reviews`. The 30-minute schedule is created paused.

**Tool functions and the agent:** the agent's credentials are scoped to the functions declared when it was
deployed. Notebook 05 therefore creates only missing functions; if you change tool definitions, run it with
`replace_tools=true` and then redeploy the agent (notebook 08). Notebook 07 fails loudly if the agent cannot use
its tools.

## 4b. Deployed agent

1. Register tools: `python scripts/register_uc_tools.py --warehouse-id <id>` (or notebook 05).
2. Run `notebooks/08_deploy_agent.py` (serverless, widget `warehouse_id`): logs the ResponsesAgent, registers
   `main.loan_servicing_intelligence.loan_servicing_agent`, deploys endpoint `loan-servicing-agent`
   (scale-to-zero, about 15-20 minutes the first time).
3. Re-run `scripts/deploy_app.py` so the app gets CAN_QUERY on the endpoint and EXECUTE on the schema.
4. Before a demo, send one question from *Meet the Agent* or the Playground to wake the endpoint.

## 5. App

`app.yaml` runs `streamlit run app/main.py`; Streamlit starts the in-process FastAPI on `127.0.0.1:8001`.
Environment: `LSI_REPOSITORY_BACKEND=databricks`, `LSI_CATALOG`, `LSI_SCHEMA`, `DATABRICKS_WAREHOUSE_ID`
(from the `sql-warehouse` resource), `LSI_MODEL_ENDPOINT` (from the `serving-endpoint` resource),
`DEMO_MODE=true`.

```bash
python scripts/deploy_app.py --repo-path /Workspace/Users/<you>/AIWorkflowAutomationDemo \
       --warehouse-id <warehouse-id> --catalog main --schema loan_servicing_intelligence
```

The script (idempotent):
1. Creates the app `loan-servicing-intelligence` with resources: SQL warehouse (`CAN_USE`) and serving
   endpoint `databricks-claude-sonnet-5-5` (`CAN_QUERY`).
2. Grants the app service principal `USE CATALOG` on the catalog and `USE SCHEMA, SELECT, MODIFY` on the
   schema (plus `CREATE TABLE` for first-run ops tables).
3. Deploys from the Git folder path.
4. Stops the app unless `--keep-running`.

Manual equivalents:
```bash
databricks apps create loan-servicing-intelligence
databricks apps deploy loan-servicing-intelligence --source-code-path /Workspace/Users/<you>/AIWorkflowAutomationDemo
databricks apps start  loan-servicing-intelligence
databricks apps stop   loan-servicing-intelligence
```

## 6. Operating guidance

- **Before a demo:** start the app, open it to warm the warehouse, Reset demo.
- **After a demo:** stop the app.
- **Code change:** push → pull Git folder → `databricks apps deploy …` (app) and/or re-run the job.
- **Data refresh:** re-run the job, or use the in-app Refresh (applies adapter writes, verifies).
- **Reset:** in-app Reset demo, or run `07_reset_demo`.
- **Logs:** App → Logs tab; job run output; `ops_agent_activity`; MLflow experiment.
- **App creation error "Failed to create app service principal due to unexpected error":** observed as a
  transient platform error during initial deployment; delete the failed app and create it again (the script is
  idempotent). Escalate to an account admin if it persists.
- **Model errors "does not support the temperature parameter":** keep `agent.temperature: null` (omitted).
- **First load:** the app reads Silver and operational tables through the warehouse on first session
  (~30-60 s from a cold warehouse); later interactions are in-memory.
- **Permissions troubleshooting:** app errors mentioning `PERMISSION_DENIED` → re-run the grants step;
  model errors → check the serving-endpoint resource permission.

## 7. Local development

```bash
pip install -e ".[dev]"            # or: pip install -r requirements.txt pytest
python -m src.synthetic_data   # writes data/generated/*.csv
pytest
streamlit run app/main.py          # local backend, deterministic agent unless LLM reachable
```

To use the Databricks backend locally: `LSI_REPOSITORY_BACKEND=databricks DATABRICKS_WAREHOUSE_ID=<id>
DATABRICKS_CONFIG_PROFILE=DEFAULT streamlit run app/main.py`.

## 8. Production hardening (not done in the demo)

Per-user authorization (App OBO tokens + UC row filters), secrets in Databricks secret scopes, real adapter
behind change control, Lakeflow incremental ingestion, monitoring/alerting, CI/CD with bundles, and security,
privacy, legal, compliance, operational, and integration reviews.
