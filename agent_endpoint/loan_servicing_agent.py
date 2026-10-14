"""Loan Servicing Agent - deployable Databricks agent (MLflow ResponsesAgent, models-from-code).

- Model: Claude via the Databricks Foundation Model API (tool calling).
- Tools: Unity Catalog SQL functions (`<catalog>.<schema>.lsi_*`). Tool names, descriptions, and parameter schemas
  are read from Unity Catalog at start-up, so the governed catalog is the single source of truth for the toolset.
- Execution: each tool call runs `SELECT * FROM <function>(...)` on a serverless SQL warehouse.
- Read-only: the agent investigates and recommends. Approval and scheduling happen in the Loan Servicing
  Intelligence app with a human in the loop.
- Tracing: every LLM call and tool call is an MLflow span, visible in the Playground and the review app.

SYNTHETIC DEMONSTRATION DATA ONLY.
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, Generator

import mlflow
from databricks.sdk import WorkspaceClient
from mlflow.entities import SpanType
from mlflow.models import ModelConfig
from mlflow.pyfunc import ResponsesAgent
from mlflow.types.responses import ResponsesAgentRequest, ResponsesAgentResponse, ResponsesAgentStreamEvent

DEFAULT_CONFIG = {
    "catalog": "main",
    "schema": "loan_servicing_intelligence",
    "warehouse_id": "",
    "llm_endpoint": "databricks-claude-sonnet-5-5",
    "max_iterations": 10,
    "tool_prefix": "lsi_",
}

SYSTEM_PROMPT = """You are the Loan Servicing Agent for Loan Servicing Intelligence, a SYNTHETIC demonstration.
You support authorized loan-servicing specialists by investigating loans and the portfolio. You are not the
decision-maker.

How you work:
- Get every fact from your Unity Catalog tools. Never invent loans, dates, amounts, statuses, metrics, or scores.
- For a loan question, typically check: loan context, current milestone, follow-up status, open follow-ups,
  pending actions, prior rejections, escalation, attention score, and allowed actions.
- Recommend only an action listed by lsi_get_allowed_actions. Report the score and escalation exactly as returned;
  never recalculate them.
- Distinguish tool facts from your interpretation and name the tools you relied on.
- State uncertainty and missing information.
- You are read-only. Approval, edits, and scheduling happen in the Loan Servicing Intelligence app, where a
  specialist must confirm every action. Never claim an action was executed.
- No legal or financial advice and no borrower-eligibility, foreclosure-authority, or other regulated decisions.
- Be concise: short paragraphs or bullets. Refer to borrowers only by their synthetic display names."""

_SQL_TYPES = {"STRING": "string", "INT": "integer", "BIGINT": "integer", "DOUBLE": "number", "BOOLEAN": "boolean"}


def _literal(value: Any, type_name: str) -> str:
    if value is None:
        return "NULL"
    if _SQL_TYPES.get(type_name) in ("integer", "number"):
        return str(float(value)) if _SQL_TYPES[type_name] == "number" else str(int(value))
    if _SQL_TYPES.get(type_name) == "boolean":
        return "TRUE" if str(value).lower() in ("true", "1") else "FALSE"
    text = str(value).replace("\\", "\\\\").replace("'", "\\'")
    return f"'{text}'"


class UCFunctionTool:
    def __init__(self, full_name: str, description: str, params: list[dict]):
        self.full_name = full_name
        self.name = full_name.split(".")[-1]
        self.description = description
        self.params = params  # [{name, type, comment}]

    def spec(self) -> dict:
        props = {p["name"]: {"type": _SQL_TYPES.get(p["type"], "string"), "description": p.get("comment") or ""}
                 for p in self.params}
        return {"type": "function", "function": {"name": self.name, "description": self.description,
                                                 "parameters": {"type": "object", "properties": props,
                                                                "required": [p["name"] for p in self.params]}}}


class LoanServicingAgent(ResponsesAgent):
    def __init__(self, config: dict | None = None):
        cfg = dict(DEFAULT_CONFIG)
        cfg.update(config or {})
        self.config = cfg
        self._w: WorkspaceClient | None = None
        self._tools: dict[str, UCFunctionTool] | None = None

    # ---- clients and tools --------------------------------------------------------------
    @property
    def w(self) -> WorkspaceClient:
        if self._w is None:
            self._w = WorkspaceClient()
        return self._w

    @property
    def tools(self) -> dict[str, UCFunctionTool]:
        if self._tools is None:
            cat, sch, prefix = self.config["catalog"], self.config["schema"], self.config["tool_prefix"]
            tools = {}
            for fn in self.w.functions.list(catalog_name=cat, schema_name=sch):
                if not fn.name.startswith(prefix):
                    continue
                info = self.w.functions.get(fn.full_name)
                params = [{"name": p.name, "type": (p.type_name.value if p.type_name else "STRING"),
                           "comment": p.comment} for p in ((info.input_params.parameters if info.input_params else None)
                                                           or [])]
                tools[fn.name] = UCFunctionTool(fn.full_name, (info.comment or fn.name), params)
            self._tools = tools
        return self._tools

    # ---- execution ----------------------------------------------------------------------
    @mlflow.trace(span_type=SpanType.TOOL)
    def execute_tool(self, name: str, arguments: dict) -> str:
        tool = self.tools.get(name)
        if tool is None:
            return json.dumps({"error": f"Unknown tool {name}"})
        args = ", ".join(_literal(arguments.get(p["name"]), p["type"]) for p in tool.params)
        statement = f"SELECT * FROM {tool.full_name}({args}) LIMIT 50"
        api = self.w.statement_execution
        resp = api.execute_statement(statement=statement, warehouse_id=self.config["warehouse_id"],
                                     wait_timeout="50s")
        deadline = time.time() + 120
        while resp.status and resp.status.state.value in ("PENDING", "RUNNING") and time.time() < deadline:
            time.sleep(1)
            resp = api.get_statement(resp.statement_id)
        if not resp.status or resp.status.state.value != "SUCCEEDED":
            message = resp.status.error.message if resp.status and resp.status.error else "unknown error"
            return json.dumps({"error": message[:500]})
        columns = [c.name for c in resp.manifest.schema.columns] if resp.manifest and resp.manifest.schema else []
        rows = [dict(zip(columns, r)) for r in ((resp.result.data_array if resp.result else None) or [])]
        return json.dumps({"rows": rows, "row_count": len(rows)}, default=str)[:12000]

    @mlflow.trace(span_type=SpanType.CHAT_MODEL)
    def call_llm(self, messages: list[dict]) -> dict:
        body = {"messages": messages, "tools": [t.spec() for t in self.tools.values()], "max_tokens": 2500}
        response = self.w.api_client.do("POST", f"/serving-endpoints/{self.config['llm_endpoint']}/invocations",
                                        body=body)
        return response["choices"][0]["message"]

    # ---- ResponsesAgent interface -------------------------------------------------------------
    def predict(self, request: ResponsesAgentRequest) -> ResponsesAgentResponse:
        outputs = [event.item for event in self.predict_stream(request)
                   if event.type == "response.output_item.done"]
        return ResponsesAgentResponse(output=outputs, custom_outputs=request.custom_inputs)

    def predict_stream(self, request: ResponsesAgentRequest) -> Generator[ResponsesAgentStreamEvent, None, None]:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + self.prep_msgs_for_cc_llm(request.input)
        for _ in range(int(self.config["max_iterations"])):
            message = self.call_llm(messages)
            calls = message.get("tool_calls") or []
            content = message.get("content")
            if isinstance(content, list):
                content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
            if not calls:
                yield ResponsesAgentStreamEvent(type="response.output_item.done", item=self.create_text_output_item(
                    text=content or "", id=str(uuid.uuid4())))
                return
            messages.append({"role": "assistant", "content": content or "", "tool_calls": calls})
            for call in calls:
                fn = call["function"]
                yield ResponsesAgentStreamEvent(type="response.output_item.done", item=self.create_function_call_item(
                    id=str(uuid.uuid4()), call_id=call["id"], name=fn["name"], arguments=fn.get("arguments") or "{}"))
                try:
                    arguments = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    arguments = {}
                output = self.execute_tool(fn["name"], arguments)
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": output})
                yield ResponsesAgentStreamEvent(type="response.output_item.done",
                                                item=self.create_function_call_output_item(call_id=call["id"],
                                                                                           output=output))
        yield ResponsesAgentStreamEvent(type="response.output_item.done", item=self.create_text_output_item(
            text="I reached my tool-call limit before finishing. Please narrow the question.", id=str(uuid.uuid4())))


_model_config = ModelConfig(development_config=DEFAULT_CONFIG).to_dict()
AGENT = LoanServicingAgent(_model_config)
mlflow.models.set_model(AGENT)
