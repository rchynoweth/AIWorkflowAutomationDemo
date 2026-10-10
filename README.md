# Loan Servicing Intelligence

**Agent-powered portfolio monitoring and loan-servicing workflow automation**

> ⚠️ **Synthetic demonstration data.** Every borrower, loan, property, specialist, vendor, event, rule,
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

Serverless-first on Azure Databricks: serverless Jobs for the pipeline, a serverless SQL warehouse with
auto-stop, pay-per-token Foundation Model API (`databricks-claude-sonnet-5-5`), and a Databricks App that is
stopped when idle. Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Repository structure

```text
app/                 Streamlit Databricks App (pages, components, API client)
config/              application, business rules, scoring, escalation, allowed actions, demo scenarios
data/generated/      synthetic CSV exports (committed, reproducible)
data/landing|outbound|processed/   runtime folders (git-ignored)
docs/                product, architecture, data, rules, agent, API, UX, evaluation, demo, deployment docs
notebooks/           01–07 Databricks notebooks (thin orchestration of src/)
scripts/             job creation and app deployment helpers
sql/                 Bronze/Silver/Gold DDL and views
src/                 core package: data_generation, ingestion, transformations, rules, scoring, tools,
                     agents, services, adapters, verification, evaluation, repositories, models, api, quality
tests/               unit, integration, end_to_end
app.yaml             Databricks App definition
databricks.yml       Databricks Asset Bundle (serverless job + app)
```

## Setup (local)

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt pytest
python -m src.data_generation.generator                # regenerate data/generated (deterministic)
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

`DEMO_MODE=true` (default) uses the fixed seed and processing date (2026-10-12), deterministic scenarios
(`LSI-SYN-000001`–`000020`), the synthetic adapter with configured failure/mismatch/duplicate/delay modes
(`config/demo_scenarios.yml`), and a full reset (sidebar **Reset demo** or `POST /api/demo/reset`).
Walkthrough: [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md).

## Testing

```bash
pytest tests/unit          # rules, scoring, dates, tools, agents, adapter, verification, API, neutrality
pytest tests/integration   # pipeline, scenario manifest, tool/agent interaction, persistence
pytest tests/end_to_end    # files -> ingestion -> rules -> score -> agent -> approval -> adapter -> refresh -> verification
python -m src.quality.neutrality   # customer-neutrality scan
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
