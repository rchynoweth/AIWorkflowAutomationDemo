# Databricks notebook source
# MAGIC %md
# MAGIC # 06 · Build and deploy the Loan Servicing Agent
# MAGIC
# MAGIC **This notebook is where the agent is defined, tested, registered, and deployed.** Four steps:
# MAGIC
# MAGIC 1. **Write the agent** - one short Python file: Claude on Databricks plus the Unity Catalog tools from
# MAGIC    notebook 05. Every `lsi_*` function in the schema automatically becomes a tool.
# MAGIC 2. **Try it** right here in the notebook.
# MAGIC 3. **Register it** in Unity Catalog with MLflow.
# MAGIC 4. **Deploy it** to a Model Serving endpoint with the Mosaic AI Agent Framework (one call).

# COMMAND ----------

# MAGIC %pip install -q "mlflow>=3.1" databricks-agents "databricks-sdk>=0.50"

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

dbutils.widgets.text("catalog", "main")
dbutils.widgets.text("schema", "loan_servicing_intelligence")
dbutils.widgets.text("warehouse_id", "", "SQL warehouse ID")
catalog, schema = dbutils.widgets.get("catalog"), dbutils.widgets.get("schema")

AGENT_CONFIG = {
    "catalog": catalog,
    "schema": schema,
    "warehouse_id": dbutils.widgets.get("warehouse_id"),   # where the tool functions run
    "llm_endpoint": "databricks-claude-sonnet-5-5",        # Foundation Model API, pay-per-token
}
MODEL_NAME = f"{catalog}.{schema}.loan_servicing_agent"
ENDPOINT_NAME = "loan-servicing-agent"

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Write the agent
# MAGIC The whole agent: load the tools from Unity Catalog, call the model, run whichever tools it asks for,
# MAGIC repeat until it answers. `mlflow.trace` records every model call and tool call.

# COMMAND ----------

# MAGIC %%writefile agent.py
# MAGIC """Loan Servicing Agent - written by notebook 06_build_and_deploy_agent (edit it there).
# MAGIC
# MAGIC A tool-calling agent: Claude on Databricks + the lsi_* Unity Catalog functions from notebook 05.
# MAGIC """
# MAGIC import json
# MAGIC import uuid
# MAGIC
# MAGIC import mlflow
# MAGIC from databricks.sdk import WorkspaceClient
# MAGIC from mlflow.entities import SpanType
# MAGIC from mlflow.models import ModelConfig
# MAGIC from mlflow.pyfunc import ResponsesAgent
# MAGIC from mlflow.types.responses import ResponsesAgentRequest, ResponsesAgentResponse
# MAGIC
# MAGIC config = ModelConfig(development_config={
# MAGIC     "catalog": "main", "schema": "loan_servicing_intelligence", "warehouse_id": "",
# MAGIC     "llm_endpoint": "databricks-claude-sonnet-5-5",
# MAGIC })
# MAGIC
# MAGIC SYSTEM_PROMPT = """You are the Loan Servicing Agent. You help loan-servicing specialists understand which loans need
# MAGIC attention and why. All data is synthetic.
# MAGIC - Get every fact from your tools; never invent dates, amounts, statuses, or scores.
# MAGIC - Report scores and escalation exactly as the tools return them.
# MAGIC - Recommend only an action listed by lsi_get_allowed_actions, and name the tools you relied on.
# MAGIC - You are read-only: you recommend, a person decides. No legal or financial advice. Be concise."""
# MAGIC
# MAGIC w = WorkspaceClient()
# MAGIC
# MAGIC
# MAGIC def load_tools() -> dict:
# MAGIC     """Every lsi_* function in the schema becomes a tool. Its comments become the tool description."""
# MAGIC     tools = {}
# MAGIC     for fn in w.functions.list(catalog_name=config.get("catalog"), schema_name=config.get("schema")):
# MAGIC         if fn.name.startswith("lsi_"):
# MAGIC             info = w.functions.get(fn.full_name)
# MAGIC             params = info.input_params.parameters if info.input_params else []
# MAGIC             tools[fn.name] = {
# MAGIC                 "full_name": fn.full_name,
# MAGIC                 "params": [p.name for p in params],
# MAGIC                 "spec": {"type": "function", "function": {
# MAGIC                     "name": fn.name,
# MAGIC                     "description": info.comment,
# MAGIC                     "parameters": {"type": "object", "required": [p.name for p in params], "properties": {
# MAGIC                         p.name: {"type": "integer" if p.type_name.value == "INT" else "string",
# MAGIC                                  "description": p.comment or ""} for p in params}}}},
# MAGIC             }
# MAGIC     return tools
# MAGIC
# MAGIC
# MAGIC TOOLS = load_tools()
# MAGIC
# MAGIC
# MAGIC @mlflow.trace(span_type=SpanType.TOOL)
# MAGIC def run_tool(name: str, arguments: dict) -> str:
# MAGIC     """Run a Unity Catalog function on the SQL warehouse and return its rows as JSON."""
# MAGIC     tool = TOOLS[name]
# MAGIC     args = ", ".join(repr(arguments.get(p)) for p in tool["params"])
# MAGIC     result = w.statement_execution.execute_statement(
# MAGIC         statement=f"SELECT * FROM {tool['full_name']}({args})", warehouse_id=config.get("warehouse_id"),
# MAGIC         wait_timeout="50s")
# MAGIC     if result.status.state.value != "SUCCEEDED":
# MAGIC         return json.dumps({"error": result.status.error.message if result.status.error else "query failed"})
# MAGIC     columns = [c.name for c in result.manifest.schema.columns]
# MAGIC     rows = [dict(zip(columns, row)) for row in (result.result.data_array or [])]
# MAGIC     return json.dumps({"rows": rows[:50]})
# MAGIC
# MAGIC
# MAGIC @mlflow.trace(span_type=SpanType.CHAT_MODEL)
# MAGIC def call_llm(messages: list) -> dict:
# MAGIC     body = {"messages": messages, "tools": [t["spec"] for t in TOOLS.values()], "max_tokens": 2500}
# MAGIC     response = w.api_client.do("POST", f"/serving-endpoints/{config.get('llm_endpoint')}/invocations", body=body)
# MAGIC     return response["choices"][0]["message"]
# MAGIC
# MAGIC
# MAGIC class LoanServicingAgent(ResponsesAgent):
# MAGIC     def predict(self, request: ResponsesAgentRequest) -> ResponsesAgentResponse:
# MAGIC         messages = [{"role": "system", "content": SYSTEM_PROMPT}] + self.prep_msgs_for_cc_llm(request.input)
# MAGIC         output = []
# MAGIC         for _ in range(10):                                    # the agent loop
# MAGIC             message = call_llm(messages)
# MAGIC             calls = message.get("tool_calls") or []
# MAGIC             if not calls:                                      # no more tools needed: answer
# MAGIC                 output.append(self.create_text_output_item(text=message.get("content") or "", id=str(uuid.uuid4())))
# MAGIC                 break
# MAGIC             messages.append({"role": "assistant", "content": message.get("content") or "", "tool_calls": calls})
# MAGIC             for call in calls:                                 # run each tool the model chose
# MAGIC                 name, arguments = call["function"]["name"], call["function"].get("arguments") or "{}"
# MAGIC                 result = run_tool(name, json.loads(arguments))
# MAGIC                 messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
# MAGIC                 output.append(self.create_function_call_item(id=str(uuid.uuid4()), call_id=call["id"],
# MAGIC                                                              name=name, arguments=arguments))
# MAGIC                 output.append(self.create_function_call_output_item(call_id=call["id"], output=result))
# MAGIC         return ResponsesAgentResponse(output=output)
# MAGIC
# MAGIC
# MAGIC AGENT = LoanServicingAgent()
# MAGIC mlflow.models.set_model(AGENT)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Try it
# MAGIC Ask a question and watch which tools the agent chooses.

# COMMAND ----------

import agent
from mlflow.models import ModelConfig
from mlflow.types.responses import ResponsesAgentRequest

agent.config = ModelConfig(development_config=AGENT_CONFIG)
print(f"The agent has {len(agent.TOOLS)} tools: {', '.join(sorted(agent.TOOLS))}")

question = "Why is loan LSI-SYN-000005 a priority and what should happen next?"
response = agent.AGENT.predict(ResponsesAgentRequest(input=[{"role": "user", "content": question}]))
for item in response.output:
    if item.type == "function_call":
        print("Tool call:", item.name, item.arguments)
print()
print(response.output[-1].content[0]["text"])

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Register it in Unity Catalog
# MAGIC We declare the resources the agent uses (model endpoint, warehouse, tool functions, tables). Databricks
# MAGIC uses this list to give the deployed agent exactly those permissions and nothing more.

# COMMAND ----------

import mlflow
from mlflow.models.resources import (DatabricksFunction, DatabricksServingEndpoint, DatabricksSQLWarehouse,
                                     DatabricksTable)

TABLES = ["gold_loan_servicing_state", "gold_loan_milestone_state", "gold_priority_queue", "gold_portfolio_health",
          "gold_pending_actions", "gold_action_verification", "gold_ai_loan_insights", "gold_reviewer_decisions",
          "silver_loan_events", "silver_milestone_rules", "silver_reviewer_decisions", "ops_actions",
          "ops_recommendations", "ops_reviewer_decisions", "v_lsi_specialist_workload", "v_lsi_verification_failures"]

resources = ([DatabricksServingEndpoint(endpoint_name=AGENT_CONFIG["llm_endpoint"]),
              DatabricksSQLWarehouse(warehouse_id=AGENT_CONFIG["warehouse_id"])]
             + [DatabricksFunction(function_name=tool["full_name"]) for tool in agent.TOOLS.values()]
             + [DatabricksTable(table_name=f"{catalog}.{schema}.{table}") for table in TABLES])

mlflow.set_registry_uri("databricks-uc")
with mlflow.start_run(run_name="loan-servicing-agent"):
    logged = mlflow.pyfunc.log_model(
        name="agent",
        python_model="agent.py",
        model_config=AGENT_CONFIG,
        resources=resources,
        pip_requirements=["mlflow>=3.1", "databricks-sdk>=0.50"],
        input_example={"input": [{"role": "user", "content": "Which loans need attention first today?"}]},
        registered_model_name=MODEL_NAME,
    )
print(f"Registered {MODEL_NAME} version {logged.registered_model_version}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Deploy it
# MAGIC One call creates (or updates) the serving endpoint, with scale-to-zero, MLflow tracing, and a review app.
# MAGIC The first deployment takes about 15 minutes.

# COMMAND ----------

from databricks import agents

deployment = agents.deploy(MODEL_NAME, logged.registered_model_version, endpoint_name=ENDPOINT_NAME,
                           scale_to_zero=True)
print("Endpoint:", deployment.endpoint_name)
print("Review app:", deployment.review_app_url)
