# Demo Script — Loan Servicing Intelligence on Databricks

> Input data is synthetic; every AI output is real (Claude on Databricks). Say it once, early.
> Theme: **Databricks is the right backend** — governed data, rules, AI Functions, and an agent in one platform.
> Duration: 15–20 minutes.

## Before the demo (15 minutes ahead)

1. Start the app if stopped: `databricks apps start loan-servicing-intelligence`.
2. Wake the agent endpoint (it scales to zero): ask one question on **The Agent** page or in the AI Playground.
3. Optional: run the `lsi-pipeline` workflow (sidebar **Run workflow now**, about 10 minutes), then **Sync AI results**.
4. Open these tabs in Databricks: the latest `lsi-pipeline` run, notebook `06_ai_functions`, notebook
   `07_agent_reviews`, the `loan-servicing-agent` serving endpoint, and the `lsi_*` functions in Catalog Explorer.

## Storyline

| # | Where | Show | Say (story) | Say (Databricks) |
|---|-------|------|-------------|------------------|
| 1 | App - How It Works | Diagram, "Where the AI is created" | Specialists used to review loans one at a time. Here the whole portfolio is evaluated and explained before anyone logs in. | One serverless Workflow does it all: Bronze/Silver/Gold, rules, AI Functions, agent reviews. |
| 2 | Databricks - Workflow run | Task graph: generate, bronze, silver, gold, tools, ai_functions, agent_reviews | This is the backend running. | Serverless Jobs: no clusters, nothing running between runs. |
| 3 | Databricks - notebook 06 | The `ai_query` SQL cell and its output | The rules found the facts; one SQL function turns them into plain language. | AI Functions: `ai_query` over a governed Gold table, written back to Gold. |
| 4 | Databricks - notebook 07 | `ask_agent`, the tool chain printed, the reviews table | The agent investigates the top of the queue overnight. | The deployed agent is one HTTP call; reviews land in Unity Catalog. |
| 5 | App - Portfolio | AI briefing, AI summary and Agent review columns | Specialists open the app and the investigation is already done. | The app just reads Gold through a serverless SQL warehouse. |
| 6 | App - Loan `LSI-SYN-000006` | Rule facts (left), backend AI (right) | Facts with rule IDs on the left; what the AI backend concluded on the right. | Deterministic rules plus AI, all governed. |
| 7 | App - Loan, **Run AI analysis now** | Live tool chain and answer; ask a follow-up | Ask the agent anything about this loan, live. It recommends; people decide. | Model Serving + Unity Catalog tools + MLflow tracing. |
| 8 | App - The Agent, then Databricks | Tool catalog; open one `lsi_*` function; serving endpoint; Playground | These 17 governed functions are the agent's toolset. | Mosaic AI Agent Framework, registered model, scale-to-zero, traces. |
| 9 | Close | — | Agents investigate, people decide, the servicing platform stays the System of Record. | One governed platform for data, AI, and the app. |

## Fallbacks

- Agent slow on first call: it is waking from scale-to-zero; continue with the backend AI and come back.
- No AI columns in Portfolio: run the workflow, then **Sync AI results**.

## After the demo

`databricks apps stop loan-servicing-intelligence`. The warehouse auto-stops; the agent endpoint scales to zero;
the workflow schedule is paused.
