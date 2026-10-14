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
| 8 | `08_agent_reviews` | Tool chain printed, drafts table | Batch agent: it drafts the next step for the top of the queue before anyone logs in. |
| 9 | Workflow run | `generate -> bronze -> silver -> gold -> ai_functions -> agent_reviews` | All of it runs as one serverless workflow on a schedule. |

## Part B - the app (the on-demand side)

| # | Page | Show | Say |
|---|------|------|-----|
| 10 | Portfolio | Briefing, AI summary and Agent draft columns | The overnight side: the queue arrives with next steps already drafted. |
| 11 | Loan `LSI-SYN-000006` | Rule facts with rule IDs, the overnight draft | Judgment Hearing follow-up 75 days overdue; the agent already drafted the next step overnight. |
| 12 | Loan - paste the attorney update (placeholder text), click **Re-plan with the agent** | Live tool chain, new draft | The on-demand side: something changed, and the same agent re-plans live, inside the workflow. |
| 13 | Loan - optional custom instruction "Draft an email to the assigned attorney" | Outreach in the draft | Steer the agent per request without redeploying. |
| 14 | Loan - edit the date, **Confirm and schedule** | Toast, timeline shows Scheduled | A person decides. The action leaves as a bulk-upload file in the `outbound` volume - no browser automation - and the next workflow run verifies it landed. |
| 14b | Loan - **Log what you did**: "I followed up" with a note | Timeline shows the contact | Not everything starts with the agent: the specialist logs their own work, and the next run takes the loan off the overdue list. |
| 15 | Loan `LSI-SYN-000007` - **Have the agent propose the next step** | Create Next Milestone drafted | A loan the overnight run did not cover: the agent drafts on demand. |
| 16 | Databricks - Traces | The traces for the drafts you just made | MLflow 3 traces every request in real time; LLM judges score them (notebook 09). |
| 17 | How It Works - One framework | The framework table | Foreclosure milestones first; tax delinquency and invoice processing reuse the same five layers. |

## Fallbacks

- Agent slow on the first call: it is waking from scale-to-zero; continue with the backend AI and come back.
- No AI columns on Portfolio: run the `lsi-pipeline` workflow.
- To reset loans you scheduled in the app: run the commented `TRUNCATE` cell at the end of notebook 01.

## After the demo

`databricks apps stop loan-servicing-intelligence`. The warehouse auto-stops, the agent endpoint scales to zero,
and the workflow schedule is paused.
