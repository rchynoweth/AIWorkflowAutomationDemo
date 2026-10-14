# Loan Servicing Intelligence

**An agent-powered loan-servicing demo on Databricks.** A serverless workflow turns servicing exports into
governed facts, AI explains them, and a deployed agent investigates the loans that matter. A thin Databricks App
shows the results, calls the agent on demand, and records the actions a person confirms.

> **Synthetic data, real AI.** Every borrower, loan, rule, and threshold is synthetic and customer-neutral. Every
> AI output is produced live by Claude on Databricks.

## How it works

```text
servicing exports (synthetic) -> UC volume -> Bronze -> Silver -> Gold rules (SQL)
    -> AI Functions summaries (ai_query)      \
    -> agent reviews of the work queue          > Unity Catalog tables  <-  Databricks App
Loan Servicing Agent (Model Serving) <- tools: Unity Catalog SQL functions   <-  on-demand analysis
    person confirms an action in the app -> servicing system event -> verified on the next run
```

| Notebook | What it does | Runs |
|---|---|---|
| `01_generate_demo_data` | Lands today's synthetic exports in a volume (generator: `synthetic_data.py`) | Workflow |
| `02_ingest_bronze` | Raw Delta copy with lineage | Workflow |
| `03_build_silver` | Typed, de-duplicated tables (SQL) | Workflow |
| `04_build_gold` | **The servicing rules in SQL**: milestone, follow-up, conditions, score, priority, allowed actions | Workflow |
| `05_agent_tools` | **The agent's tools**: 13 Unity Catalog SQL functions | Once |
| `06_build_and_deploy_agent` | **The agent**: write, test, register, deploy (writes `agent.py`) | Once |
| `07_ai_functions` | Batch AI with `ai_query`: loan summaries and a portfolio briefing | Workflow |
| `08_agent_reviews` | Batch agent: the deployed agent reviews the top of the queue | Workflow |
| `09_monitor_agent` | MLflow 3 traces, LLM judges, production monitoring | Once |

The app (`app/`) has four pages: Portfolio, Loan, The Agent, How It Works. `app/data.py` holds every query and the
agent call.

Everything is serverless and scales to zero: serverless jobs, a serverless SQL warehouse with auto-stop,
pay-per-token Foundation Model API, a scale-to-zero agent endpoint, and an app you stop after the demo.

## Repository

```text
notebooks/   the pipeline, the tools, the agent (01-09), plus synthetic_data.py and agent.py
app/         the Databricks App: main.py, data.py, ui.py, pages/, demo_story.yml (presenter notes)
scripts/     create_pipeline_job.py, deploy_app.py
tests/       generator and customer-neutrality checks
docs/        DEMO_SCRIPT.md
```

## Deploy

1. Add this repository to the workspace as a Git folder.
2. Run notebooks `01` to `05`, then `06` with the `warehouse_id` widget set (deploys the agent, about 15 minutes).
3. Create the workflow and run it once:
   `python scripts/create_pipeline_job.py --repo-path /Workspace/Users/<you>/AIWorkflowAutomationDemo --run`
4. Deploy the app:
   `python scripts/deploy_app.py --repo-path /Workspace/Users/<you>/AIWorkflowAutomationDemo --warehouse-id <id> --keep-running`

After changing a tool in notebook 05, rerun notebook 06: replacing a function gives it a new identity, and the
deployed agent only has access to the functions it was deployed with.

## Test

```bash
pip install pandas pytest && pytest
```

Set `LSI_NEUTRALITY_DENYLIST` (comma-separated names) to also check that no customer names appear.

## Limits

Synthetic data and rules only. No production systems, no legal, eligibility, or other regulated decisions. The agent
is read-only; a person confirms every action.
