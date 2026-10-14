"""Log, register (Unity Catalog), and deploy the Loan Servicing Agent to Model Serving (Mosaic AI Agent Framework).

Called by notebooks/11_deploy_agent.py on serverless compute. The agent code lives in
agent_endpoint/loan_servicing_agent.py (MLflow models-from-code) and its tools are the Unity Catalog functions
registered by notebooks/05_register_agent_tools.py.
"""
from __future__ import annotations

AGENT_MODEL = "loan_servicing_agent"
ENDPOINT_NAME = "loan-servicing-agent"
TABLES = ["gold_loan_servicing_state", "gold_loan_milestone_state", "gold_priority_queue", "gold_portfolio_health",
          "gold_pending_actions", "gold_action_verification", "gold_ai_loan_insights", "gold_reviewer_decisions",
          "silver_loan_events", "silver_milestone_rules", "silver_reviewer_decisions", "ops_actions",
          "ops_recommendations", "ops_reviewer_decisions", "v_lsi_specialist_workload", "v_lsi_verification_failures"]


def deploy_agent(agent_path: str, catalog: str, schema: str, warehouse_id: str,
                 llm_endpoint: str = "databricks-claude-sonnet-5-5", endpoint_name: str = ENDPOINT_NAME,
                 scale_to_zero: bool = True) -> dict:
    import mlflow
    from databricks import agents
    from databricks.sdk import WorkspaceClient
    from mlflow.models.resources import (DatabricksFunction, DatabricksServingEndpoint, DatabricksSQLWarehouse,
                                         DatabricksTable)

    w = WorkspaceClient()
    mlflow.set_registry_uri("databricks-uc")
    user = w.current_user.me().user_name
    mlflow.set_experiment(f"/Users/{user}/loan-servicing-agent")

    functions = [f.full_name for f in w.functions.list(catalog_name=catalog, schema_name=schema)
                 if f.name.startswith("lsi_")]
    resources = ([DatabricksServingEndpoint(endpoint_name=llm_endpoint), DatabricksSQLWarehouse(warehouse_id=warehouse_id)]
                 + [DatabricksFunction(function_name=f) for f in functions]
                 + [DatabricksTable(table_name=f"{catalog}.{schema}.{t}") for t in TABLES])
    config = {"catalog": catalog, "schema": schema, "warehouse_id": warehouse_id, "llm_endpoint": llm_endpoint,
              "max_iterations": 10, "tool_prefix": "lsi_"}
    model_name = f"{catalog}.{schema}.{AGENT_MODEL}"
    with mlflow.start_run(run_name="loan-servicing-agent"):
        info = mlflow.pyfunc.log_model(
            name="agent",
            python_model=agent_path,
            model_config=config,
            resources=resources,
            pip_requirements=["mlflow>=3.1", "databricks-sdk>=0.50"],
            input_example={"input": [{"role": "user", "content": "Which loans need attention first today?"}]},
            registered_model_name=model_name,
        )
    version = info.registered_model_version
    deployment = agents.deploy(model_name, version, scale_to_zero=scale_to_zero, endpoint_name=endpoint_name,
                               description="Loan Servicing Agent (synthetic demonstration): Claude + Unity Catalog "
                                           "tools, read-only, human approval in the app.",
                               tags={"project": "loan-servicing-intelligence", "synthetic_data": "true"})
    return {"model": model_name, "version": version, "endpoint": deployment.endpoint_name,
            "review_app_url": getattr(deployment, "review_app_url", None), "tools": len(functions)}
