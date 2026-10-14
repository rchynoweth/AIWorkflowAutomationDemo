"""Create/update and deploy the Loan Servicing Intelligence Databricks App from the workspace Git folder.

Usage:
  python scripts/deploy_app.py --repo-path /Workspace/Users/<you>/AIWorkflowAutomationDemo --warehouse-id <id> \
      [--catalog main] [--schema loan_servicing_intelligence] \
      [--keep-running]

Steps: create the app with the SQL warehouse (CAN_USE) and agent endpoint (CAN_QUERY) as resources; grant the app
service principal least-privilege Unity Catalog access to one schema; deploy; stop the app unless
--keep-running (Databricks Apps do not auto-suspend).
"""
from __future__ import annotations

import argparse
import time

from databricks.sdk import WorkspaceClient
from databricks.sdk.service import apps, workspace
from databricks.sdk.service.sql import StatementState

APP_NAME = "loan-servicing-intelligence"


def run_sql(w: WorkspaceClient, warehouse_id: str, statement: str) -> None:
    resp = w.statement_execution.execute_statement(statement=statement, warehouse_id=warehouse_id, wait_timeout="50s")
    while resp.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(1)
        resp = w.statement_execution.get_statement(resp.statement_id)
    if resp.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(f"{statement}: {resp.status.error.message if resp.status.error else resp.status}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-path", required=True)
    parser.add_argument("--warehouse-id", required=True)
    parser.add_argument("--catalog", default="main")
    parser.add_argument("--schema", default="loan_servicing_intelligence")
    parser.add_argument("--keep-running", action="store_true")
    args = parser.parse_args()
    w = WorkspaceClient()

    resources = [
        apps.AppResource(name="sql-warehouse", description="Serverless SQL warehouse (auto-stop)",
                         sql_warehouse=apps.AppResourceSqlWarehouse(
                             id=args.warehouse_id,
                             permission=apps.AppResourceSqlWarehouseSqlWarehousePermission.CAN_USE)),
        apps.AppResource(name="agent-endpoint", description="Loan Servicing Agent (Model Serving)",
                         serving_endpoint=apps.AppResourceServingEndpoint(
                             name="loan-servicing-agent",
                             permission=apps.AppResourceServingEndpointServingEndpointPermission.CAN_QUERY)),
    ]
    for job in w.jobs.list(name="lsi-pipeline"):   # lets How It Works show the last run
        resources.append(apps.AppResource(name="pipeline-job", description="Databricks Workflow lsi-pipeline",
                                          job=apps.AppResourceJob(id=str(job.job_id),
                                                                  permission=apps.AppResourceJobJobPermission.CAN_VIEW)))
    description = ("Loan Servicing Intelligence - agent-powered portfolio monitoring and loan-servicing workflow "
                   "automation (synthetic demonstration data).")
    try:
        app = w.apps.get(APP_NAME)
        print(f"App exists: {app.url}")
        deadline = time.time() + 1200
        while app.compute_status and app.compute_status.state.value in ("STARTING", "STOPPING") \
                and time.time() < deadline:
            time.sleep(10)  # updates are only accepted while compute is ACTIVE or STOPPED
            app = w.apps.get(APP_NAME)
        app = w.apps.update(name=APP_NAME, app=apps.App(name=APP_NAME, description=description, resources=resources))
    except Exception as exc:  # noqa: BLE001
        if "does not exist" not in str(exc).lower() and "not found" not in str(exc).lower():
            raise
        print("Creating app (compute start-up takes a few minutes)...")
        app = w.apps.create_and_wait(apps.App(name=APP_NAME, description=description, resources=resources))
        print(f"Created: {app.url}")

    sp = app.service_principal_client_id
    print(f"Granting Unity Catalog privileges to app service principal {sp}")
    run_sql(w, args.warehouse_id, f"GRANT USE CATALOG ON CATALOG `{args.catalog}` TO `{sp}`")
    run_sql(w, args.warehouse_id,
            f"GRANT USE SCHEMA, SELECT, MODIFY, CREATE TABLE, EXECUTE, READ VOLUME, WRITE VOLUME ON SCHEMA `{args.catalog}`.`{args.schema}` "
            f"TO `{sp}`")

    try:  # lets the app link to its Git folder in the resource inventory
        repo = w.workspace.get_status(args.repo_path)
        w.repos.update_permissions(str(repo.object_id), access_control_list=[
            workspace.RepoAccessControlRequest(service_principal_name=sp,
                                               permission_level=workspace.RepoPermissionLevel.CAN_READ)])
    except Exception as exc:  # noqa: BLE001 - optional
        print(f"Skipping Git folder permission: {str(exc)[:120]}")

    state = w.apps.get(APP_NAME).compute_status.state.value
    if state not in ("ACTIVE", "STARTING"):
        print(f"Starting app compute (was {state})...")
        w.apps.start_and_wait(APP_NAME)
    print(f"Deploying from {args.repo_path} ...")
    deployment = w.apps.deploy_and_wait(APP_NAME, apps.AppDeployment(source_code_path=args.repo_path))
    print(f"Deployment {deployment.deployment_id}: {deployment.status.state.value} {deployment.status.message or ''}")
    app = w.apps.get(APP_NAME)
    print(f"App URL: {app.url}")
    if not args.keep_running:
        print("Stopping app to avoid idle cost (start with: databricks apps start loan-servicing-intelligence)")
        w.apps.stop_and_wait(APP_NAME)


if __name__ == "__main__":
    main()
