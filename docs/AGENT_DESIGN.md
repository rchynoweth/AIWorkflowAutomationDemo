# Agent Design — Loan Servicing Agent

> Synthetic demonstration. The agent never makes lending, eligibility, legal, foreclosure-authority, compliance,
> loss-mitigation, or other regulated decisions and never provides legal or financial advice.

## 1. Purpose

The Loan Servicing Agent performs investigative work for authorized servicing specialists: it gathers facts
through approved deterministic tools, interprets them, recommends an action **from the allowed list**,
explains why with cited evidence, states uncertainty and missing information, drafts notes/outreach, and
prepares an **uncommitted** action that waits for human authorization.

## 2. Interface (framework-neutral)

```python
class LoanServicingAgent(ABC):
    agent_version: str
    def assess_loan(self, loan_id: str, run: RunContext) -> AgentAssessment: ...
    def answer_question(self, question: str, loan_id: str | None, run: RunContext) -> AgentAnswer: ...
    def portfolio_briefing(self, facts: dict, run: RunContext) -> Briefing: ...
```

Implementations (`src/agent.py`):

| Class | Use |
|-------|-----|
| `ToolCallingLoanServicingAgent` | LLM-driven tool selection via an `LlmClient` (OpenAI-compatible tool calling). Default model: `databricks-claude-sonnet-5-5` (pay-per-token Foundation Model API). |
| `DeterministicLoanServicingAgent` | Fixed investigation plan and templated narrative. Used in tests, when the LLM is unavailable, and as the guaranteed fallback. Also produces baseline recommendations in the pipeline. |

`LlmClient` implementations: `DatabricksFoundationModelClient` (Databricks SDK, serving-endpoint invocations)
and `ScriptedLlmClient` (tests). No core logic imports an agent framework; Agent Bricks / Mosaic AI Agent
Framework deployment would wrap the same interface (see `docs/DECISIONS.md` ADR-004).

`create_agent(config, tools)` selects the implementation from `agent.mode` (`auto` | `llm` | `deterministic`).
In `auto`, the LLM agent is used and any LLM error falls back to the deterministic agent for that request; the
fallback is recorded in the trace and the recommendation's `uncertainty`.

## 2a. Deployed Databricks agent (Mosaic AI Agent Framework)

`agent_endpoint/loan_servicing_agent.py` is an MLflow **ResponsesAgent** (models-from-code) deployed by
`notebooks/11_deploy_agent.py` (`src/databricks.py`):

- **Model:** Claude via the Foundation Model API (`databricks-claude-sonnet-5-5`), tool calling.
- **Tools:** the 17 Unity Catalog SQL functions `lsi_*` (`src/tools.py`). Tool names, descriptions,
  and parameter schemas are read from Unity Catalog at start-up; each call executes
  `SELECT * FROM <function>(...)` on the serverless SQL warehouse.
- **Registered model:** `main.loan_servicing_intelligence.loan_servicing_agent` (Unity Catalog).
- **Serving:** endpoint `loan-servicing-agent`, scale-to-zero, with automatic authentication passthrough for the
  declared resources (LLM endpoint, warehouse, functions, tables), MLflow tracing of every LLM and tool span,
  review app, and AI Playground access.
- **Read-only by design:** it investigates and recommends; approval, edits, and scheduling happen in the app.
- **In the app:** the *Meet the Agent* page shows endpoint status, model version, links, the live tool catalog
  from Unity Catalog, and a chat that displays each tool call and its rows.

The in-app agent (`ToolCallingLoanServicingAgent`, 29 Python tools) remains the engine for Loan 360 assessments
and backend triage because it builds validated recommendations and outbound event drafts against live state.

## 3. Assessment loop (LLM agent)

```text
1. Build messages: system instruction + task ("Assess loan X on processing date P").
2. Offer tool schemas (29 servicing tools + submit_recommendation).
3. Loop (max 12 iterations):
     model -> tool_calls -> ToolExecutor runs each (typed input validation, timing, logging) -> results appended
     stop when the model calls submit_recommendation or returns text.
4. Guardrail completion: RecommendationBuilder ensures the mandatory facts exist
   (loan context, current milestone, follow-up status, escalation, score, allowed actions, pending action,
   prior rejection, existing events). Missing ones are executed and labeled `guardrail` in the trace.
5. Enforce: recommended_action ∈ allowed_actions, else use the deterministic default and add an uncertainty note.
6. Prepare the event deterministically (calculate_followup_date, prepare_followup_event / prepare_escalation)
   and validate (validate_proposed_event). Validation failures are surfaced, not hidden.
7. Assemble the Recommendation (status PENDING_REVIEW, requires_human_approval = true) and persist it.
```

`submit_recommendation` arguments (from the model): `recommended_action`, `rationale`, `suggested_note`,
`suggested_outreach`, `evidence_refs` (tool names relied upon), `confidence` (`HIGH|MEDIUM|LOW`),
`uncertainty`, `missing_information`. The model **cannot** set the score, priority, conditions, dates, event
type, or allowed actions — those are copied from tool outputs.

Confidence is bounded deterministically: `DATA_EXCEPTION`, `DUPLICATE_RISK`, or `VERIFICATION_FAILURE` cap
confidence at `MEDIUM`; a fallback or failed validation caps it at `LOW`.

## 4. Deterministic agent plan

`get_loan_context → get_event_history → get_current_milestone → check_milestone_completion →
check_followup_status → get_milestone_rule → check_existing_event → check_pending_action →
check_previous_rejection → get_assigned_party → calculate_escalation_state → calculate_loan_attention_score →
get_allowed_actions → (calculate_followup_date → prepare_followup_event | prepare_escalation) →
validate_proposed_event`. The default action is the first allowed action; narrative is templated from facts.

## 5. Ask the Agent

Governed loan questions ("Why was this flagged?", "What comes next?", "What is missing?", "Is there already a
follow-up?", "What evidence supports this?", "Which rule applies?", "Explain the priority", "What happens if I
reject?", "Are there pending actions?"). The LLM agent answers with tools and must cite tool facts; the
deterministic agent maps the question to an intent by keywords and answers from tool results. Answers include
the tool calls made. Questions outside servicing operations (legal advice, eligibility) are declined with a
pointer to the appropriate human role.

## 6. Portfolio briefing

Inputs are only `gold_portfolio_briefing_facts`. The LLM drafts a short narrative; a **number guard** extracts
every number in the draft and rejects the draft if any number is not present in the facts (dates and
percentages derived from facts are included in the allowed set). On rejection or LLM failure the templated
deterministic briefing is used. The UI labels which path produced the briefing.

## 7. System instruction (summary)

The full text is in `src/agent.py`. It instructs the agent to:

- support authorized loan-servicing specialists; it is not the decision-maker;
- obtain every fact from tools and never invent loans, dates, amounts, statuses, metrics, or scores;
- distinguish tool facts from interpretation;
- avoid legal conclusions and legal/financial advice; avoid eligibility or regulated decisions;
- recommend only actions returned by `get_allowed_actions`;
- never calculate or alter the attention score, escalation, or dates;
- check for duplicates, pending actions, and prior rejections before recommending;
- state uncertainty and missing information explicitly;
- treat every action as a proposal requiring human approval; never claim an action was executed;
- keep notes and outreach factual, neutral, and free of borrower-sensitive speculation.

## 8. Recommendation schema

`recommendation_id, loan_id, primary_condition, secondary_conditions, attention_score, priority,
score_drivers, recommended_action, recommended_event_type, recommended_followup_date, suggested_note,
suggested_outreach, rationale, evidence[], confidence, uncertainty, missing_information, tool_calls[],
created_at, agent_version, rule_version, scoring_version, status, requires_human_approval`
plus `allowed_actions`, `escalation_state`, `state_fingerprint`, `validation`, `agent_mode`.

Evidence item: `source_type` (`TOOL`, `EVENT`, `RULE`, `ACTION`, `DECISION`), `source_identifier`,
`description`, `value`, `observed_at`.

Statuses: `PENDING_REVIEW`, `APPROVED`, `REJECTED`, `DEFERRED`, `ESCALATED`, `SUPERSEDED`, `FAILED`.
A new assessment supersedes earlier `PENDING_REVIEW` recommendations for the same loan.

## 9. Prohibited behaviors and enforcement

| Prohibited | Enforcement |
|-----------|-------------|
| Modify the System of Record | Agent has no adapter access; only ActionService (after approval) calls the adapter |
| Bypass validation | ActionService revalidates on approval regardless of agent output |
| Override escalation | Escalation copied from tool output; model output ignored |
| Invent data/metrics | Facts copied from tools; briefing number guard |
| Calculate the score | Score only from `calculate_loan_attention_score` |
| Recommend unallowed actions | Builder enforcement + validation `ACTION_NOT_ALLOWED` |
| Execute without approval | `requires_human_approval = true`; no submit path from the agent |
| Self-modify from feedback | Feedback stored for offline evaluation only |

## 10. Failure handling

Tool exception → `ToolResult(success=false, error)`, logged. LLM error/timeout → deterministic fallback
(auto mode) or a `FAILED` recommendation with no action (llm mode). Any failure: no action, status surfaced in
the UI ("Agent analysis failed — route to specialist review"), activity recorded.

## 11. Observability

Each run has a `run_id`. Every step and tool call is persisted to `ops_agent_activity` with summarized inputs
and outputs, duration, success, and error. If `mlflow` is importable, runs are wrapped in MLflow traces
(`src/service.py`). Prompts, credentials, and model reasoning are never stored.

## 12. Improvement process

Reviewer edits/rejections and evaluation results feed an **offline** review: proposed prompt, rule, or scoring
changes are made in a branch, evaluated against the scenario manifest and historical decisions, reviewed, and
promoted by version bump. Nothing changes automatically.
