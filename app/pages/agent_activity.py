"""Agent Activity: understandable trace summaries of agent, tool, reviewer, adapter, and system activity."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app.components import activity_trace
from app.components.talk_track import active_chapter_banner, notes
from app.state import get_client


def render() -> None:
    active_chapter_banner("agent_activity")
    st.markdown("## Agent activity")
    notes("agent_activity")
    st.caption("Summarized inputs and outputs only. Secrets, credentials, prompts, and model reasoning are never "
               "recorded or displayed.")
    client = get_client()
    records = client.activity(limit=2000)
    if not records:
        st.info("No activity yet. Run an agent analysis from Loan 360 or the Priority Queue.")
        return
    df = pd.DataFrame(records)
    c1, c2, c3 = st.columns(3)
    loans = sorted(x for x in df["loan_id"].dropna().unique())
    loan = c1.selectbox("Loan", ["All"] + loans, key="aa_loan")
    actors = sorted(df["actor"].dropna().unique())
    actor = c2.multiselect("Actor", actors, key="aa_actor")
    if loan != "All":
        df = df[df["loan_id"] == loan]
    if actor:
        df = df[df["actor"].isin(actor)]
    runs = list(dict.fromkeys(df["run_id"].dropna()))
    run = c3.selectbox("Run", ["All"] + runs, key="aa_run")

    recs_by_loan = {}
    if run != "All":
        run_df = df[df["run_id"] == run]
        st.markdown(f"#### Run {run}")
        activity_trace.render_flow(run_df.to_dict("records"))
        loan_ids = run_df["loan_id"].dropna().unique()
        if len(loan_ids):
            recs = client.recommendations(loan_ids[0])
            match = next((r for r in recs if r.get("run_id") == run), None)
            if match:
                st.caption(f"Recommendation {match['recommendation_id']}: {match['recommended_action']} — status "
                           f"{match['status']}")
        df = run_df
    else:
        summary = (df.groupby("actor").agg(events=("activity_id", "count"), runs=("run_id", "nunique"),
                                           failures=("success", lambda s: int((~s.astype(bool)).sum())))
                   .reset_index())
        st.dataframe(summary, hide_index=True)
    activity_trace.render_table(df.to_dict("records"), height=560)
