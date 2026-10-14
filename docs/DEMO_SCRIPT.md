# Demo Script — Loan Servicing Intelligence on Databricks

> Input data is synthetic; every AI output is real (Claude on Databricks). Say it once, early.
> Theme: **Databricks is the right backend** — governed data, rules, AI Functions, and an agent in one platform.
> Duration: 15–20 minutes.

## Before the demo (15 minutes ahead)

1. Start the app if stopped: `databricks apps start loan-servicing-intelligence`.
2. Wake the agent endpoint (it scales to zero): ask one question on **The Agent** page or in the AI Playground.
3. Optional: run the `lsi-pipeline` workflow (sidebar **Run workflow now**, about 10 minutes), then **Sync AI results**.
4. Open these tabs in Databricks: the latest `lsi-pipeline` run, notebook `07_ai_functions`, notebook
   `08_agent_reviews`, the `loan-servicing-agent` serving endpoint, and the `lsi_*` functions in Catalog Explorer.

## Storyline: two sides of AI on Databricks

**Part A - the notebooks (open them in this order).** Each notebook is short and shows its work inline.

| # | Notebook | Show | Say |
|---|----------|------|-----|
| 1 | `01_generate_demo_data` | Volume listing, sample rows | Servicing exports land in a governed Unity Catalog volume (synthetic here). |
| 2 | `02_ingest_bronze` | One short Spark cell | Raw copy plus lineage: every fact traces back to its file. |
| 3 | `03_build_silver` | SQL cells | Typed, de-duplicated, sequenced, quality-flagged - in plain SQL. |
| 4 | `04_build_gold` | The one-loan walkthrough cell | Rules are configuration; every loan gets conditions, a score with its drivers, and allowed actions. |
| 5 | `05_agent_tools` | Two or three `CREATE FUNCTION` cells | **This is where the agent's tools are defined**: governed SQL functions whose comments tell the model when to use them. |
| 6 | `06_build_and_deploy_agent` | The agent cell, the test output, `log_model`, `agents.deploy` | **This is the whole agent**: about 100 lines. Test it, register it in Unity Catalog, deploy it with one call. Custom instructions steer it per request. |
| 7 | `07_ai_functions` | The `ai_query` cell and results | Batch AI in SQL: summaries for every priority loan. |
| 8 | `08_agent_reviews` | Tool chain printed, reviews table | Batch agent: it investigates the top of the queue before anyone logs in. |
| 9 | Workflow run | Task graph `generate -> bronze -> silver -> gold -> ai_functions -> agent_reviews` | All of it runs as one serverless workflow on a schedule. |

**Part B - the app (on demand).**

| # | Page | Show | Say |
|---|------|------|-----|
| 10 | Portfolio | Briefing, AI summary and Agent review columns | The batch side's results, ready for specialists. |
| 11 | Loan `LSI-SYN-000006` | Rule facts and backend AI side by side | Facts with rule IDs; what the backend AI concluded. |
| 12 | Loan - **Run AI analysis now** | Live tool chain | The on-demand side: the same agent, live. |
| 13 | Loan - custom instruction "Draft an email to the assigned attorney" | The email in the answer | Augment the agent per request without redeploying. |
| 14 | The Agent | Tool catalog, links to Serving, Playground, Unity Catalog | Governed tools, registered model, traces. |

## Fallbacks

- Agent slow on first call: it is waking from scale-to-zero; continue with the backend AI and come back.
- No AI columns in Portfolio: run the workflow, then **Sync AI results**.

## After the demo

`databricks apps stop loan-servicing-intelligence`. The warehouse auto-stops; the agent endpoint scales to zero;
the workflow schedule is paused.
