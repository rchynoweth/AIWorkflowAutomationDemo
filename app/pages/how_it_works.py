"""How It Works: Databricks is the backend - data, rules, AI Functions, and the agent."""
import pandas as pd
import streamlit as st

from app import data, ui

DIAGRAM = """
digraph G {
  rankdir=LR; bgcolor="transparent"; nodesep=0.35; ranksep=0.5;
  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=11, color="#98A2B3"];
  edge [color="#667085", arrowsize=0.7, fontname="Helvetica", fontsize=9];
  exports [label="Servicing exports\\n(synthetic)", fillcolor="#EAECF0"];
  subgraph cluster_job { label="Databricks Workflow: lsi-pipeline (serverless)"; fontname="Helvetica";
    fontsize=10; style="rounded,dashed"; color="#98A2B3";
    medallion [label="Bronze -> Silver -> Gold\\nrules in SQL", fillcolor="#DCE8F7"];
    aif [label="AI Functions\\nai_query in SQL", fillcolor="#EBE4FB", color="#6941C6", penwidth=2];
    reviews [label="Agent reviews", fillcolor="#EBE4FB", color="#6941C6", penwidth=2];
    medallion -> aif; medallion -> reviews;
  }
  uc [label="Unity Catalog\\ntables - tool functions\\nregistered agent model", fillcolor="#DCE8F7"];
  agent [label="Loan Servicing Agent\\nModel Serving + Claude", fillcolor="#EBE4FB", color="#6941C6", penwidth=2];
  app [label="Databricks App", fillcolor="#FDE9D7"];
  exports -> medallion; aif -> uc; reviews -> uc [label="reviews"]; medallion -> uc;
  agent -> uc [label="tool calls"]; reviews -> agent [label="calls", style=dashed];
  app -> uc [label="reads results,\\nwrites confirmed actions"]; app -> agent [label="on-demand analysis"];
}
"""

NOTEBOOKS = [  # notebook, what it does, side
    ("01_generate_demo_data", "Lands the day's synthetic servicing exports in a Unity Catalog volume", "Workflow"),
    ("02_ingest_bronze", "Raw copy of every file as Delta, with lineage", "Workflow"),
    ("03_build_silver", "Typed, de-duplicated tables (SQL)", "Workflow"),
    ("04_build_gold", "The servicing rules in SQL: conditions, score, priority, allowed actions", "Workflow"),
    ("05_agent_tools", "Defines the agent's tools as Unity Catalog SQL functions", "Set up once"),
    ("06_build_and_deploy_agent", "Writes, tests, registers, and deploys the agent", "Set up once"),
    ("07_ai_functions", "Batch AI: ai_query writes loan summaries and a briefing", "Workflow"),
    ("08_agent_reviews", "Batch agent: drafts the next step for the top of the queue", "Workflow"),
    ("09_monitor_agent", "Traces, LLM judges, production monitoring", "Set up once"),
]

COMPONENTS = [
    ("Delta Lake + Unity Catalog", "Governed Bronze / Silver / Gold tables, lineage, permissions"),
    ("Databricks Workflows (serverless)", "One job runs the pipeline, rules, AI Functions, and agent reviews"),
    ("AI Functions", "ai_query turns rule facts into summaries directly in SQL"),
    ("Unity Catalog functions", "Governed SQL functions are the agent's tools"),
    ("Mosaic AI Agent Framework + Model Serving", "Agent registered in Unity Catalog, served with scale-to-zero"),
    ("Foundation Model API", "Claude, pay-per-token, inside the Databricks boundary"),
    ("MLflow 3", "Every agent request traced in real time and scored by LLM judges"),
    ("Databricks Apps", "This app, reading Gold and calling the agent"),
]

st.markdown("## How it works")
ui.notes("how_it_works")
st.markdown("**Databricks is the backend.** One serverless workflow turns servicing exports into governed facts, "
            "uses AI to explain them, and has an agent investigate the loans that matter. The app reads the results, "
            "calls the agent on demand, and records the actions a person confirms.")
st.graphviz_chart(DIAGRAM, use_container_width=True)
run = data.last_pipeline_run()
if run and run.get("url"):
    st.markdown(f"**Last run of `lsi-pipeline`:** {ui.nice(run['state'])}, started {run['started']}")

st.markdown("### Two sides of the same agent")
st.markdown("- **Overnight, in the workflow:** the data comes in, the rules score every loan, `ai_query` writes "
            "summaries (notebook 07), and the agent drafts the next step for the top of the queue (notebook 08).\n"
            "- **On demand, in the app:** when something changes - an attorney replies, a date moves - the specialist "
            "pastes the update and the same agent re-plans live, steered by custom instructions if needed.\n"
            "- **Human in the loop:** the agent only drafts. A person edits and confirms; the action goes to the "
            "servicing system as a bulk-upload file (no browser automation), and the next run verifies it landed.")

st.markdown("### One framework, many servicing workflows")
st.markdown("Foreclosure milestones are the first workflow. The same five layers carry the next ones - only the data, "
            "the rules, and the tools change.")
st.dataframe(pd.DataFrame([
    ("Data", "Servicing exports -> Bronze / Silver / Gold", "Tax bills and jurisdiction deadlines",
     "Invoices and payment status"),
    ("Rules (SQL)", "Milestone overdue, missing follow-up, next milestone", "Deadline and auction proximity, risk",
     "New, paid, or ready for processing"),
    ("Agent reasoning", "Investigates and drafts the next step", "Prioritizes cases, drafts escalations",
     "Checks invoices, drafts the submission"),
    ("Human review", "Specialist edits and confirms", "Specialist confirms the escalation", "Reviewer validates"),
    ("Action", "Bulk-upload file to the servicing system", "Follow-up task or escalation", "Submission to accounting"),
], columns=["Layer", "Foreclosure milestones (this demo)", "Tax delinquency", "Invoice processing"]),
    hide_index=True, use_container_width=True)

st.markdown("### The notebooks")
links = data.notebook_links()
st.dataframe(pd.DataFrame([{"Notebook": nb, "What it does": what, "Runs": side, "Open": links.get(nb)}
                           for nb, what, side in NOTEBOOKS]),
             hide_index=True, use_container_width=True,
             column_config={"Open": st.column_config.LinkColumn(display_text="Open")})

st.markdown("### Databricks components")
st.dataframe(pd.DataFrame(COMPONENTS, columns=["Component", "Role in this solution"]), hide_index=True,
             use_container_width=True)

st.markdown("### Open it in Databricks")
experiment = data.experiment_id()
resources = [
    ("Agent", data.AGENT_ENDPOINT, f"/ml/endpoints/{data.AGENT_ENDPOINT}", "The agent on Model Serving"),
    ("Agent", data.table(data.AGENT_MODEL), f"/explore/data/models/{data.CATALOG}/{data.SCHEMA}/{data.AGENT_MODEL}",
     "The agent's registered model and versions"),
    ("Agent", "Traces and monitoring", f"/ml/experiments/{experiment}/traces" if experiment else "/ml/experiments",
     "Every agent request, traced in MLflow"),
    ("Agent", "AI Playground", "/ml/playground", "Chat with the deployed agent"),
    ("Workflow", data.PIPELINE_JOB, f"/jobs/{run['job_id']}" if run else "/jobs", "The serverless pipeline"),
    ("Data", f"{data.CATALOG}.{data.SCHEMA}", f"/explore/data/{data.CATALOG}/{data.SCHEMA}",
     "Tables, tool functions, and the landing volume"),
    ("Data", "gold_loan_state", f"/explore/data/{data.CATALOG}/{data.SCHEMA}/gold_loan_state",
     "One row per loan: conditions, score, allowed actions"),
    ("Platform", "SQL warehouse", f"/sql/warehouses/{data.WAREHOUSE_ID}", "Serverless; runs the tools and app queries"),
    ("Platform", "Git folder", None, "This repository in the workspace"),
]
st.dataframe(pd.DataFrame([{"Type": kind, "Resource": name,
                            "Link": links.get("repo") if path is None else data.link(path), "What it is": what}
                           for kind, name, path, what in resources]),
             hide_index=True, use_container_width=True,
             column_config={"Link": st.column_config.LinkColumn(display_text="Open")})
