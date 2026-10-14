# App UX Specification — Loan Servicing Intelligence

> The app is a thin window onto the Databricks backend. It shows the **Synthetic Demonstration Data** label on
> every page. Calm by default; detail on demand.

- Framework: Streamlit (Databricks Apps), `app/main.py` + `app/navigation.py`; pages in `app/pages/`, shared
  building blocks in `app/ui.py`. All data goes through the REST API (`app/client.py`).
- Sidebar: **Presenter notes** toggle (talk track from `config/demo_story.yml`), `lsi-pipeline` workflow status
  with **Open run in Databricks** and **Run workflow now**, and **Sync AI results** (reloads Gold tables).
- Purple boxes are AI output and always state where they were produced (notebook, function, endpoint).
  Blue boxes are deterministic rule facts with rule IDs.

## 1. Portfolio (default page)
- Four cards: active loans, need attention, AI summaries, reviewed by the agent.
- AI portfolio briefing from `gold_ai_portfolio_briefing` (AI Functions, notebook 07).
- Loan list (highest attention first): loan (click to open), priority, condition, score, **AI summary**
  (`gold_ai_loan_insights`), **Agent review** (recommended action and tool-call count from `gold_agent_loan_reviews`).
- Search, priority filter, and "Only loans with AI" toggle.

## 2. Loan
- Picker plus header (priority, condition, days overdue, payment and foreclosure status).
- Left, **Rules engine facts**: conditions with rule IDs, score-driver chart, milestone, follow-up, escalation.
- Right, **AI from the Databricks backend**: the AI Functions summary and the agent review (recommended action,
  tools called, review text), each labelled with its source.
- **On-demand AI analysis**: *Run AI analysis now* sends a review request to the deployed agent; a chat box sends
  follow-up questions. Each answer shows the tool chain and the rows each Unity Catalog tool returned.
- Servicing event timeline in an expander.

## 3. The Agent
- Endpoint status, model version, tool count; links to the serving endpoint, AI Playground, the model in Unity
  Catalog, and traces.
- How-it-works diagram, what it may and may never do, a live chat with suggested prompts, and the tool catalog
  read live from Unity Catalog (with links to each function).

## 4. How It Works
- One diagram with Databricks at the center, last workflow run, "Where the AI is created" table, the agent in four
  bullets, Databricks components and their role, and links to every resource.

## Retained in the backend (not shown in the simplified app)
Review decisions, action preparation, the synthetic System-of-Record adapter, verification, and evaluation remain in
`src/` and the REST API (with tests) and can be surfaced again if a demo needs the full human-in-the-loop flow.
