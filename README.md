# Loan Servicing Intelligence

**Agent-powered portfolio monitoring and loan-servicing workflow automation**

> **Synthetic demonstration data.** Every borrower, loan, property, specialist, vendor, event, rule,
> threshold, score, workflow, and metric in this repository is synthetic. Nothing here represents any
> lender's production schema, servicing policy, legal process, or regulated decision framework.

> **Customer-neutral.** This is a reusable reference application. It contains no customer, employee,
> stakeholder, customer document, customer system, URL, presentation, or customer-specific process, and an
> automated neutrality scan enforces this (`docs/CUSTOMER_NEUTRALITY_REVIEW.md`).

## Overview

Loan Servicing Intelligence shows how a servicing organization can move from reviewing loans one at a time to
continuously monitoring an entire portfolio:

- **Portfolio Intelligence:** what is happening across the portfolio, which loans need attention, why, and
  where to focus.
- **Loan Intelligence:** what is happening on one loan, the current milestone, its history, what should happen
  next, and the evidence for it.

Deterministic, configuration-driven rules detect conditions (upcoming, due, overdue, missing follow-up,
duplicates, data exceptions, pending/failed actions…), compute escalation and an explainable attention score,
and build a prioritized work queue. A tool-calling **Loan Servicing Agent** investigates loans through 29
approved tools, recommends only allowed actions with cited evidence, and prepares — never executes — actions.
Specialists approve, edit, reject, defer, or escalate. Approved actions are revalidated, sent through a
synthetic System-of-Record adapter, and verified on the next refresh; failures return to the queue.

**Operating principle:** Agents perform investigative work. People remain accountable for consequential
decisions. The loan-servicing platform remains the operational System of Record.

## Architecture

```text
Synthetic exports -> UC volume -> Bronze -> Silver -> Gold (rules, escalation, scoring, verification)
  -> deterministic tools -> Loan Servicing Agent -> REST API -> Databricks App (Streamlit)
  -> human review -> revalidation -> SyntheticServicingSystemAdapter -> simulated System of Record
  -> next refresh -> verification -> verified, or back to the queue
```

The **Loan Servicing Agent** is also deployed as a Databricks agent (Mosaic AI Agent Framework): registered in Unity
Catalog, served on Model Serving, with 17 Unity Catalog SQL functions as its governed tools. The app's *Meet the
Agent* page shows it live.

One serverless workflow (`lsi-pipeline`) builds the Bronze/Silver/Gold data, runs the rules, creates AI summaries
with AI Functions, and has the deployed agent review the top of the queue. The app reads the results.

Serverless-first on Azure Databricks: serverless Jobs for the pipeline, a serverless SQL warehouse with
auto-stop, pay-per-token Foundation Model API (`databricks-claude-sonnet-5-5`), and a Databricks App that is
stopped when idle. Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Repository structure

```text
src/                 flat core modules: config, synthetic_data, medallion, rules (the whole rules engine),
                     tools, agent, service, storage, evaluation, databricks, pipeline, api, models, neutrality
agent_endpoint/      the deployable Databricks agent (MLflow ResponsesAgent, Unity Catalog tools)
app/                 Streamlit Databricks App: main, navigation, client, ui, pages/ (one file per page)
config/              application, business rules, scoring, escalation, allowed actions, demo scenarios, talk track
data/generated/      synthetic CSV exports (committed, reproducible)
docs/                product, architecture, data, rules, agent, API, UX, evaluation, demo, deployment docs
notebooks/           01-07 lsi-pipeline workflow (06 AI Functions, 07 agent reviews), 08 deploy agent
scripts/             job creation, app and agent deployment, UC tool registration
sql/                 Bronze/Silver/Gold DDL and views
tests/               unit, integration, end_to_end
app.yaml             Databricks App definition
databricks.yml       Databricks Asset Bundle (serverless job + app)
```

## Setup (local)

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt pytest
python -m src.synthetic_data                # regenerate data/generated (deterministic)
pytest                                                 # unit + integration + end-to-end
streamlit run app/main.py                              # local backend
```

`LSI_AGENT_MODE=auto` uses the Databricks LLM endpoint when your Databricks CLI profile can reach it, and the
deterministic agent otherwise. See `.env.example` for all settings.

## Databricks deployment

1. Link this repository as a Git folder in the workspace and pull.
2. Create and run the serverless pipeline job:
   `python scripts/create_pipeline_job.py --repo-path /Workspace/Users/<you>/AIWorkflowAutomationDemo`
3. Deploy the app (creates resources, grants, deploys, then stops it):
   `python scripts/deploy_app.py --repo-path /Workspace/Users/<you>/AIWorkflowAutomationDemo --warehouse-id <id>`
4. Before a demo: `databricks apps start loan-servicing-intelligence`; after: `databricks apps stop …`.

Full guide: [docs/DATABRICKS_DEPLOYMENT.md](docs/DATABRICKS_DEPLOYMENT.md).

## Demo mode

Open the app on **Portfolio**, open a loan, run the on-demand AI analysis, then show the Databricks side: the
`lsi-pipeline` workflow run, notebook `06_ai_functions` (AI Functions in SQL), notebook `07_agent_reviews` (the
deployed agent reviewing the queue), and the agent's Unity Catalog tools. Walkthrough:
[docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md).

## Testing

```bash
pytest tests/unit          # rules, scoring, dates, tools, agents, adapter, verification, API, neutrality
pytest tests/integration   # pipeline, scenario manifest, tool/agent interaction, persistence
pytest tests/end_to_end    # files -> ingestion -> rules -> score -> agent -> approval -> adapter -> refresh -> verification
python -m src.neutrality   # customer-neutrality scan
```

## Limitations

Synthetic data and rules only; no production platform or browser automation; no regulated, legal, or
eligibility decisions; every consequential action requires approval; feedback never changes behavior
automatically; demo-grade authorization. Production use requires security, privacy, legal, compliance,
operational, and integration reviews. See [docs/ASSUMPTIONS_AND_LIMITATIONS.md](docs/ASSUMPTIONS_AND_LIMITATIONS.md).

## Documentation

| Document | Contents |
|----------|----------|
| [PRD](docs/PRD.md) | Vision, goals, personas, journeys, stories, requirements, acceptance criteria |
| [Architecture](docs/ARCHITECTURE.md) | Logical/physical architecture, runtime topology, sequences |
| [Data Model](docs/DATA_MODEL.md) | Source, Bronze, Silver, Gold, operational tables |
| [Business Rules](docs/BUSINESS_RULES.md) | Rule catalog with IDs, escalation, scoring, scenarios |
| [Agent Design](docs/AGENT_DESIGN.md) | Agent interface, loop, guardrails, prompts, failure handling |
| [Agent Tools](docs/AGENT_TOOLS.md) | 29 tools with inputs/outputs |
| [API Specification](docs/API_SPECIFICATION.md) | REST endpoints and schemas |
| [App UX Specification](docs/APP_UX_SPECIFICATION.md) | Pages, components, states |
| [Evaluation Plan](docs/EVALUATION_PLAN.md) | Rule vs agent evaluation methodology |
| [Demo Script](docs/DEMO_SCRIPT.md) | Step-by-step client demo |
| [Databricks Deployment](docs/DATABRICKS_DEPLOYMENT.md) | Serverless deployment and operations |
| [Assumptions & Limitations](docs/ASSUMPTIONS_AND_LIMITATIONS.md) | Assumptions, limitations, production prerequisites |
| [Implementation Plan](docs/IMPLEMENTATION_PLAN.md) | Stages and status |
| [Decisions](docs/DECISIONS.md) | Architecture decision records |
| [Customer-Neutrality Review](docs/CUSTOMER_NEUTRALITY_REVIEW.md) | Neutrality method and results |
