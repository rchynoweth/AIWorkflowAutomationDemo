"""Evaluation: deterministic rule quality vs agent quality vs human review signals (synthetic metrics)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app.ui import active_chapter_banner, notes
from app.client import ApiError, get_client


def _metrics(metrics: dict, keys: list[tuple[str, str]], pct: bool = True) -> None:
    cols = st.columns(len(keys))
    for col, (key, label) in zip(cols, keys):
        value = metrics.get(key)
        col.metric(label, f"{value * 100:.0f}%" if pct and isinstance(value, (int, float)) else value)


def render() -> None:
    active_chapter_banner("evaluation")
    st.markdown("## Evaluation")
    notes("evaluation")
    st.warning("All metrics on this page are computed on **synthetic data** and demonstrate methodology, not "
               "real-world performance.", icon=":material/science:")
    client = get_client()
    data = client.evaluation()

    st.markdown("#### 1 · Deterministic rule quality (scenario manifest)")
    st.caption("Scenario expectations apply to the source snapshot before live demo actions. Any miss is a defect.")
    _metrics(data["rule_metrics"], [("condition_accuracy", "Condition accuracy"),
                                    ("priority_accuracy", "Priority accuracy"),
                                    ("action_accuracy", "Default-action accuracy"),
                                    ("verification_accuracy", "Verification accuracy")])
    scen = pd.DataFrame(data["scenarios"])
    if not scen.empty:
        scen["passed"] = scen[[c for c in scen.columns if c.startswith("passed_")]].all(axis=1)
        with st.expander("Scenario details"):
            st.dataframe(scen[["scenario_id", "loan_id", "scenario_type", "expected_condition", "actual_condition",
                             "expected_priority", "actual_priority", "expected_action", "actual_action",
                             "expected_verification", "actual_verification", "attention_score", "passed"]],
                       hide_index=True, use_container_width=True, height=420)

    st.markdown("#### 2 · Agent quality")
    c1, c2 = st.columns([3, 1])
    c1.caption(f"Last run: {data['agent_mode']} agent at {data['agent_run_at']}. Allowed-action compliance and "
               "score integrity must be 100%; agreement is tracked across versions.")
    mode = c2.selectbox("Agent", ["deterministic", "llm"], key="eval_mode")
    if c2.button("Run agent evaluation", use_container_width=True):
        with st.spinner(f"Running {mode} agent on 20 scenario loans..."):
            try:
                client.run_evaluation(mode)
            except ApiError as exc:
                st.error(str(exc.detail))
        st.rerun()
    am = data["agent_metrics"]
    _metrics(am, [("action_agreement", "Action agreement"), ("allowed_action_compliance", "Allowed-action compliance"),
                  ("score_integrity", "Score integrity"), ("evidence_coverage", "Evidence coverage")])
    _metrics(am, [("false_positive_rate", "False positives"), ("false_negative_rate", "False negatives"),
                  ("tool_failure_rate", "Tool failure rate"), ("fallback_rate", "Fallback rate")])
    with st.expander("Per-scenario agent results"):
        st.dataframe(pd.DataFrame(data["agent_rows"]), hide_index=True, use_container_width=True)

    st.markdown("#### 3 · Human review signals")
    st.caption("Signals for controlled, offline improvement only — feedback never changes behavior automatically.")
    rm = data["reviewer_metrics"]
    rows = []
    for label, key in (("Synthetic history", "synthetic_history"), ("Live demo", "live"), ("Combined", "combined")):
        m = rm[key]
        rows.append({"Source": label, "Decisions": m["decisions"], "Acceptance": f"{m['acceptance_rate']:.0%}",
                     "Edit": f"{m['edit_rate']:.0%}", "Rejection": f"{m['rejection_rate']:.0%}",
                     "Deferral": f"{m['deferral_rate']:.0%}", "Escalation": f"{m['escalation_rate']:.0%}"})
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

    st.markdown("#### 4 · Verification")
    vm = data["verification_metrics"]
    c1, c2 = st.columns([1, 3])
    c1.metric("Verification success", f"{vm['verification_success_rate']:.0%}")
    dist = pd.DataFrame([{"status": k, "actions": v} for k, v in vm["distribution"].items()])
    if not dist.empty:
        c2.bar_chart(dist.set_index("status"), height=200)
