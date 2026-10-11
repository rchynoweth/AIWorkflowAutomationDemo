"""Status of the Databricks backend workflows (Jobs API) and AI Functions outputs, for the app."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

log = logging.getLogger(__name__)

MONITOR_JOB_NAME = "lsi-servicing-monitor"
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
    """Recent runs of the servicing monitor and setup pipeline. Never raises."""
    try:
        w = _client()
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": f"Databricks SDK unavailable: {exc}"}
    out = {"available": True, "workflows": []}
    for env_key, name in (("LSI_MONITOR_JOB_ID", MONITOR_JOB_NAME), ("LSI_PIPELINE_JOB_ID", PIPELINE_JOB_NAME)):
        try:
            job_id = _job_id(w, env_key, name)
            if job_id is None:
                out["workflows"].append({"name": name, "found": False})
                continue
            job = w.jobs.get(job_id)
            schedule = job.settings.schedule
            runs = []
            for run in w.jobs.list_runs(job_id=job_id, limit=limit, expand_tasks=True):
                state = run.state
                runs.append({
                    "run_id": run.run_id,
                    "state": (state.result_state.value if state and state.result_state else
                              state.life_cycle_state.value if state and state.life_cycle_state else "UNKNOWN"),
                    "trigger": run.trigger.value if run.trigger else None,
                    "start_time": _ts(run.start_time), "end_time": _ts(run.end_time),
                    "duration_s": round((run.run_duration or 0) / 1000) if run.run_duration else None,
                    "run_page_url": run.run_page_url,
                    "tasks": [{"task": t.task_key, "state": (t.state.result_state.value if t.state and
                                                             t.state.result_state else
                                                             t.state.life_cycle_state.value if t.state else None)}
                              for t in (run.tasks or [])],
                })
            out["workflows"].append({
                "name": name, "found": True, "job_id": job_id,
                "schedule": schedule.quartz_cron_expression if schedule else None,
                "schedule_paused": (schedule.pause_status.value == "PAUSED") if schedule and schedule.pause_status else None,
                "tasks": [t.task_key for t in job.settings.tasks or []],
                "runs": runs,
            })
        except Exception as exc:  # noqa: BLE001 - status is informational
            log.warning("workflow status failed for %s: %s", name, exc)
            out["workflows"].append({"name": name, "found": False, "error": str(exc)[:300]})
    return out


def run_monitor_now() -> dict:
    w = _client()
    job_id = _job_id(w, "LSI_MONITOR_JOB_ID", MONITOR_JOB_NAME)
    if job_id is None:
        raise RuntimeError("Servicing monitor workflow not found")
    run = w.jobs.run_now(job_id=job_id)
    return {"job_id": job_id, "run_id": run.run_id}


def latest_success_end(status: dict, name: str = MONITOR_JOB_NAME) -> str | None:
    for wf in status.get("workflows", []):
        if wf.get("name") == name:
            for run in wf.get("runs", []):
                if run["state"] == "SUCCESS" and run.get("end_time"):
                    return run["end_time"]
    return None


def ai_insights(repository, limit: int = 8) -> dict:
    """Rows produced by the AI Functions task (ai_query), when the Databricks backend is in use."""
    if getattr(repository, "backend", "local") != "databricks" or not hasattr(repository, "execute"):
        return {"available": False, "reason": "AI Functions outputs are read from Databricks tables."}
    try:
        loans = repository.execute(
            f"SELECT loan_id, priority, primary_condition, attention_score, ai_summary, "
            f"CAST(generated_at AS STRING) AS generated_at FROM {repository.fq('gold_ai_loan_insights')} "
            f"ORDER BY attention_score DESC, loan_id LIMIT {int(limit)}")
        briefing = repository.execute(
            f"SELECT briefing, CAST(generated_at AS STRING) AS generated_at "
            f"FROM {repository.fq('gold_ai_portfolio_briefing')} LIMIT 1")
        return {"available": True, "loans": loans, "briefing": briefing[0] if briefing else None}
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": f"Not yet generated ({str(exc)[:160]})"}


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
    for env_key, name, note in (("LSI_MONITOR_JOB_ID", MONITOR_JOB_NAME, "Recurring backend workflow (serverless)"),
                                ("LSI_PIPELINE_JOB_ID", PIPELINE_JOB_NAME, "One-time setup pipeline (serverless)")):
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
                        ("ops_recommendations", "Agent proposals awaiting human review"),
                        ("ops_actions", "Approved actions and outbound events"),
                        ("sor_servicing_events", "Simulated System of Record writes")):
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
