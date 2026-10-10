"""Create or update the serverless pipeline job that runs notebooks 01-06 from the workspace Git folder.

Usage:
  python scripts/create_pipeline_job.py --repo-path /Workspace/Users/<you>/AIWorkflowAutomationDemo \
      [--catalog main] [--schema loan_servicing_intelligence] [--run]

No cluster specification is given, so notebook tasks run on serverless Jobs compute (scales to zero).
"""
from __future__ import annotations

import argparse

from databricks.sdk import WorkspaceClient
from databricks.sdk.service import jobs

JOB_NAME = "lsi-pipeline"
TASKS = [
    ("generate", "01_generate_demo_data", None),
    ("bronze", "02_ingest_bronze", "generate"),
    ("silver", "03_build_silver", "bronze"),
    ("gold", "04_build_gold", "silver"),
    ("tools", "05_register_agent_tools", "gold"),
    ("evaluate", "06_run_evaluation", "gold"),
]


def job_settings(repo_path: str, catalog: str, schema: str) -> dict:
    params = {"catalog": catalog, "schema": schema, "processing_date": "2026-10-12"}
    tasks = []
    for key, notebook, depends in TASKS:
        tasks.append(jobs.Task(
            task_key=key,
            description=f"Loan Servicing Intelligence (synthetic): {notebook}",
            notebook_task=jobs.NotebookTask(notebook_path=f"{repo_path}/notebooks/{notebook}",
                                            source=jobs.Source.WORKSPACE, base_parameters=params),
            depends_on=[jobs.TaskDependency(task_key=depends)] if depends else None,
            timeout_seconds=3600,
        ))
    return {
        "name": JOB_NAME,
        "description": "Loan Servicing Intelligence synthetic pipeline: generate -> bronze -> silver -> gold -> "
                       "UC tools -> evaluation. Serverless compute.",
        "tasks": tasks,
        "max_concurrent_runs": 1,
        "tags": {"project": "loan-servicing-intelligence", "synthetic_data": "true"},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-path", required=True)
    parser.add_argument("--catalog", default="main")
    parser.add_argument("--schema", default="loan_servicing_intelligence")
    parser.add_argument("--run", action="store_true", help="Run the job after creating it and wait")
    args = parser.parse_args()

    w = WorkspaceClient()
    settings = job_settings(args.repo_path.rstrip("/"), args.catalog, args.schema)
    existing = [j for j in w.jobs.list(name=JOB_NAME)]
    if existing:
        job_id = existing[0].job_id
        w.jobs.reset(job_id=job_id, new_settings=jobs.JobSettings(**settings))
        print(f"Updated job {JOB_NAME} ({job_id})")
    else:
        job_id = w.jobs.create(**settings).job_id
        print(f"Created job {JOB_NAME} ({job_id})")
    if args.run:
        print("Running... (serverless start-up can take a minute)")
        run = w.jobs.run_now_and_wait(job_id=job_id)
        print(f"Run {run.run_id}: {run.state.result_state} {run.state.state_message or ''}")
        for task in run.tasks or []:
            print(f"  {task.task_key:10s} {task.state.result_state}")


if __name__ == "__main__":
    main()
