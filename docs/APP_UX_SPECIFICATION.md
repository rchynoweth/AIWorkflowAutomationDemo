# App UX Specification — Loan Servicing Intelligence

> Every page shows the **Synthetic Demonstration Data** label. The app is an operations product with AI
> embedded throughout, not a chatbot.

- Framework: Streamlit (Databricks Apps compatible), `app/main.py` with `st.navigation`.
- Title: **Loan Servicing Intelligence** — subtitle **Agent-powered portfolio monitoring and loan-servicing
  workflow automation**.
- Data access: only through `ApiClient` (`app/state.py`) → REST API.
- Global header (`app/navigation.py`): product name, subtitle, synthetic badge, processing date, refresh cycle,
  backend, agent mode; sidebar reviewer selector (synthetic specialist + role) and a "Refresh source" control.

## Visual language

| Element | Treatment |
|---------|-----------|
| Priority | CRITICAL red, HIGH orange, MEDIUM amber, LOW slate |
| Health | Healthy green, Watch blue, Action Required amber, Critical red |
| Timeline states | COMPLETED grey-green, CURRENT blue, UPCOMING teal, SCHEDULED slate (open follow-up beyond look-ahead), DUE amber, OVERDUE red, PROPOSED purple (dashed), SUBMITTED indigo, FAILED dark red, VERIFIED green check |
| AI content | Labeled "Agent" and the agent mode (LLM / deterministic) |
| Deterministic facts | Labeled "Rule" with the rule ID |

## 0. Demo layer (presenter experience)

Design principle: **calm by default, detail on demand.** Pages show the few things a presenter needs; filters,
extra metrics, evidence, and tool calls live in expanders and popovers.

- **Navigation sections:** Demo (Demo Story, How It Works) · Operations (Home, Priority Queue, Loan 360,
  Portfolio) · Trust (Agent Activity, Evaluation). The app opens on Demo Story.
- **Demo Story (`app/pages/story.py`):** ten chapters (set the scene → glance → queue → investigate → agent →
  decide → verify → failure → trust → close). Each chapter shows its goal, minutes, and talk track, and an
  **Open** button that navigates to the right page (and loan). The target page then shows a chapter banner
  with "Say" and "Do" notes and a **Next chapter** button.
- **Presenter notes:** sidebar toggle (default on) showing a dashed talk-track callout on each page.
  Content lives in `config/demo_story.yml` and can be edited without code changes.
- **How It Works (`app/pages/how_it_works.py`):** three pillars (monitor, agent investigates, people decide),
  an architecture diagram color-coded by automated / AI / human / System of Record, a "who does what" table for
  every step of the loop, the agent loop diagram with what the agent may and may never do, a rules-vs-agent-vs-
  people decision split, and the Databricks components used.

## 1. Home (`app/pages/home.py`)

1. **KPI cards** (`components/kpi_cards.py`): five headline cards (Active loans, Need attention, Critical,
   Awaiting approval, Failed verification); Upcoming, Due, Overdue, Missing follow-up, Data exceptions, Approved
   today, and Awaiting verification under "More metrics". All from `GET /api/portfolio/summary`.
2. **Portfolio Health** (`components/portfolio_health.py`): four segment buttons (Healthy, Watch, Action
   Required, Critical) with counts and a stacked bar. Clicking a segment filters the task preview and offers
   "Open in Portfolio".
3. **Today's Portfolio Briefing**: generated via `POST /api/agent {mode: briefing}` from deterministic facts
   only; shows source (LLM / deterministic), an expander with the facts, and a regenerate button.
4. **Prioritized task preview** (`components/priority_table.py`): top 10 — priority, loan, synthetic borrower,
   condition, score, drivers, recommendation, specialist, status, why prioritized; "Open" goes to Loan 360.

## 2. Portfolio (`app/pages/portfolio.py`)

Columns: Loan, Borrower, State, Portfolio, Current Balance, Payment Status, Days Delinquent, Loan Status,
Foreclosure Status, Current Milestone, Next Follow-Up, Milestone Health, Attention Score, Priority, Assigned
Specialist, Agent Status. Filters: State, Portfolio, Loan Status, Payment Status, Foreclosure Status,
Milestone, Health, Priority, Specialist, Agent Status. Search: loan ID, synthetic borrower, state, county.
Single-row selection opens Loan 360. Row count and filtered count displayed.

## 3. Priority Queue (`app/pages/priority_queue.py`)

Columns: priority, loan, borrower, condition, severity, milestone, follow-up date, days overdue, score,
drivers, recommendation, confidence, specialist, status, why prioritized. Filters: priority, every condition,
review state (Not analyzed, Awaiting approval, Approved, Submitted, Rejected, Deferred, Escalated, Verified,
Verification failed), specialist. Row selection → Loan 360. Bulk "Analyze top N with agent" (default 5).

## 4. Loan 360 (`app/pages/loan_360.py`)

**Header:** loan ID, synthetic borrower, loan status, payment status, days delinquent, foreclosure status,
priority badge, score, days overdue. Loan picker (search) if none selected.

**Tabs**
- **Overview:** metadata, property (synthetic), balances, assigned specialist and party, statuses, current
  milestone, effective follow-up, health, score drivers (bar), open conditions with rule IDs, escalation
  reasons, pending actions.
- **Events:** chronological timeline (`components/event_timeline.py`) with state styling for completed,
  current, upcoming, due, overdue, proposed, submitted, failed, verified; toggle to include payment history.
- **Agent Analysis:** (`components/agent_assessment.py`) detected primary + secondary conditions, priority,
  score, attention reasons, evidence table, rationale, recommended action, proposed event/date/note/outreach,
  confidence, uncertainty, missing information, allowed actions, validation result. Buttons: "Run agent
  analysis" (creates/refreshes the recommendation). **Review controls** (`components/review_controls.py`):
  Approve, Edit (form: action from allowed list, event type, follow-up date, note, outreach, escalation
  target), Reject (reason required), Defer (reason), Escalate (target role). After approval: outbound event
  JSON preview, "Submit via synthetic adapter", then "Refresh source & verify".
  **Ask the Agent:** suggested-question chips + free text; answers show tool calls in an expander.
- **Recommendations:** history of recommendations with status, decision, action, verification.
- **Activity:** this loan's agent/tool/user/adapter activity (`components/activity_trace.py`).

## 5. Agent Activity (`app/pages/agent_activity.py`)

Run selector and loan filter. For a run: step chain rendered as a horizontal flow — candidate detected →
context retrieved → milestone checked → events retrieved → duplicates checked → rule retrieved → pending
action checked → score calculated → allowed actions retrieved → recommendation generated → awaiting approval.
Table: timestamp, run, loan, tool, summarized input, summarized output, duration, result, recommendation
status. Never shows secrets, credentials, prompts, or chain-of-thought.

## 6. Evaluation (`app/pages/evaluation.py`)

Clearly labeled synthetic metrics in two separate sections:
- **Deterministic rule quality** (scenario manifest): condition accuracy, priority accuracy, default-action
  accuracy, verification accuracy; per-scenario pass/fail table.
- **Agent quality**: action agreement with expected action, allowed-action compliance, evidence coverage,
  tool failure rate, fallback rate, false positives / false negatives (attention flag vs expected).
- **Human review signals** (synthetic history + live decisions): acceptance, edit, rejection, deferral rates.
- **Verification**: success rate and status distribution.
- Button "Run agent evaluation" (deterministic by default; LLM optional) and explanation of rule vs agent quality.

## 7. States and errors

- API unavailable → banner with retry; no stale writes.
- Agent failure → "Agent analysis failed — routed to specialist review", no action buttons except Defer/Escalate.
- Validation failure on approval → error list with codes; no action created.
- Empty states for queues and activity.

## 8. Accessibility

Color is never the only signal (badges include text), tables are sortable, all controls have labels, and
contrast meets WCAG AA in the configured theme (`.streamlit/config.toml`).
