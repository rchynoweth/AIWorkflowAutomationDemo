# Evaluation Plan — Loan Servicing Intelligence

> All metrics are computed on synthetic data and are labeled as such. They demonstrate methodology, not
> real-world performance.

## 1. Principle: evaluate rules and agent separately

| Layer | Question | Ground truth | Expected quality |
|-------|----------|--------------|------------------|
| Deterministic rules | Did the engine detect the right condition, priority, default action, verification status? | Scenario manifest | 100% (any miss is a defect) |
| Agent | Did the agent choose a sensible allowed action, cite evidence, avoid failures? | Manifest expected action + compliance checks | Measured, tracked over versions |
| Human review | Do specialists accept, edit, reject, defer? | Reviewer decisions | Signal for offline improvement only |
| Verification | Did approved actions land correctly? | Verifier output | Operational KPI |

## 2. Datasets

- **Scenario manifest** (`demo_scenario_manifest.csv`): 20 deterministic scenarios with expected condition,
  priority, action, verification status.
- **Synthetic reviewer history** (`reviewer_decisions.csv`): historical APPROVE/EDIT/REJECT/DEFER decisions.
- **Live decisions** (`ops_reviewer_decisions`) during a demo.

## 3. Metrics

### Rule metrics (`src/evaluation.py`)
- `condition_accuracy` = matches(primary_condition) / scenarios
- `priority_accuracy`, `default_action_accuracy`, `verification_accuracy` (NOT_APPLICABLE ⇔ no action awaiting/after verification)
- Per-scenario pass/fail with expected vs actual.

### Agent metrics (`src/evaluation.py`)
- `action_agreement` = recommended_action == expected_action
- `allowed_action_compliance` = recommended_action ∈ allowed_actions (must be 100%)
- `evidence_coverage` = recommendations with ≥ 3 evidence items / total
- `score_integrity` = recommendation score == engine score (must be 100%)
- `tool_failure_rate` = failed tool calls / tool calls
- `fallback_rate` = deterministic fallbacks / LLM runs
- `false_positive_rate` = recommended a creating action where expected NO_ACTION
- `false_negative_rate` = recommended NO_ACTION where expected an action
- `mean_tool_calls`, `mean_latency_ms`

### Reviewer metrics (`src/evaluation.py`)
`acceptance_rate` (APPROVE), `edit_rate`, `rejection_rate`, `deferral_rate`, `escalation_rate`, over
synthetic history and live decisions separately and combined.

### Verification metrics
`verification_success_rate` = VERIFIED / (VERIFIED + NOT_FOUND + MISMATCH + DUPLICATE + FAILED); distribution.

## 4. Procedure

1. `notebooks/06_run_evaluation.py` (or `POST /api/evaluation/summary` in the app) evaluates the current
   portfolio against the manifest (rule metrics).
2. Runs the agent on each scenario loan (deterministic by default; `agent_mode=llm` widget to evaluate the LLM).
3. Writes row-level results to `gold_agent_evaluation` and logs aggregate metrics to an MLflow run
   (`/Shared/loan-servicing-intelligence-evaluation` experiment when available).
4. Results appear on the Evaluation page.

## 5. Acceptance gates

- Rule metrics: 100% on all four.
- Agent: allowed-action compliance 100%, score integrity 100%, tool failure rate 0% on the manifest,
  action agreement ≥ 80% for LLM mode (deterministic mode is 100% by construction).
- Any change to rules, scoring, prompts, or model must re-run evaluation; regressions block promotion.

## 6. Automated tests

`tests/integration/test_scenario_manifest.py` (rule metrics = 100%), `tests/unit/test_evaluation.py`
(metric math), `tests/integration/test_agent_tools_interaction.py` (scripted LLM: disallowed action is
overridden; score cannot be altered).

## 7. Limitations

Twenty scenarios test logic coverage, not statistical performance. LLM metrics vary by model/version and
should be tracked over time. Reviewer metrics on synthetic history are illustrative.
