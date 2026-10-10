"""How It Works: architecture, end-to-end flow, the agent, and where humans stay in the loop."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app.components.talk_track import active_chapter_banner, notes

AUTO, AI, HUMAN, SOR = "#DCE8F7", "#EBE4FB", "#FDE9D7", "#EAECF0"

ARCHITECTURE = f"""
digraph G {{
  rankdir=LR; bgcolor="transparent"; nodesep=0.35; ranksep=0.45;
  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=11, color="#98A2B3", penwidth=1];
  edge [color="#667085", arrowsize=0.7, fontname="Helvetica", fontsize=9];

  subgraph cluster_data {{ label="Lakehouse (serverless jobs, Delta, Unity Catalog)"; fontname="Helvetica"; fontsize=10;
    style="rounded,dashed"; color="#98A2B3";
    files [label="Servicing\\nexport files", fillcolor="{SOR}"];
    bronze [label="Bronze\\nraw + lineage", fillcolor="{AUTO}"];
    silver [label="Silver\\nclean + validated", fillcolor="{AUTO}"];
    gold [label="Gold\\nconditions, scores,\\npriority queue", fillcolor="{AUTO}"];
    files -> bronze -> silver -> gold;
  }}
  rules [label="Deterministic rules\\n(config-driven)", fillcolor="{AUTO}"];
  tools [label="29 approved tools\\n(Python + UC functions)", fillcolor="{AUTO}"];
  agent [label="Loan Servicing Agent\\n(Claude on Databricks)", fillcolor="{AI}", penwidth=2, color="#6941C6"];
  app [label="Databricks App\\n(API + UI)", fillcolor="{AUTO}"];
  human [label="Servicing specialist\\napprove / edit / reject", fillcolor="{HUMAN}", penwidth=2, color="#C4560C"];
  adapter [label="System adapter", fillcolor="{AUTO}"];
  sor [label="Servicing platform\\n(System of Record)", fillcolor="{SOR}"];
  verify [label="Verification", fillcolor="{AUTO}"];

  silver -> rules [style=dashed]; rules -> gold [style=dashed];
  gold -> tools; tools -> agent [label="facts"]; agent -> app [label="proposal"];
  app -> human; human -> adapter [label="approved only", color="#C4560C", fontcolor="#C4560C"];
  adapter -> sor; sor -> files [label="next refresh", style=dashed];
  gold -> verify [style=dashed]; verify -> app [label="verified / returned", style=dashed];
}}
"""

AGENT_LOOP = f"""
digraph A {{
  rankdir=LR; bgcolor="transparent"; nodesep=0.3;
  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=11, color="#98A2B3"];
  edge [color="#667085", arrowsize=0.7, fontname="Helvetica", fontsize=9];
  q [label="Flagged loan\\nor question", fillcolor="{SOR}"];
  llm [label="LLM decides\\nnext tool", fillcolor="{AI}", color="#6941C6", penwidth=2];
  tools [label="Deterministic tools\\ncontext · milestone · events\\nduplicates · pending · rejections\\nscore · escalation · allowed actions", fillcolor="{AUTO}"];
  guard [label="Guardrails\\nallowed actions only\\nscore & dates from tools\\nvalidation", fillcolor="{AUTO}"];
  rec [label="Recommendation\\n+ evidence, rationale,\\nconfidence, uncertainty,\\ndraft note & outreach", fillcolor="{AI}"];
  wait [label="Waits for\\nhuman decision", fillcolor="{HUMAN}", color="#C4560C", penwidth=2];
  q -> llm; llm -> tools [label="call"]; tools -> llm [label="structured result"];
  llm -> guard [label="submit"]; guard -> rec -> wait;
}}
"""

WHO_DOES_WHAT = [
    ("1", "Ingest servicing exports into Bronze/Silver/Gold", "Automated", "Serverless job"),
    ("2", "Detect upcoming, due, overdue, missing, duplicate, exception conditions", "Automated", "Deterministic rules"),
    ("3", "Score, escalate, and rank every loan", "Automated", "Deterministic rules"),
    ("4", "Write the daily portfolio briefing", "AI", "Agent, fact-checked"),
    ("5", "Investigate a flagged loan with tools", "AI", "Agent"),
    ("6", "Recommend an allowed action, draft note and outreach", "AI", "Agent"),
    ("7", "Approve, edit, reject, defer, or escalate", "Human", "Specialist"),
    ("8", "Re-validate the approved action", "Automated", "Rules"),
    ("9", "Send the event to the servicing system", "Automated (after approval)", "Adapter"),
    ("10", "Verify it landed on the next refresh; return failures", "Automated", "Verification"),
    ("11", "Change rules, prompts, or thresholds", "Human", "Controlled release"),
]

SPLIT = [
    ("Dates, statuses, milestone order", "✔", "", ""),
    ("Duplicate / pending / rejection checks", "✔", "", ""),
    ("Attention score, priority, escalation", "✔", "explains", ""),
    ("Which tools to call, in what order", "", "✔", ""),
    ("Recommendation (from allowed list)", "limits", "✔", "decides"),
    ("Rationale, note, outreach drafts", "", "✔", "edits"),
    ("Executing any consequential action", "", "", "✔"),
    ("Verification of outcome", "✔", "", "reviews failures"),
]


def legend() -> None:
    st.markdown(
        f'<span style="background:{AUTO};padding:3px 10px;border-radius:8px">Automated (rules)</span> &nbsp;'
        f'<span style="background:{AI};padding:3px 10px;border-radius:8px">AI agent</span> &nbsp;'
        f'<span style="background:{HUMAN};padding:3px 10px;border-radius:8px">Human in the loop</span> &nbsp;'
        f'<span style="background:{SOR};padding:3px 10px;border-radius:8px">Source / System of Record</span>',
        unsafe_allow_html=True)


def render() -> None:
    active_chapter_banner("how_it_works")
    st.markdown("## How it works")
    notes("how_it_works")
    c1, c2, c3 = st.columns(3)
    c1.markdown("#### 🔎 Monitor everything\nRules evaluate **every active loan, every cycle**, and turn dates and "
                "events into conditions, scores, and a ranked queue.")
    c2.markdown("#### ✨ Agent investigates\nAn AI agent uses **approved tools** to gather facts, then proposes an "
                "**allowed** action with evidence and drafts.")
    c3.markdown("#### ✋ People decide\nNothing is sent without a **specialist's approval**. Approved actions are "
                "re-checked, sent, and **verified**.")

    st.markdown("### Architecture")
    legend()
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
    st.caption("If the model is unavailable, a deterministic agent produces the same structure, so the demo "
               "and the workflow keep working.")

    st.markdown("### Rules vs agent vs people")
    st.dataframe(pd.DataFrame(SPLIT, columns=["Decision", "Rules", "Agent", "Human"]), hide_index=True,
                 use_container_width=True)

    with st.expander("Databricks components used"):
        st.markdown("- **Serverless Jobs**: notebooks for generate → Bronze → Silver → Gold → tools → evaluation\n"
                    "- **Delta Lake + Unity Catalog**: governed tables, a landing volume, and SQL tool functions\n"
                    "- **Serverless SQL warehouse** (auto-stop): app reads and writes\n"
                    "- **Foundation Model API** (pay-per-token Claude): the agent\n"
                    "- **Databricks Apps**: Streamlit UI with an in-process REST API\n"
                    "- **MLflow**: evaluation runs\n\nAll data, rules, and thresholds are synthetic.")
