# Demo Script - Loan Servicing Intelligence on Databricks

> Input data is synthetic; every AI output is real (Claude on Databricks). Say it once, early.
> Theme: **Databricks is the right backend** - governed data, rules, AI Functions, and an agent in one platform.
> Duration: 15-20 minutes.

## Before the demo (15 minutes ahead)

1. Start the app if it is stopped: `databricks apps start loan-servicing-intelligence`.
2. Wake the agent endpoint (it scales to zero): ask one question on **The Agent** page or in the AI Playground.
3. Optional: run the `lsi-pipeline` workflow (about 10 minutes) so the data and AI are from today.
4. Open in Databricks: the latest `lsi-pipeline` run, notebooks `04`, `05`, `06`, `07`, `08`, and the
   `loan-servicing-agent` experiment's Traces tab. The How It Works page links to all of them.

## Part A - the notebooks (the batch side)

| # | Notebook | Show | Say |
|---|----------|------|-----|
| 1 | `01_generate_demo_data` | Volume listing | Servicing exports land in a governed Unity Catalog volume (synthetic here). |
| 2 | `02_ingest_bronze` | One short Spark cell | Raw copy plus lineage: every fact traces back to its file. |
| 3 | `03_build_silver` | SQL cells | Typed, de-duplicated, sequenced - plain SQL. |
| 4 | `04_build_gold` | `rule_conditions`, the condition cell, the `LSI-SYN-000007` walkthrough | **The rules are SQL and a table.** Each line is one rule with its ID. 000007 finished Title Review but nobody opened Complaint Filed (RULE-MILESTONE-003), so the allowed action is Create Next Milestone. |
| 5 | `05_agent_tools` | Two or three `CREATE FUNCTION` cells | **This is where the agent's tools are defined**: governed SQL functions whose comments tell the model when to use them. |
| 6 | `06_build_and_deploy_agent` | The agent cell, the test output, `log_model`, `agents.deploy` | **This is the whole agent**: about 100 lines. Test it, register it in Unity Catalog, deploy it with one call. |
| 7 | `07_ai_functions` | The `ai_query` cell and results | Batch AI in SQL: summaries for every priority loan. |
| 8 | `08_agent_reviews` | Tool chain printed, reviews table | Batch agent: it investigates the top of the queue before anyone logs in. |
| 9 | Workflow run | `generate -> bronze -> silver -> gold -> ai_functions -> agent_reviews` | All of it runs as one serverless workflow on a schedule. |

## Part B - the app (the on-demand side)

| # | Page | Show | Say |
|---|------|------|-----|
| 10 | Portfolio | Briefing, AI summary and Agent review columns | The batch side's results, ready for specialists. |
| 11 | Loan `LSI-SYN-000007` | Backend AI, then the rule facts with rule IDs | What the backend concluded, and the deterministic facts behind it. |
| 12 | Loan - **Run AI analysis now** | Live tool chain | The on-demand side: the same agent, live. |
| 13 | Loan - custom instruction "Draft an email to the assigned attorney" | The email in the answer | Steer the agent per request without redeploying. |
| 14 | Loan - **Next step** | Create Next Milestone preselected; edit the date; Confirm and schedule | The agent recommends, a person decides. The timeline shows it as scheduled; the next workflow run verifies it landed. |
| 15 | Databricks - Traces and notebook `09_monitor_agent` | The trace for the analysis you just ran | MLflow 3 traces every request in real time; LLM judges score them. |
| 16 | The Agent | Tool catalog, links to Serving, Playground, Unity Catalog | Governed tools, registered model, traces. |

## Fallbacks

- Agent slow on the first call: it is waking from scale-to-zero; continue with the backend AI and come back.
- No AI columns on Portfolio: run the `lsi-pipeline` workflow.
- To reset loans you scheduled in the app: run the commented `TRUNCATE` cell at the end of notebook 01.

## After the demo

`databricks apps stop loan-servicing-intelligence`. The warehouse auto-stops, the agent endpoint scales to zero,
and the workflow schedule is paused.
