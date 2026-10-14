"""Loan Servicing Agent - written by notebook 06_build_and_deploy_agent (edit it there).

A tool-calling agent: Claude on Databricks + the lsi_* Unity Catalog functions from notebook 05.
"""
import json
import os
import uuid

import mlflow
from databricks.sdk import WorkspaceClient
from mlflow.entities import SpanType
from mlflow.models import ModelConfig
from mlflow.pyfunc import ResponsesAgent
from mlflow.types.responses import ResponsesAgentRequest, ResponsesAgentResponse

config = ModelConfig(development_config={
    "catalog": "main", "schema": "loan_servicing_intelligence", "warehouse_id": "",
    "llm_endpoint": "databricks-claude-sonnet-5-5", "endpoint_name": "loan-servicing-agent",
})

SYSTEM_PROMPT = """You are the Loan Servicing Agent. You help loan-servicing specialists understand which loans need
attention and why. All data is synthetic.
- Get every fact from your tools; never invent dates, amounts, statuses, or scores.
- Report scores and escalation exactly as the tools return them.
- Recommend only an action listed by lsi_get_allowed_actions, and name the tools you relied on.
- You are read-only: you recommend, a person decides. No legal or financial advice. Be concise."""

w = WorkspaceClient()


def load_tools() -> dict:
    """Every lsi_* function in the schema becomes a tool. Its comments become the tool description."""
    tools = {}
    for fn in w.functions.list(catalog_name=config.get("catalog"), schema_name=config.get("schema")):
        if fn.name.startswith("lsi_"):
            info = w.functions.get(fn.full_name)
            params = info.input_params.parameters if info.input_params else []
            tools[fn.name] = {
                "full_name": fn.full_name,
                "params": [p.name for p in params],
                "spec": {"type": "function", "function": {
                    "name": fn.name,
                    "description": info.comment,
                    "parameters": {"type": "object", "required": [p.name for p in params], "properties": {
                        p.name: {"type": "integer" if p.type_name.value == "INT" else "string",
                                 "description": p.comment or ""} for p in params}}}},
            }
    return tools


TOOLS = load_tools()


@mlflow.trace(span_type=SpanType.TOOL)
def run_tool(name: str, arguments: dict) -> str:
    """Run a Unity Catalog function on the SQL warehouse and return its rows as JSON."""
    tool = TOOLS.get(name)
    if tool is None:  # the model asked for a tool that does not exist: tell it, so it can recover
        return json.dumps({"error": f"Unknown tool {name}. Available tools: {', '.join(sorted(TOOLS))}"})
    args = ", ".join(repr(arguments.get(p)) for p in tool["params"])
    try:
        result = w.statement_execution.execute_statement(
            statement=f"SELECT * FROM {tool['full_name']}({args})", warehouse_id=config.get("warehouse_id"),
            wait_timeout="50s")
    except Exception as exc:  # report the problem to the model instead of failing the request
        return json.dumps({"error": str(exc)[:300]})
    if result.status.state.value != "SUCCEEDED":
        return json.dumps({"error": result.status.error.message if result.status.error else "query failed"})
    columns = [c.name for c in result.manifest.schema.columns]
    rows = [dict(zip(columns, row)) for row in (result.result.data_array or [])]
    return json.dumps({"rows": rows[:50]})


@mlflow.trace(span_type=SpanType.CHAT_MODEL)
def call_llm(messages: list) -> dict:
    body = {"messages": messages, "tools": [t["spec"] for t in TOOLS.values()], "max_tokens": 2500}
    response = w.api_client.do("POST", f"/serving-endpoints/{config.get('llm_endpoint')}/invocations", body=body)
    return response["choices"][0]["message"]


def text_of(message: dict) -> str:
    """The model's text; some models return a list of content blocks (reasoning + text) instead of a string."""
    content = message.get("content") or ""
    if isinstance(content, list):
        content = "".join(block.get("text", "") for block in content if block.get("type") == "text")
    return content


class LoanServicingAgent(ResponsesAgent):
    def predict(self, request: ResponsesAgentRequest) -> ResponsesAgentResponse:
        if os.environ.get("IS_IN_DB_MODEL_SERVING_ENV"):   # label the trace so the endpoint's Traces page shows it
            mlflow.update_current_trace(metadata={"mlflow.databricks.modelServingEndpointName": config.get("endpoint_name")})
        system = SYSTEM_PROMPT
        instructions = (request.custom_inputs or {}).get("instructions")   # optional: augment the agent per call
        if instructions:
            system += "\n\nAdditional instructions for this request:\n" + instructions
        messages = [{"role": "system", "content": system}] + self.prep_msgs_for_cc_llm(request.input)
        output = []
        for _ in range(10):                                    # the agent loop
            message = call_llm(messages)
            calls = message.get("tool_calls") or []
            if not calls:                                      # no more tools needed: answer
                output.append(self.create_text_output_item(text=text_of(message), id=str(uuid.uuid4())))
                break
            messages.append({"role": "assistant", "content": text_of(message), "tool_calls": calls})
            for call in calls:                                 # run each tool the model chose
                name, arguments = call["function"]["name"], call["function"].get("arguments") or "{}"
                result = run_tool(name, json.loads(arguments))
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
                output.append(self.create_function_call_item(id=str(uuid.uuid4()), call_id=call["id"],
                                                             name=name, arguments=arguments))
                output.append(self.create_function_call_output_item(call_id=call["id"], output=result))
        return ResponsesAgentResponse(output=output)


AGENT = LoanServicingAgent()
mlflow.models.set_model(AGENT)
