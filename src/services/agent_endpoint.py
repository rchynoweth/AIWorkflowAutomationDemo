"""Client for the deployed Loan Servicing Agent (Model Serving) and its Unity Catalog toolset."""
from __future__ import annotations

import logging
import os
import time

log = logging.getLogger(__name__)

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


def _client():
    from databricks.sdk import WorkspaceClient

    return WorkspaceClient()


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


def chat(messages: list[dict]) -> dict:
    """Query the deployed agent. Returns the answer text plus the tool-call steps from its output items."""
    w = _client()
    started = time.perf_counter()
    response = w.api_client.do("POST", f"/serving-endpoints/{ENDPOINT_NAME}/invocations", body={"input": messages})
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
