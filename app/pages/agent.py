"""The Agent: the deployed Loan Servicing Agent, a live chat, and its Unity Catalog tools."""
import pandas as pd
import streamlit as st

from app import data, ui

PROMPTS = [
    "Why is loan LSI-SYN-000005 prioritized, and what should happen next?",
    "What should happen next on loan LSI-SYN-000007?",
    "Which loans need attention first today?",
    "Did any approved actions fail to land in the servicing system?",
]

LOOP = """
digraph A {
  rankdir=LR; bgcolor="transparent"; nodesep=0.3;
  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=11, color="#98A2B3"];
  edge [color="#667085", arrowsize=0.7, fontname="Helvetica", fontsize=9];
  q [label="Question\\n(app, Playground,\\nworkflow)", fillcolor="#EAECF0"];
  llm [label="Claude on Databricks\\nchooses next tool", fillcolor="#EBE4FB", color="#6941C6", penwidth=2];
  uc [label="Unity Catalog tools\\nlsi_* SQL functions", fillcolor="#DCE8F7"];
  data [label="Governed Delta tables\\nSilver / Gold", fillcolor="#DCE8F7"];
  ans [label="Answer with evidence\\n(read-only)", fillcolor="#EBE4FB"];
  human [label="Specialist confirms\\nin the app", fillcolor="#FDE9D7", color="#C4560C", penwidth=2];
  q -> llm; llm -> uc [label="call"]; uc -> data; data -> uc; uc -> llm [label="rows"]; llm -> ans -> human;
}
"""

st.markdown("## The agent")
ui.notes("agent")
status = data.agent_status()
ready = status["ready"] == "READY"
st.markdown(f"<div style='font-size:1.25rem; font-weight:700'>Loan Servicing Agent &nbsp; "
            f"{ui.badge('Ready' if ready else ui.nice(status['ready']), '#067647' if ready else '#B54708')}</div>"
            "<div class='lsi-muted'>A tool-calling agent built in notebook 06 and deployed on Databricks Model Serving. "
            "It reads governed data only through Unity Catalog functions and never acts on its own.</div>",
            unsafe_allow_html=True)
c1, c2, c3, c4 = st.columns(4)
c1.metric("Model", "Claude", help=f"{data.LLM_ENDPOINT} on the Foundation Model API")
c2.metric("Registered in Unity Catalog", f"v{status['version'] or '-'}", help=data.table(data.AGENT_MODEL))
c3.metric("Serving endpoint", data.AGENT_ENDPOINT, help="Scale-to-zero: the first call after idle wakes it up")
c4.metric("Tools", f"{len(status['tools'])} UC functions")
b1, b2, b3, b4 = st.columns(4)
b1.link_button("Serving endpoint", data.link(f"/ml/endpoints/{data.AGENT_ENDPOINT}"), icon=":material/dns:",
               use_container_width=True)
b2.link_button("AI Playground", data.link("/ml/playground"), icon=":material/science:", use_container_width=True)
b3.link_button("Model in Unity Catalog", data.link(f"/explore/data/models/{data.CATALOG}/{data.SCHEMA}/{data.AGENT_MODEL}"),
               icon=":material/inventory_2:", use_container_width=True)
experiment = data.experiment_id()
b4.link_button("Traces (MLflow)", data.link(f"/ml/experiments/{experiment}/traces" if experiment else "/ml/experiments"),
               icon=":material/timeline:", use_container_width=True)

st.graphviz_chart(LOOP, use_container_width=True)
left, right = st.columns(2)
left.markdown("**What it may do**\n- Choose which tools to call and when it has enough evidence\n"
              "- Explain priorities and recommend an action **from the allowed list**\n"
              "- State uncertainty and missing information\n- Answer portfolio questions")
right.markdown("**What it can never do**\n- Change data, scores, or dates\n- Send anything to the servicing system\n"
               "- Recommend an action that is not allowed\n- Make legal, eligibility, or other regulated decisions")

st.markdown("### Try it")
if not ready:
    st.info("The endpoint is waking up or deploying; the first call after idle can take a few minutes.")
history = st.session_state.setdefault("agent_chat", [])
instructions = ui.instructions_box("agent_page")
asked = None
for col, prompt in zip(st.columns(len(PROMPTS)), PROMPTS):
    if col.button(prompt, use_container_width=True):
        asked = prompt
asked = st.chat_input("Ask the Loan Servicing Agent") or asked
if asked:
    history.append({"role": "user", "content": asked})
    with st.spinner("The agent is choosing tools and querying Unity Catalog..."):
        try:
            result = data.ask_agent([{"role": m["role"], "content": m["content"]} for m in history][-8:], instructions)
            history.append({"role": "assistant", "content": result["answer"], **result})
        except Exception as exc:  # noqa: BLE001
            history.pop()
            st.error(f"The agent did not respond: {exc}")
for message in history:
    with st.chat_message(message["role"]):
        if message["role"] == "assistant":
            ui.agent_answer(message)
        else:
            st.markdown(message["content"])
if history and st.button("Clear conversation", icon=":material/delete:"):
    st.session_state["agent_chat"] = []
    st.rerun()

st.markdown("### Its tools - defined in notebook 05, governed in Unity Catalog")
st.caption("Each tool is a SQL function. Its comment and parameters are exactly what the model reads when it picks a "
           "tool; permissions come from Unity Catalog, and every call is traced in MLflow.")
st.dataframe(pd.DataFrame(status["tools"]).rename(columns={"tool": "Tool", "description": "What it does",
                                                           "parameters": "Parameters", "url": "Unity Catalog"}),
             hide_index=True, use_container_width=True,
             column_config={"Unity Catalog": st.column_config.LinkColumn(display_text="Open"),
                            "What it does": st.column_config.TextColumn(width="large")})
