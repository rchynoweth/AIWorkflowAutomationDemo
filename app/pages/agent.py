"""Meet the Agent: the deployed Loan Servicing Agent, its Unity Catalog tools, guardrails, and a live chat."""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from app.components.styles import badge, esc
from app.components.talk_track import active_chapter_banner, notes
from app.state import ApiError, get_client

PROMPTS = [
    "Why is loan LSI-SYN-000005 prioritized, and what should happen next?",
    "Which loans need attention first today?",
    "Is anything already pending for LSI-SYN-000019?",
    "Which specialists carry the most critical work?",
]

LOOP = """
digraph A {
  rankdir=LR; bgcolor="transparent"; nodesep=0.3;
  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=11, color="#98A2B3"];
  edge [color="#667085", arrowsize=0.7, fontname="Helvetica", fontsize=9];
  q [label="Question\\n(app, Playground,\\nworkflow)", fillcolor="#EAECF0"];
  llm [label="Claude on Databricks\\nchooses next tool", fillcolor="#EBE4FB", color="#6941C6", penwidth=2];
  uc [label="Unity Catalog tools\\nlsi_* SQL functions", fillcolor="#DCE8F7"];
  data [label="Governed Delta tables\\nGold / Silver / ops", fillcolor="#DCE8F7"];
  ans [label="Answer with evidence\\n(read-only)", fillcolor="#EBE4FB"];
  human [label="Specialist approves\\nin the app", fillcolor="#FDE9D7", color="#C4560C", penwidth=2];
  q -> llm; llm -> uc [label="call"]; uc -> data; data -> uc; uc -> llm [label="rows"]; llm -> ans -> human;
}
"""


def _status_badge(dep: dict) -> str:
    if not dep.get("endpoint_found"):
        return badge("Not deployed", "#B42318")
    if dep.get("ready") == "READY":
        return badge("Ready", "#067647")
    if dep.get("config_update") == "IN_PROGRESS":
        return badge("Deploying", "#B54708")
    return badge(dep.get("ready", "Unknown").title(), "#475467")


def _header(dep: dict) -> None:
    links = dep.get("links", {})
    st.markdown(f"<div style='font-size:1.25rem; font-weight:700'>Loan Servicing Agent &nbsp; {_status_badge(dep)}"
                f"</div><div class='lsi-why'>A tool-calling agent deployed on Databricks Model Serving. It reads "
                f"governed data only through Unity Catalog functions and never acts on its own.</div>",
                unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Model", "Claude (Foundation Model API)", help=dep.get("llm_endpoint"))
    c2.metric("Registered in Unity Catalog", f"v{dep.get('model_version') or '-'}", help=dep.get("model_name"))
    c3.metric("Serving endpoint", dep.get("endpoint_name", "-"),
              help="Scale-to-zero: idle cost is zero; the first call after idle wakes it up"
              if dep.get("scale_to_zero") else None)
    c4.metric("Tools", f"{len(dep.get('tools') or [])} UC functions")
    b1, b2, b3, b4 = st.columns(4)
    if links.get("endpoint"):
        b1.link_button("Serving endpoint", links["endpoint"], use_container_width=True, icon=":material/dns:")
        b2.link_button("Open AI Playground", links["playground"], use_container_width=True,
                       icon=":material/science:")
        b3.link_button("Model in Unity Catalog", links["model"], use_container_width=True,
                       icon=":material/inventory_2:")
        b4.link_button("Traces (MLflow)", links["experiments"], use_container_width=True, icon=":material/timeline:")


def _tools(dep: dict) -> None:
    tools = dep.get("tools") or []
    st.markdown("### Its tools - governed in Unity Catalog")
    st.caption("Each tool is a SQL function in Unity Catalog. Its description and parameters are exactly what the "
               "model sees, permissions are governed by Unity Catalog, and every call is traced.")
    if not tools:
        st.info("Tool list unavailable here; it is read live from Unity Catalog when the app runs in Databricks.")
        return
    df = pd.DataFrame(tools)
    for group in ["Loan facts", "Rules and scoring", "Safeguards", "Portfolio"]:
        part = df[df["group"] == group]
        if part.empty:
            continue
        st.markdown(f"**{group}**")
        st.dataframe(part[["tool", "description", "parameters", "url"]].rename(columns={
            "tool": "Tool", "description": "What it does", "parameters": "Parameters", "url": "Unity Catalog"}),
            hide_index=True, use_container_width=True,
            column_config={"Unity Catalog": st.column_config.LinkColumn(display_text="Open"),
                           "What it does": st.column_config.TextColumn(width="large")})


def _chat(client, dep: dict) -> None:
    st.markdown("### Try it")
    if dep.get("ready") != "READY":
        st.info("The serving endpoint is not ready yet (deploying or waking from scale-to-zero). "
                "The first call after idle can take a few minutes.")
    history = st.session_state.setdefault("agent_chat", [])
    cols = st.columns(len(PROMPTS))
    asked = None
    for i, prompt in enumerate(PROMPTS):
        if cols[i].button(prompt, key=f"agent_prompt_{i}", use_container_width=True):
            asked = prompt
    typed = st.chat_input("Ask the Loan Servicing Agent")
    asked = asked or typed
    if asked:
        history.append({"role": "user", "content": asked})
        with st.spinner("Agent is choosing tools and querying Unity Catalog..."):
            try:
                result = client.agent_chat([{"role": m["role"], "content": m["content"]} for m in history][-8:])
                history.append({"role": "assistant", "content": result["answer"], "steps": result["steps"],
                                "seconds": result["seconds"]})
            except ApiError as exc:
                history.pop()
                st.error(f"The deployed agent did not respond: {exc.detail}")
    for message in history:
        with st.chat_message(message["role"]):
            if message["role"] == "assistant" and message.get("steps"):
                chain = " → ".join(s["tool"] for s in message["steps"])
                st.markdown(f"<div class='lsi-why'>Called {len(message['steps'])} tools in "
                            f"{message.get('seconds')} s: {esc(chain)}</div>", unsafe_allow_html=True)
                with st.expander("Tool calls and results"):
                    for step in message["steps"]:
                        st.markdown(f"**{step['tool']}** `{step['arguments']}`")
                        try:
                            rows = json.loads(step["output"] or "{}").get("rows", [])
                            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
                        except (ValueError, TypeError):
                            st.code(str(step["output"])[:1500])
            st.markdown(message["content"])
    if history and st.button("Clear conversation", icon=":material/delete:"):
        st.session_state["agent_chat"] = []
        st.rerun()


def render() -> None:
    active_chapter_banner("agent")
    st.markdown("## Meet the agent")
    notes("agent")
    client = get_client()
    try:
        dep = client.agent_deployment()
    except ApiError as exc:
        st.error(f"Agent status unavailable: {exc.detail}")
        return
    if not dep.get("available"):
        st.info(dep.get("reason", "Agent status unavailable"))
        return
    _header(dep)
    st.graphviz_chart(LOOP, use_container_width=True)
    left, right = st.columns(2)
    left.markdown("**What it may do**\n- Choose which tools to call and when it has enough evidence\n"
                  "- Explain priorities and recommend an action **from the allowed list**\n"
                  "- State uncertainty and missing information\n- Answer portfolio questions")
    right.markdown("**What it can never do**\n- Change data, scores, dates, or escalation\n"
                   "- Send anything to the servicing system\n- Recommend an action that is not allowed\n"
                   "- Make legal, eligibility, or other regulated decisions")
    _chat(client, dep)
    _tools(dep)
    with st.expander("Also inside the app: the full 29-tool toolset used for live recommendations"):
        from src.tools.registry import REGISTRY
        st.caption("Loan 360 and the backend triage use this Python toolset (same rules engine) to build "
                   "recommendations, validation, and outbound event drafts.")
        st.dataframe(pd.DataFrame([{"tool": s.name, "description": s.description} for s in REGISTRY.values()]),
                     hide_index=True, use_container_width=True)
