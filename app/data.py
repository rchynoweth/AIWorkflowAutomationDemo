"""Everything the app reads or writes in Databricks: SQL on the warehouse, the agent endpoint, and resource links.

The app is a thin window: the facts come from the Gold tables (notebook 04), the AI from notebooks 07 and 08,
and on-demand analysis from the deployed Loan Servicing Agent (notebook 06).
"""
from __future__ import annotations

import json
import os
import time
import uuid
from datetime import date, datetime, timedelta

import streamlit as st
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementParameterListItem, StatementState

CATALOG = os.environ.get("LSI_CATALOG", "main")
SCHEMA = os.environ.get("LSI_SCHEMA", "loan_servicing_intelligence")
WAREHOUSE_ID = os.environ.get("DATABRICKS_WAREHOUSE_ID", "")
AGENT_ENDPOINT = "loan-servicing-agent"
AGENT_MODEL = "loan_servicing_agent"
LLM_ENDPOINT = "databricks-claude-sonnet-5-5"
PIPELINE_JOB = "lsi-pipeline"

# What each action creates in the servicing system: (event type, follow-up days; None = the milestone's default).
ACTIONS = {
    "CREATE_FOLLOWUP": ("FOLLOWUP", None),
    "CREATE_NEXT_MILESTONE": ("MILESTONE", None),
    "ESCALATE_TO_SPECIALIST": ("ESCALATION", 3),
    "CONTACT_ATTORNEY": ("CONTACT", 7),
    "CONTACT_SERVICING_VENDOR": ("CONTACT", 7),
    "REQUEST_INFORMATION": ("INFO_REQUEST", 5),
    "REVIEW_DATA_EXCEPTION": ("DATA_REVIEW", 2),
    "RETRY_FAILED_ACTION": (None, 5),   # same event type as the action that failed
}


@st.cache_resource
def client() -> WorkspaceClient:
    return WorkspaceClient()


def table(name: str) -> str:
    return f"{CATALOG}.{SCHEMA}.{name}"


# ---- SQL on the serverless warehouse ------------------------------------------------------------------------
def sql(statement: str, **params) -> list[dict]:
    """Run a statement with named :parameters; return rows as dicts (arrays and structs parsed from JSON)."""
    w = client()
    response = w.statement_execution.execute_statement(
        statement=statement, warehouse_id=WAREHOUSE_ID, wait_timeout="50s",
        parameters=[StatementParameterListItem(name=k, value=None if v is None else str(v)) for k, v in params.items()])
    while response.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(0.5)
        response = w.statement_execution.get_statement(response.statement_id)
    if response.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(response.status.error.message if response.status.error else str(response.status.state))
    if not response.manifest or not response.result:
        return []
    columns = response.manifest.schema.columns
    rows, result = [], response.result
    while True:
        rows += result.data_array or []
        if result.next_chunk_index is None:
            break
        result = w.statement_execution.get_statement_result_chunk_n(response.statement_id, result.next_chunk_index)
    return [{c.name: _convert(value, c.type_name.value) for c, value in zip(columns, row)} for row in rows]


def _convert(value, type_name: str):
    if value is None:
        return None
    if type_name in ("INT", "LONG", "SHORT", "BYTE"):
        return int(value)
    if type_name in ("DOUBLE", "FLOAT", "DECIMAL"):
        return float(value)
    if type_name == "BOOLEAN":
        return value == "true"
    if type_name in ("ARRAY", "STRUCT", "MAP"):
        return json.loads(value)
    return value


# ---- Reads ------------------------------------------------------------------------------------------------
@st.cache_data(ttl=60, show_spinner=False)
def loans() -> list[dict]:
    return sql(f"""
        SELECT loan_id, borrower_display_name, property_state, property_county, priority, primary_condition,
               attention_score, queue_rank, recommended_action, processing_date
        FROM {table('gold_loan_state')}
        WHERE is_active
        ORDER BY queue_rank""")


@st.cache_data(ttl=60, show_spinner=False)
def loan(loan_id: str) -> dict | None:
    rows = sql(f"SELECT * FROM {table('gold_loan_state')} WHERE loan_id = :loan_id", loan_id=loan_id)
    return rows[0] if rows else None


@st.cache_data(ttl=60, show_spinner=False)
def events(loan_id: str) -> list[dict]:
    """The loan's servicing events, plus any the app created since the last pipeline run."""
    return sql(f"""
        SELECT event_id, event_date, event_type, milestone_type, followup_date, completed_date, status, event_note,
               event_id LIKE 'EVT-APP-%' AS from_app
        FROM {table('silver_loan_events')}
        WHERE loan_id = :loan_id AND event_type <> 'PAYMENT_RECEIVED'
        UNION ALL
        SELECT event_id, event_date, event_type, milestone_type, followup_date, NULL, status, event_note, true
        FROM {table('servicing_system_events')}
        WHERE loan_id = :loan_id
          AND event_id NOT IN (SELECT event_id FROM {table('silver_loan_events')} WHERE loan_id = :loan_id)
        ORDER BY event_date, event_id""", loan_id=loan_id)


@st.cache_data(ttl=60, show_spinner=False)
def latest_app_action(loan_id: str) -> dict | None:
    """The last action confirmed in the app for this loan, and its verification once the pipeline has run."""
    rows = sql(f"""
        SELECT a.action_id, a.action_type, a.followup_date, a.submitted_at, v.verification_status
        FROM {table('app_actions')} a
        LEFT JOIN {table('gold_action_verification')} v USING (action_id)
        WHERE a.loan_id = :loan_id
        ORDER BY a.submitted_at DESC
        LIMIT 1""", loan_id=loan_id)
    return rows[0] if rows else None


@st.cache_data(ttl=120, show_spinner=False)
def backend_ai() -> dict:
    """AI created in Databricks: AI Functions summaries and briefing (notebook 07), agent reviews (notebook 08)."""
    out = {"insights": {}, "reviews": {}, "briefing": None}
    try:
        out["insights"] = {r["loan_id"]: r for r in sql(
            f"SELECT loan_id, ai_summary, model_endpoint, generated_at FROM {table('gold_ai_loan_insights')}")}
        out["reviews"] = {r["loan_id"]: r for r in sql(
            f"SELECT loan_id, review, recommended_action, tools_called, tool_call_count, generated_at "
            f"FROM {table('gold_agent_loan_reviews')}")}
        briefing = sql(f"SELECT briefing, model_endpoint, generated_at FROM {table('gold_ai_portfolio_briefing')}")
        out["briefing"] = briefing[0] if briefing else None
    except RuntimeError:  # the workflow has not run yet
        pass
    return out


# ---- Human in the loop: propose, then a person confirms -------------------------------------------------------
def next_business_day(day: date) -> date:
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def proposal(state: dict, action: str) -> dict:
    """The servicing event an action would create, with defaults a person can edit before confirming."""
    event_type, days = ACTIONS.get(action, ("FOLLOWUP", None))
    if action == "RETRY_FAILED_ACTION":
        event_type = ACTIONS.get(state.get("latest_action_type"), ("FOLLOWUP",))[0]
    milestone = state["next_milestone"] if action == "CREATE_NEXT_MILESTONE" else state["current_milestone"]
    if days is None:
        days = (state["next_milestone_followup_days"] if action == "CREATE_NEXT_MILESTONE"
                else state["default_followup_days"]) or 14
    label = action.replace("_", " ").title()
    outreach = ""
    if action in ("CONTACT_ATTORNEY", "CONTACT_SERVICING_VENDOR"):
        outreach = (f"Hello {state.get('party_name') or 'team'}, please send a status update on the "
                    f"{(milestone or '').replace('_', ' ').lower()} step for synthetic loan {state['loan_id']}. "
                    "Thank you, Loan Servicing Team")
    return {"event_type": event_type, "milestone_type": milestone,
            "followup_date": next_business_day(date.today() + timedelta(days=days)),
            "note": f"{label} for {(milestone or 'the loan').replace('_', ' ').lower()}.", "outreach": outreach}


def schedule(state: dict, action: str, followup_date: date, note: str, outreach: str) -> str:
    """Record the confirmed action and the event the servicing system creates for it. Returns the action ID.

    In production the servicing system would create the event; here the app writes it to
    servicing_system_events, and the next pipeline run verifies it landed (notebook 04).
    """
    if action not in state["allowed_actions"] or action == "NO_ACTION":
        raise ValueError(f"{action} is not an allowed action for this loan.")
    if not date.today() < followup_date <= date.today() + timedelta(days=120):
        raise ValueError("The follow-up date must be within the next 120 days.")
    pending = latest_app_action(state["loan_id"])
    if pending and pending["verification_status"] in (None, "PENDING"):
        raise ValueError(f"Action {pending['action_id']} is already waiting to be verified.")
    action_id = f"ACT-APP-{uuid.uuid4().hex[:8].upper()}"
    event = proposal(state, action)
    params = dict(action_id=action_id, event_id=f"EVT-APP-{action_id[8:]}", loan_id=state["loan_id"],
                  action_type=action, event_type=event["event_type"], milestone_type=event["milestone_type"],
                  followup_date=followup_date.isoformat(), note=note, outreach=outreach or None,
                  user=st.context.headers.get("X-Forwarded-Email", "app user"))
    sql(f"""INSERT INTO {table('app_actions')} VALUES (:action_id, :loan_id, :action_type, :event_type,
            :milestone_type, CAST(:followup_date AS DATE), :note, :outreach, :user, current_timestamp())""", **params)
    sql(f"""INSERT INTO {table('servicing_system_events')} VALUES (:event_id, :loan_id, :event_type, :milestone_type,
            current_date(), CAST(:followup_date AS DATE), 'OPEN', concat(:note, ' [ref ', :action_id, ']'),
            'SERVICING_SYSTEM_ADAPTER', current_timestamp())""", **params)
    st.cache_data.clear()
    return action_id


# ---- The deployed agent ---------------------------------------------------------------------------------------
def ask_agent(messages: list[dict], instructions: str | None = None) -> dict:
    """Call the agent on Model Serving. Returns its answer and the tools it chose, with what they returned."""
    started = time.time()
    body = {"input": messages}
    if instructions:
        body["custom_inputs"] = {"instructions": instructions}   # appended to the agent's system prompt
    response = client().api_client.do("POST", f"/serving-endpoints/{AGENT_ENDPOINT}/invocations", body=body)
    steps, outputs, answer = [], {}, []
    for item in response.get("output", []):
        if item.get("type") == "function_call":
            steps.append({"call_id": item["call_id"], "tool": item["name"], "arguments": item.get("arguments")})
        elif item.get("type") == "function_call_output":
            outputs[item["call_id"]] = item.get("output")
        elif item.get("type") == "message":
            answer += [part.get("text", "") for part in item.get("content", [])]
    for step in steps:
        step["output"] = outputs.get(step["call_id"])
    return {"answer": "\n".join(answer).strip(), "steps": steps, "seconds": round(time.time() - started, 1)}


@st.cache_data(ttl=60, show_spinner=False)
def agent_status() -> dict:
    """Endpoint state, served model version, and the agent's tools as registered in Unity Catalog."""
    w = client()
    status = {"ready": "NOT_FOUND", "version": None, "tools": []}
    try:
        endpoint = w.serving_endpoints.get(AGENT_ENDPOINT)
        status["ready"] = endpoint.state.ready.value if endpoint.state and endpoint.state.ready else "UNKNOWN"
        entities = endpoint.config.served_entities if endpoint.config else []
        status["version"] = entities[0].entity_version if entities else None
    except Exception:  # noqa: BLE001 - not deployed yet
        pass
    for fn in w.functions.list(catalog_name=CATALOG, schema_name=SCHEMA):
        if fn.name.startswith("lsi_"):
            info = w.functions.get(fn.full_name)
            params = info.input_params.parameters if info.input_params else []
            status["tools"].append({"tool": fn.name, "description": info.comment,
                                    "parameters": ", ".join(p.name for p in params) or "none",
                                    "url": link(f"/explore/data/functions/{CATALOG}/{SCHEMA}/{fn.name}")})
    return status


# ---- Links into the workspace (built at runtime; no workspace URL is stored in the repo) -----------------------
@st.cache_data(show_spinner=False)
def _workspace() -> tuple[str, str]:
    w = client()
    return w.config.host.rstrip("/"), f"?o={w.get_workspace_id()}"


def link(path: str) -> str:
    host, org = _workspace()
    return f"{host}{path}{org}"


@st.cache_data(ttl=300, show_spinner=False)
def experiment_id() -> str | None:
    """The MLflow experiment the agent endpoint writes its traces to."""
    try:
        for entity in client().serving_endpoints.get(AGENT_ENDPOINT).config.served_entities or []:
            if (entity.environment_vars or {}).get("MLFLOW_EXPERIMENT_ID"):
                return entity.environment_vars["MLFLOW_EXPERIMENT_ID"]
    except Exception:  # noqa: BLE001
        pass
    return None


@st.cache_data(ttl=60, show_spinner=False)
def last_pipeline_run() -> dict | None:
    w = client()
    for job in w.jobs.list(name=PIPELINE_JOB):
        for run in w.jobs.list_runs(job_id=job.job_id, limit=1):
            state = run.state.result_state or run.state.life_cycle_state
            return {"job_id": job.job_id, "state": state.value if state else "UNKNOWN",
                    "started": datetime.fromtimestamp(run.start_time / 1000).strftime("%Y-%m-%d %H:%M"),
                    "url": run.run_page_url}
        return {"job_id": job.job_id}
    return None


@st.cache_data(ttl=300, show_spinner=False)
def notebook_links() -> dict:
    """Workspace links to the notebooks in the Git folder the app was deployed from."""
    w = client()
    try:
        app = w.apps.get(os.environ.get("DATABRICKS_APP_NAME", "loan-servicing-intelligence"))
        root = app.active_deployment.source_code_path if app.active_deployment else app.default_source_code_path
    except Exception:  # noqa: BLE001
        return {}
    links = {"repo": link(f"/browse/folders/{w.workspace.get_status(root).object_id}")}
    for item in w.workspace.list(f"{root}/notebooks"):
        if item.object_type and item.object_type.value == "NOTEBOOK":
            links[item.path.rsplit("/", 1)[-1]] = link(f"/editor/notebooks/{item.object_id}")
    return links
