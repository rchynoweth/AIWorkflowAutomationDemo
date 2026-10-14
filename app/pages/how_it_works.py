"""How It Works: data origin, always-on backend, architecture, the agent, human in the loop, resources."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app.ui import active_chapter_banner, notes
from app.client import ApiError, get_client

AUTO, AI, HUMAN, SOR = "#DCE8F7", "#EBE4FB", "#FDE9D7", "#EAECF0"

DATA_FLOW = f"""
digraph D {{
  rankdir=LR; bgcolor="transparent"; nodesep=0.3; ranksep=0.4;
  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=11, color="#98A2B3"];
  edge [color="#667085", arrowsize=0.7, fontname="Helvetica", fontsize=9];
  sor [label="Servicing platform\\n(System of Record)", fillcolor="{SOR}"];
  exp [label="Daily exports\\nloans, events, actions,\\ndecisions, rules", fillcolor="{SOR}"];
  vol [label="Unity Catalog\\nlanding volume", fillcolor="{AUTO}"];
  bronze [label="Bronze\\nexact copy + lineage", fillcolor="{AUTO}"];
  silver [label="Silver\\ntyped, validated,\\nde-duplicated", fillcolor="{AUTO}"];
  gold [label="Gold\\nconditions, scores,\\nqueue, verification", fillcolor="{AUTO}"];
  sor -> exp -> vol -> bronze -> silver -> gold;
  gold -> sor [label="approved actions return as events\\nin the next export", style=dashed, constraint=false];
}}
"""

WORKFLOW = f"""
digraph W {{
  rankdir=LR; bgcolor="transparent"; nodesep=0.25; ranksep=0.35;
  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=10, color="#98A2B3"];
  edge [color="#667085", arrowsize=0.6];
  t [label="Schedule / new files", shape=oval, fillcolor="{SOR}"];
  ingest [label="Ingest\\nBronze", fillcolor="{AUTO}"];
  silver [label="Build\\nSilver", fillcolor="{AUTO}"];
  verify [label="Refresh &\\nverify actions", fillcolor="{AUTO}"];
  gold [label="Rules & scores\\nGold", fillcolor="{AUTO}"];
  triage [label="Agent triage\\n(Claude, tools)", fillcolor="{AI}", color="#6941C6", penwidth=2];
  aif [label="AI Functions\\nai_query in SQL", fillcolor="{AI}", color="#6941C6", penwidth=2];
  review [label="Proposals wait for\\nspecialist approval", fillcolor="{HUMAN}", color="#C4560C", penwidth=2];
  t -> ingest -> silver -> verify -> gold; gold -> triage; gold -> aif; triage -> review;
}}
"""

ARCHITECTURE = f"""
digraph G {{
  rankdir=LR; bgcolor="transparent"; nodesep=0.35; ranksep=0.45;
  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=11, color="#98A2B3", penwidth=1];
  edge [color="#667085", arrowsize=0.7, fontname="Helvetica", fontsize=9];
  subgraph cluster_data {{ label="Always-on backend: serverless Databricks Workflow"; fontname="Helvetica";
    fontsize=10; style="rounded,dashed"; color="#98A2B3";
    files [label="Servicing\\nexport files", fillcolor="{SOR}"];
    medallion [label="Bronze / Silver / Gold\\n(Delta, Unity Catalog)", fillcolor="{AUTO}"];
    rules [label="Deterministic rules\\n(config-driven)", fillcolor="{AUTO}"];
    triage [label="Agent triage +\\nAI Functions", fillcolor="{AI}", color="#6941C6", penwidth=2];
    files -> medallion -> rules -> triage;
  }}
  tools [label="29 approved tools\\n(Python + UC functions)", fillcolor="{AUTO}"];
  agent [label="Loan Servicing Agent\\n(Claude on Databricks)", fillcolor="{AI}", penwidth=2, color="#6941C6"];
  app [label="Databricks App\\n(API + UI)", fillcolor="{AUTO}"];
  human [label="Servicing specialist\\napprove / edit / reject", fillcolor="{HUMAN}", penwidth=2, color="#C4560C"];
  adapter [label="System adapter", fillcolor="{AUTO}"];
  sor [label="Servicing platform\\n(System of Record)", fillcolor="{SOR}"];
  rules -> tools; tools -> agent [label="facts"]; triage -> app [label="proposals"]; agent -> app [label="proposal"];
  app -> human; human -> adapter [label="approved only", color="#C4560C", fontcolor="#C4560C"];
  adapter -> sor; sor -> files [label="next export", style=dashed];
}}
"""

AGENT_LOOP = f"""
digraph A {{
  rankdir=LR; bgcolor="transparent"; nodesep=0.3;
  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=11, color="#98A2B3"];
  edge [color="#667085", arrowsize=0.7, fontname="Helvetica", fontsize=9];
  q [label="Flagged loan\\nor question", fillcolor="{SOR}"];
  llm [label="LLM decides\\nnext tool", fillcolor="{AI}", color="#6941C6", penwidth=2];
  tools [label="Deterministic tools\\ncontext - milestone - events\\nduplicates - pending - rejections\\nscore - escalation - allowed actions", fillcolor="{AUTO}"];
  guard [label="Guardrails\\nallowed actions only\\nscore & dates from tools\\nvalidation", fillcolor="{AUTO}"];
  rec [label="Recommendation\\nevidence, rationale,\\nconfidence, uncertainty,\\ndraft note & outreach", fillcolor="{AI}"];
  wait [label="Waits for\\nhuman decision", fillcolor="{HUMAN}", color="#C4560C", penwidth=2];
  q -> llm; llm -> tools [label="call"]; tools -> llm [label="structured result"];
  llm -> guard [label="submit"]; guard -> rec -> wait;
}}
"""

WHO_DOES_WHAT = [
    ("1", "Land servicing exports and build Bronze / Silver / Gold", "Automated", "Databricks Workflow"),
    ("2", "Detect upcoming, due, overdue, missing, duplicate, exception conditions", "Automated", "Rules"),
    ("3", "Score, escalate, and rank every loan", "Automated", "Rules"),
    ("4", "Verify yesterday's approved actions; return failures to the queue", "Automated", "Workflow"),
    ("5", "Triage new high-priority loans and draft proposals", "AI", "Agent (workflow)"),
    ("6", "Summarize loans and the portfolio with ai_query", "AI", "AI Functions (workflow)"),
    ("7", "Investigate a loan on demand, answer questions", "AI", "Agent (app)"),
    ("8", "Approve, edit, reject, defer, or escalate", "Human", "Specialist"),
    ("9", "Re-validate the approved action", "Automated", "Rules"),
    ("10", "Send the event to the servicing system", "Automated (after approval)", "Adapter"),
    ("11", "Change rules, prompts, or thresholds", "Human", "Controlled release"),
]

SPLIT = [
    ("Dates, statuses, milestone order", "Yes", "", ""),
    ("Duplicate / pending / rejection checks", "Yes", "", ""),
    ("Attention score, priority, escalation", "Yes", "Explains", ""),
    ("Which tools to call, in what order", "", "Yes", ""),
    ("Recommendation (from the allowed list)", "Limits", "Proposes", "Decides"),
    ("Rationale, note, outreach drafts", "", "Drafts", "Edits"),
    ("Executing any consequential action", "", "", "Yes"),
    ("Verification of outcome", "Yes", "", "Reviews failures"),
]


def legend() -> None:
    st.markdown(
        f'<span style="background:{AUTO};padding:3px 10px;border-radius:8px">Automated (rules / workflow)</span> &nbsp;'
        f'<span style="background:{AI};padding:3px 10px;border-radius:8px">AI agent</span> &nbsp;'
        f'<span style="background:{HUMAN};padding:3px 10px;border-radius:8px">Human in the loop</span> &nbsp;'
        f'<span style="background:{SOR};padding:3px 10px;border-radius:8px">Source / System of Record</span>',
        unsafe_allow_html=True)


def _backend_live(client) -> None:
    try:
        status = client.backend()
    except ApiError as exc:
        st.caption(f"Live status unavailable: {exc.detail}")
        return
    monitor = next((w for w in status.get("workflows", []) if w.get("name") == "lsi-servicing-monitor"), None)
    if not status.get("available") or not monitor or not monitor.get("found"):
        st.caption("Live status appears here when the app runs in Databricks with the workflow deployed.")
        return
    runs = pd.DataFrame(monitor["runs"])
    c1, c2, c3 = st.columns(3)
    c1.metric("Workflow", "lsi-servicing-monitor")
    c2.metric("Schedule", "Every 30 min" + (" (paused)" if monitor.get("schedule_paused") else ""))
    c3.metric("Last run", (runs.iloc[0]["state"].title() if not runs.empty else "Never"))
    if not runs.empty:
        runs["tasks"] = runs["tasks"].map(lambda ts: ", ".join(f"{t['task']}: {(t['state'] or '').title()}" for t in ts))
        st.dataframe(runs[["start_time", "state", "trigger", "duration_s", "tasks", "run_page_url"]].rename(columns={
            "start_time": "Started (UTC)", "state": "Result", "trigger": "Trigger", "duration_s": "Seconds",
            "tasks": "Tasks", "run_page_url": "Open"}), hide_index=True, use_container_width=True,
            column_config={"Open": st.column_config.LinkColumn(display_text="View run")})
    ai = status.get("ai_insights") or {}
    if ai.get("available") and ai.get("loans"):
        st.markdown("**Latest AI Functions output** (`gold_ai_loan_insights`, written by `ai_query` in SQL)")
        st.dataframe(pd.DataFrame(ai["loans"])[["loan_id", "priority", "ai_summary"]].rename(
            columns={"loan_id": "Loan", "priority": "Priority", "ai_summary": "AI summary"}),
            hide_index=True, use_container_width=True)


def _inventory(client) -> None:
    try:
        inv = client.resources()
    except ApiError as exc:
        st.caption(f"Inventory unavailable: {exc.detail}")
        return
    if not inv.get("available"):
        st.caption(inv.get("reason", "Inventory unavailable"))
        return
    df = pd.DataFrame(inv["items"])[["category", "resource", "what_it_is", "url"]]
    st.dataframe(df.rename(columns={"category": "Type", "resource": "Resource", "what_it_is": "What it is",
                                    "url": "Link"}), hide_index=True, use_container_width=True,
                 column_config={"Link": st.column_config.LinkColumn(display_text="Open in Databricks")})


def render() -> None:
    active_chapter_banner("how_it_works")
    client = get_client()
    st.markdown("## How it works")
    notes("how_it_works")
    c1, c2, c3 = st.columns(3)
    c1.markdown("#### Monitor everything\nA serverless workflow evaluates **every active loan, every cycle**, "
                "turning dates and events into conditions, scores, and a ranked queue.")
    c2.markdown("#### Agent investigates\nAn AI agent uses **approved tools** to gather facts and proposes an "
                "**allowed** action with evidence and drafts - in the background and on demand.")
    c3.markdown("#### People decide\nNothing is sent without a **specialist's approval**. Approved actions are "
                "re-checked, sent, and **verified** on the next refresh.")
    legend()

    st.markdown("### Where the data comes from")
    st.markdown("The servicing platform remains the System of Record. Each cycle it exports loans, servicing "
                "events, milestone rules, assignments, prior actions, and reviewer decisions. Files land in a Unity "
                "Catalog volume and flow through the medallion layers: **Bronze** keeps an exact copy with lineage, "
                "**Silver** types, validates, and de-duplicates, **Gold** holds the computed servicing state. "
                "Approved actions return as new events in the next export, which is how verification works. "
                "In this demo, a deterministic generator stands in for the servicing exports.")
    st.graphviz_chart(DATA_FLOW, use_container_width=True)

    st.markdown("### Always-on backend")
    st.markdown("The queue isn't built when someone opens the app. A **Databricks Workflow** runs on serverless "
                "compute on a schedule (or when new files arrive): it ingests the exports, rebuilds Silver, verifies "
                "submitted actions, re-runs every rule and score, then runs two AI tasks in parallel - **agent "
                "triage**, where the agent investigates new high-priority loans and leaves proposals for approval, "
                "and **AI Functions**, where `ai_query` in SQL writes loan summaries and a briefing to Gold.")
    st.graphviz_chart(WORKFLOW, use_container_width=True)
    _backend_live(client)

    st.markdown("### Architecture")
    st.graphviz_chart(ARCHITECTURE, use_container_width=True)

    st.markdown("### Who does what")
    df = pd.DataFrame(WHO_DOES_WHAT, columns=["Step", "What happens", "Mode", "Performed by"])
    colors = {"Automated": AUTO, "AI": AI, "Human": HUMAN, "Automated (after approval)": AUTO}
    st.dataframe(df.style.apply(lambda r: [f"background-color:{colors[r['Mode']]}"] * len(r), axis=1),
                 hide_index=True, use_container_width=True)

    st.markdown("### Inside the agent")
    st.graphviz_chart(AGENT_LOOP, use_container_width=True)
    a, b = st.columns(2)
    with a:
        st.markdown("**What the agent may do**\n"
                    "- Choose which of 29 tools to call, and when it has enough evidence\n"
                    "- Recommend one action **from the allowed list**\n"
                    "- Explain why, cite evidence, state uncertainty and missing information\n"
                    "- Draft the servicing note and outreach message\n"
                    "- Answer questions about a loan, and summarize the portfolio")
    with b:
        st.markdown("**What the agent can never do**\n"
                    "- Calculate or change the score, dates, statuses, or escalation\n"
                    "- Recommend an action that isn't allowed (it gets replaced)\n"
                    "- Send anything to the servicing system\n"
                    "- Make legal, eligibility, or other regulated decisions\n"
                    "- Change its own rules from feedback")
    st.caption("If the model is unavailable, a deterministic agent produces the same structure, so the workflow "
               "keeps running.")

    st.markdown("### Rules vs agent vs people")
    st.dataframe(pd.DataFrame(SPLIT, columns=["Decision", "Rules", "Agent", "Human"]), hide_index=True,
                 use_container_width=True)

    st.markdown("### Databricks resource inventory")
    _inventory(client)
    with st.expander("Databricks capabilities used"):
        st.markdown("- **Serverless Workflows**: setup pipeline and the recurring servicing monitor\n"
                    "- **Delta Lake + Unity Catalog**: governed tables, landing volume, lineage, SQL tool functions\n"
                    "- **AI Functions** (`ai_query`): loan summaries and briefing in SQL\n"
                    "- **Foundation Model API** (pay-per-token Claude): the tool-calling agent\n"
                    "- **Serverless SQL warehouse** (auto-stop): app reads and writes\n"
                    "- **Databricks Apps**: Streamlit UI with an in-process REST API\n"
                    "- **MLflow**: evaluation runs\n\nAll data, rules, and thresholds are synthetic.")
