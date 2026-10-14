"""Create or update the `lsi-pipeline` Databricks Workflow (serverless) that runs from the workspace Git folder.

    generate -> bronze -> silver -> gold -> ai_functions -> agent_reviews

The agent's tools (notebook 05) and the agent itself (notebook 06) are set up once, outside this schedule.

Usage:
  python scripts/create_pipeline_job.py --repo-path /Workspace/Users/<you>/AIWorkflowAutomationDemo [--run]
      [--catalog main] [--schema loan_servicing_intelligence] [--schedule-unpaused]

No cluster is specified, so every task runs on serverless compute. The 30-minute schedule is created PAUSED
unless --schedule-unpaused is passed.
"""
from __future__ import annotations

import argparse

from databricks.sdk import WorkspaceClient
from databricks.sdk.service import jobs

JOB_NAME = "lsi-pipeline"
TASKS = [  # task key, notebook, depends on
    ("generate", "01_generate_demo_data", []),
    ("bronze", "02_ingest_bronze", ["generate"]),
    ("silver", "03_build_silver", ["bronze"]),
    ("gold", "04_build_gold", ["silver"]),
    ("ai_functions", "07_ai_functions", ["gold"]),
    ("agent_reviews", "08_agent_reviews", ["ai_functions"]),
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-path", required=True)
    parser.add_argument("--catalog", default="main")
    parser.add_argument("--schema", default="loan_servicing_intelligence")
    parser.add_argument("--run", action="store_true", help="Run the job after creating it and wait")
    parser.add_argument("--schedule-unpaused", action="store_true")
    args = parser.parse_args()

    params = {"catalog": args.catalog, "schema": args.schema}
    tasks = [jobs.Task(task_key=key,
                       notebook_task=jobs.NotebookTask(notebook_path=f"{args.repo_path.rstrip('/')}/notebooks/{nb}",
                                                       source=jobs.Source.WORKSPACE, base_parameters=params),
                       depends_on=[jobs.TaskDependency(task_key=d) for d in deps] or None,
                       timeout_seconds=3600)
             for key, nb, deps in TASKS]
    settings = {
        "name": JOB_NAME,
        "description": "Loan Servicing Intelligence (synthetic data): servicing exports -> Bronze -> Silver -> "
                       "Gold rules -> AI Functions -> agent reviews. Serverless.",
        "tasks": tasks,
        "max_concurrent_runs": 1,
        "schedule": jobs.CronSchedule(quartz_cron_expression="0 0/30 * * * ?", timezone_id="UTC",
                                      pause_status=jobs.PauseStatus.UNPAUSED if args.schedule_unpaused
                                      else jobs.PauseStatus.PAUSED),
        "tags": {"project": "loan-servicing-intelligence", "synthetic_data": "true"},
    }
    w = WorkspaceClient()
    existing = list(w.jobs.list(name=JOB_NAME))
    if existing:
        job_id = existing[0].job_id
        w.jobs.reset(job_id=job_id, new_settings=jobs.JobSettings(**settings))
        print(f"Updated job {JOB_NAME} ({job_id})")
    else:
        job_id = w.jobs.create(**settings).job_id
        print(f"Created job {JOB_NAME} ({job_id})")
    if args.run:
        print("Running... (serverless start-up takes about a minute)")
        run = w.jobs.run_now_and_wait(job_id=job_id)
        print(f"Run {run.run_id}: {run.state.result_state} {run.state.state_message or ''}")
        for task in run.tasks or []:
            print(f"  {task.task_key:14s} {task.state.result_state}")


if __name__ == "__main__":
    main()
