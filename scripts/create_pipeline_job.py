"""Create or update the serverless Databricks Workflows that run from the workspace Git folder.

Jobs:
  lsi-pipeline           one-time setup: generate -> bronze -> silver -> gold -> UC tools -> evaluation
  lsi-servicing-monitor  recurring backend: bronze -> silver -> refresh & verify -> gold -> agent triage + AI Functions

Usage:
  python scripts/create_pipeline_job.py --repo-path /Workspace/Users/<you>/AIWorkflowAutomationDemo \
      [--job all|pipeline|monitor] [--catalog main] [--schema loan_servicing_intelligence] [--run] \
      [--schedule-unpaused]

No cluster specification is given, so notebook tasks run on serverless Jobs compute (scales to zero between runs).
The monitor schedule (every 30 minutes) is created PAUSED unless --schedule-unpaused is passed.
"""
from __future__ import annotations

import argparse

from databricks.sdk import WorkspaceClient
from databricks.sdk.service import jobs

PIPELINE = ("lsi-pipeline",
            "Loan Servicing Intelligence (synthetic) setup: generate -> bronze -> silver -> gold -> UC tools -> "
            "evaluation. Serverless.",
            [("generate", "01_generate_demo_data", []),
             ("bronze", "02_ingest_bronze", ["generate"]),
             ("silver", "03_build_silver", ["bronze"]),
             ("gold", "04_build_gold", ["silver"]),
             ("tools", "05_register_agent_tools", ["gold"]),
             ("evaluate", "06_run_evaluation", ["gold"])])
MONITOR = ("lsi-servicing-monitor",
           "Loan Servicing Intelligence (synthetic) recurring backend: ingest servicing exports, rebuild Silver, "
           "refresh and verify submitted actions, re-evaluate rules and scores (Gold), agent triage of new "
           "high-priority loans (proposals await human approval), and AI Functions insights. Serverless.",
           [("ingest", "02_ingest_bronze", []),
            ("silver", "03_build_silver", ["ingest"]),
            ("refresh_verify", "09_refresh_and_verify", ["silver"]),
            ("rules_and_scores", "04_build_gold", ["refresh_verify"]),
            ("agent_triage", "08_agent_triage", ["rules_and_scores"]),
            ("ai_insights", "10_ai_insights", ["rules_and_scores"])])


def job_settings(spec, repo_path: str, catalog: str, schema: str, schedule_unpaused: bool) -> dict:
    name, description, task_specs = spec
    params = {"catalog": catalog, "schema": schema, "processing_date": "2026-10-12"}
    tasks = [jobs.Task(
        task_key=key,
        description=f"{notebook} (synthetic demonstration)",
        notebook_task=jobs.NotebookTask(notebook_path=f"{repo_path}/notebooks/{notebook}",
                                        source=jobs.Source.WORKSPACE, base_parameters=params),
        depends_on=[jobs.TaskDependency(task_key=d) for d in depends] or None,
        timeout_seconds=3600,
    ) for key, notebook, depends in task_specs]
    settings = {"name": name, "description": description, "tasks": tasks, "max_concurrent_runs": 1,
                "tags": {"project": "loan-servicing-intelligence", "synthetic_data": "true"}}
    if spec is MONITOR:
        settings["schedule"] = jobs.CronSchedule(
            quartz_cron_expression="0 0/30 * * * ?", timezone_id="UTC",
            pause_status=jobs.PauseStatus.UNPAUSED if schedule_unpaused else jobs.PauseStatus.PAUSED)
    return settings


def upsert(w: WorkspaceClient, settings: dict) -> int:
    existing = list(w.jobs.list(name=settings["name"]))
    if existing:
        job_id = existing[0].job_id
        w.jobs.reset(job_id=job_id, new_settings=jobs.JobSettings(**settings))
        print(f"Updated job {settings['name']} ({job_id})")
    else:
        job_id = w.jobs.create(**settings).job_id
        print(f"Created job {settings['name']} ({job_id})")
    return job_id


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-path", required=True)
    parser.add_argument("--job", choices=["all", "pipeline", "monitor"], default="all")
    parser.add_argument("--catalog", default="main")
    parser.add_argument("--schema", default="loan_servicing_intelligence")
    parser.add_argument("--run", action="store_true", help="Run the selected job(s) and wait")
    parser.add_argument("--schedule-unpaused", action="store_true")
    args = parser.parse_args()

    w = WorkspaceClient()
    specs = {"pipeline": [PIPELINE], "monitor": [MONITOR], "all": [PIPELINE, MONITOR]}[args.job]
    for spec in specs:
        job_id = upsert(w, job_settings(spec, args.repo_path.rstrip("/"), args.catalog, args.schema,
                                        args.schedule_unpaused))
        if args.run:
            print(f"Running {spec[0]}... (serverless start-up can take a minute)")
            run = w.jobs.run_now_and_wait(job_id=job_id)
            print(f"Run {run.run_id}: {run.state.result_state} {run.state.state_message or ''}")
            for task in run.tasks or []:
                print(f"  {task.task_key:18s} {task.state.result_state}")


if __name__ == "__main__":
    main()
