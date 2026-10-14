"""Databricks integrations: workflow status, resource links, the deployed agent endpoint, agent deployment."""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone




# ====================================================================================================
# Status of the Databricks backend workflows (Jobs API) and AI Functions outputs, for the app
# ====================================================================================================

log = logging.getLogger(__name__)

PIPELINE_JOB_NAME = "lsi-pipeline"


def _client():
    from databricks.sdk import WorkspaceClient

    return WorkspaceClient()


def _ts(ms: int | None) -> str | None:
    if not ms:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def _job_id(w, env_key: str, name: str) -> int | None:
    value = os.environ.get(env_key)
    if value:
        return int(value)
    for job in w.jobs.list(name=name):
        return job.job_id
    return None


def workflow_status(limit: int = 5) -> dict:
    """Schedule and recent runs of the lsi-pipeline workflow. Never raises."""
    try:
        w = _client()
        job_id = _job_id(w, "LSI_PIPELINE_JOB_ID", PIPELINE_JOB_NAME)
        if job_id is None:
            return {"available": False, "reason": f"Workflow {PIPELINE_JOB_NAME} not found"}
        job = w.jobs.get(job_id)
        schedule = job.settings.schedule
        runs = []
        for run in w.jobs.list_runs(job_id=job_id, limit=limit, expand_tasks=True):
            state = run.state
            runs.append({
                "run_id": run.run_id,
                "state": (state.result_state.value if state and state.result_state else
                          state.life_cycle_state.value if state and state.life_cycle_state else "UNKNOWN"),
                "start_time": _ts(run.start_time), "end_time": _ts(run.end_time),
                "duration_s": round(run.run_duration / 1000) if run.run_duration else None,
                "run_page_url": run.run_page_url,
                "tasks": {t.task_key: (t.state.result_state.value if t.state and t.state.result_state else
                                       t.state.life_cycle_state.value if t.state else None) for t in (run.tasks or [])},
            })
        return {"available": True, "name": PIPELINE_JOB_NAME, "job_id": job_id,
                "schedule_paused": (schedule.pause_status.value == "PAUSED") if schedule and schedule.pause_status
                else None, "tasks": [t.task_key for t in job.settings.tasks or []], "runs": runs}
    except Exception as exc:  # noqa: BLE001 - status is informational
        return {"available": False, "reason": str(exc)[:300]}


def run_pipeline_now() -> dict:
    w = _client()
    job_id = _job_id(w, "LSI_PIPELINE_JOB_ID", PIPELINE_JOB_NAME)
    if job_id is None:
        raise RuntimeError(f"Workflow {PIPELINE_JOB_NAME} not found")
    return {"job_id": job_id, "run_id": w.jobs.run_now(job_id=job_id).run_id}


def latest_success_end(status: dict) -> str | None:
    for run in status.get("runs", []):
        if run["state"] == "SUCCESS" and run.get("end_time"):
            return run["end_time"]
    return None


def backend_ai(repository) -> dict:
    """AI created in Databricks: AI Functions summaries (notebook 07) and agent reviews (notebook 08)."""
    empty = {"available": False, "insights": {}, "reviews": {}, "briefing": None}
    if getattr(repository, "backend", "local") != "databricks" or not hasattr(repository, "execute"):
        return {**empty, "reason": "AI outputs are read from Databricks Gold tables when running in Databricks."}
    out = dict(empty, available=True)
    queries = {
        "insights": f"SELECT loan_id, ai_summary, model_endpoint, CAST(generated_at AS STRING) AS generated_at "
                    f"FROM {repository.fq('gold_ai_loan_insights')}",
        "reviews": f"SELECT loan_id, review, recommended_action, tools_called, CAST(tool_call_count AS INT) AS "
                   f"tool_call_count, seconds, agent_endpoint, CAST(generated_at AS STRING) AS generated_at "
                   f"FROM {repository.fq('gold_agent_loan_reviews')}",
        "briefing": f"SELECT briefing, model_endpoint, CAST(generated_at AS STRING) AS generated_at "
                    f"FROM {repository.fq('gold_ai_portfolio_briefing')} LIMIT 1",
    }
    for key, sql in queries.items():
        try:
            rows = repository.execute(sql)
        except Exception as exc:  # noqa: BLE001 - table may not exist until the workflow runs
            log.warning("backend AI read failed for %s: %s", key, exc)
            continue
        out[key] = rows[0] if key == "briefing" and rows else ({r["loan_id"]: r for r in rows} if key != "briefing"
                                                                else None)
    return out


def resource_inventory(settings) -> dict:
    """Links to the Databricks resources behind the demo, built from the runtime workspace host (never committed)."""
    try:
        w = _client()
        host = w.config.host.rstrip("/")
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": f"Databricks SDK unavailable: {exc}"}
    try:
        org = f"?o={w.get_workspace_id()}"
    except Exception:  # noqa: BLE001
        org = ""
    cat, sch = settings.catalog, settings.schema
    vol = settings.application["databricks"]["landing_volume"]
    items = []

    def add(category: str, name: str, path: str, note: str) -> None:
        items.append({"category": category, "resource": name, "url": f"{host}{path}{org}", "what_it_is": note})

    app_name = os.environ.get("DATABRICKS_APP_NAME", "loan-servicing-intelligence")
    add("App", app_name, f"/apps/{app_name}", "Databricks App: Streamlit UI + in-process agent API")
    for env_key, name, note in (("LSI_PIPELINE_JOB_ID", PIPELINE_JOB_NAME,
                                 "Workflow: data pipeline, rules, AI Functions, agent reviews (serverless)"),):
        try:
            job_id = _job_id(w, env_key, name)
            if job_id:
                add("Workflow", name, f"/jobs/{job_id}", note)
        except Exception:  # noqa: BLE001
            pass
    add("Unity Catalog", f"{cat}.{sch}", f"/explore/data/{cat}/{sch}", "Schema with Bronze, Silver, Gold, ops tables")
    add("Unity Catalog", f"{cat}.{sch}.{vol}", f"/explore/data/volumes/{cat}/{sch}/{vol}",
        "Landing volume for servicing export files")
    for table, note in (("bronze_loan_events", "Raw events with lineage"),
                        ("silver_loan_events", "Validated, sequenced events"),
                        ("gold_loan_servicing_state", "Conditions, escalation, score per loan"),
                        ("gold_priority_queue", "Ranked work queue"),
                        ("gold_ai_loan_insights", "AI Functions (ai_query) summaries"),
                        ("gold_agent_loan_reviews", "Reviews written by the deployed agent"),
                        ("gold_ai_portfolio_briefing", "AI Functions portfolio briefing")):
        add("Delta table", table, f"/explore/data/{cat}/{sch}/{table}", note)
    add("Unity Catalog", "lsi_* functions", f"/explore/data/{cat}/{sch}", "SQL tool functions for agents and Genie")
    if settings.warehouse_id:
        add("Compute", "Serverless SQL warehouse", f"/sql/warehouses/{settings.warehouse_id}",
            "Serves app reads/writes; auto-stops when idle")
    endpoint = settings.agent.get("model_endpoint")
    add("AI", endpoint, f"/ml/endpoints/{endpoint}", "Foundation Model API (pay-per-token) used by the agent")
    add("AI", "MLflow experiments", "/ml/experiments", "Evaluation runs (loan-servicing-intelligence-evaluation)")
    try:
        app = w.apps.get(app_name)
        src_path = (app.active_deployment.source_code_path if app.active_deployment else None) \
            or app.default_source_code_path
        if src_path:
            folder_id = w.workspace.get_status(src_path).object_id
            add("Code", "Git folder", f"/browse/folders/{folder_id}", "Repository synced from GitHub; notebooks and src/")
    except Exception:  # noqa: BLE001
        pass
    return {"available": True, "host": host, "items": items}


# ====================================================================================================
# Client for the deployed Loan Servicing Agent (Model Serving) and its Unity Catalog toolset
# ====================================================================================================

ENDPOINT_NAME = os.environ.get("LSI_AGENT_ENDPOINT", "loan-servicing-agent")
MODEL_NAME = "loan_servicing_agent"

TOOL_GROUPS = {
    "lsi_get_loan_context": "Loan facts", "lsi_get_event_history": "Loan facts",
    "lsi_get_current_milestone": "Loan facts", "lsi_check_followup_status": "Rules and scoring",
    "lsi_get_open_followups": "Safeguards", "lsi_get_milestone_rule": "Rules and scoring",
    "lsi_get_escalation_state": "Rules and scoring", "lsi_get_attention_score": "Rules and scoring",
    "lsi_get_allowed_actions": "Safeguards", "lsi_check_pending_actions": "Safeguards",
    "lsi_check_prior_rejections": "Safeguards", "lsi_get_agent_proposals": "Loan facts",
    "lsi_get_ai_loan_insight": "Loan facts", "lsi_priority_queue": "Portfolio",
    "lsi_portfolio_health_summary": "Portfolio", "lsi_specialist_workload": "Portfolio",
    "lsi_get_failed_verifications": "Portfolio",
}
GROUP_ORDER = ["Loan facts", "Rules and scoring", "Safeguards", "Portfolio"]




def _links(w, settings) -> dict:
    host = w.config.host.rstrip("/")
    try:
        org = f"?o={w.get_workspace_id()}"
    except Exception:  # noqa: BLE001
        org = ""
    cat, sch = settings.catalog, settings.schema
    return {
        "endpoint": f"{host}/ml/endpoints/{ENDPOINT_NAME}{org}",
        "playground": f"{host}/ml/playground{org}",
        "model": f"{host}/explore/data/models/{cat}/{sch}/{MODEL_NAME}{org}",
        "experiments": f"{host}/ml/experiments{org}",
        "function_base": f"{host}/explore/data/functions/{cat}/{sch}/",
        "org": org,
    }


def deployment_status(settings) -> dict:
    """Endpoint state, model version, links, and the Unity Catalog toolset. Never raises."""
    try:
        w = _client()
        links = _links(w, settings)
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": f"Databricks SDK unavailable: {exc}"}
    out = {"available": True, "endpoint_name": ENDPOINT_NAME, "links": links,
           "model_name": f"{settings.catalog}.{settings.schema}.{MODEL_NAME}",
           "llm_endpoint": settings.agent.get("model_endpoint")}
    try:
        ep = w.serving_endpoints.get(ENDPOINT_NAME)
        ready = ep.state.ready.value if ep.state and ep.state.ready else "UNKNOWN"
        updating = ep.state.config_update.value if ep.state and ep.state.config_update else None
        entities = (ep.config.served_entities if ep.config else None) or []
        entity = entities[0] if entities else None
        pending = ((ep.pending_config.served_entities if ep.pending_config else None) or [None])[0]
        state = None
        if entity and entity.state and entity.state.deployment:
            state = entity.state.deployment.value
        out.update({
            "endpoint_found": True, "ready": ready, "config_update": updating,
            "model_version": (entity or pending).entity_version if (entity or pending) else None,
            "scale_to_zero": (entity or pending).scale_to_zero_enabled if (entity or pending) else None,
            "deployment_state": state,
        })
    except Exception as exc:  # noqa: BLE001
        out.update({"endpoint_found": False, "endpoint_error": str(exc)[:200]})
    out["tools"] = uc_tools(w, settings, links)
    return out


def uc_tools(w, settings, links: dict | None = None) -> list[dict]:
    links = links or _links(w, settings)
    tools = []
    try:
        for fn in w.functions.list(catalog_name=settings.catalog, schema_name=settings.schema):
            if not fn.name.startswith("lsi_"):
                continue
            try:
                info = w.functions.get(fn.full_name)
                params = [f"{p.name} ({p.type_name.value.lower() if p.type_name else 'string'})"
                          for p in ((info.input_params.parameters if info.input_params else None) or [])]
                comment = (info.comment or "").replace(" (synthetic demonstration data)", "")
            except Exception:  # noqa: BLE001
                params, comment = [], fn.comment or ""
            tools.append({"tool": fn.name, "group": TOOL_GROUPS.get(fn.name, "Other"), "description": comment,
                          "parameters": ", ".join(params) or "none", "full_name": fn.full_name,
                          "url": f"{links['function_base']}{fn.name}{links['org']}"})
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not list UC functions: %s", exc)
    order = {g: i for i, g in enumerate(GROUP_ORDER)}
    return sorted(tools, key=lambda t: (order.get(t["group"], 99), t["tool"]))


def chat(messages: list[dict], instructions: str | None = None) -> dict:
    """Query the deployed agent. Returns the answer text plus the tool-call steps from its output items."""
    w = _client()
    started = time.perf_counter()
    body = {"input": messages}
    if instructions:
        body["custom_inputs"] = {"instructions": instructions}   # augments the agent's system prompt for this call
    response = w.api_client.do("POST", f"/serving-endpoints/{ENDPOINT_NAME}/invocations", body=body)
    steps, answer, outputs = [], [], {}
    for item in response.get("output", []):
        kind = item.get("type")
        if kind == "function_call":
            steps.append({"call_id": item.get("call_id"), "tool": item.get("name"),
                          "arguments": item.get("arguments"), "output": None})
        elif kind == "function_call_output":
            outputs[item.get("call_id")] = item.get("output")
        elif kind == "message":
            for part in item.get("content", []):
                if part.get("type") in ("output_text", "text"):
                    answer.append(part.get("text", ""))
    for step in steps:
        step["output"] = outputs.get(step["call_id"])
    return {"answer": "\n".join(answer).strip(), "steps": steps,
            "seconds": round(time.perf_counter() - started, 1), "endpoint": ENDPOINT_NAME}



