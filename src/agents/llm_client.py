"""LLM client adapters (OpenAI-compatible chat completions with tool calling)."""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any


class LlmError(Exception):
    pass


class LlmClient(ABC):
    model: str = "unknown"

    @abstractmethod
    def chat(self, messages: list[dict], tools: list[dict] | None = None, max_tokens: int = 2000,
             temperature: float | None = None) -> dict:
        """Return the assistant message: {"content": str|None, "tool_calls": [{"id", "name", "arguments": dict}]}."""


def parse_message(response: dict) -> dict:
    try:
        message = response["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LlmError(f"Malformed LLM response: {str(response)[:200]}") from exc
    content = message.get("content")
    if isinstance(content, list):  # some endpoints return content blocks
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    calls = []
    for call in message.get("tool_calls") or []:
        fn = call.get("function", {})
        args = fn.get("arguments") or "{}"
        try:
            parsed = json.loads(args) if isinstance(args, str) else dict(args)
        except json.JSONDecodeError:
            parsed = {"__invalid_json__": args}
        calls.append({"id": call.get("id") or fn.get("name"), "name": fn.get("name"), "arguments": parsed})
    return {"content": content, "tool_calls": calls}


class DatabricksFoundationModelClient(LlmClient):
    """Calls a Databricks model serving endpoint (pay-per-token Foundation Model API) via databricks-sdk."""

    def __init__(self, endpoint: str, timeout_seconds: int = 90, workspace_client: Any = None):
        self.model = endpoint
        self.timeout_seconds = timeout_seconds
        self._client = workspace_client

    @property
    def client(self):
        if self._client is None:
            try:
                from databricks.sdk import WorkspaceClient
            except ImportError as exc:  # pragma: no cover - depends on environment
                raise LlmError("databricks-sdk is not installed") from exc
            self._client = WorkspaceClient()
        return self._client

    def chat(self, messages: list[dict], tools: list[dict] | None = None, max_tokens: int = 2000,
             temperature: float | None = None) -> dict:
        body: dict[str, Any] = {"messages": messages, "max_tokens": max_tokens}
        if temperature is not None:
            body["temperature"] = temperature
        if tools:
            body["tools"] = tools
        try:
            response = self.client.api_client.do("POST", f"/serving-endpoints/{self.model}/invocations", body=body)
        except LlmError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise LlmError(f"{type(exc).__name__}: {str(exc)[:300]}") from exc
        return parse_message(response)


class ScriptedLlmClient(LlmClient):
    """Test double that replays scripted assistant messages."""

    model = "scripted"

    def __init__(self, script: list[dict]):
        self.script = list(script)
        self.requests: list[dict] = []

    def chat(self, messages, tools=None, max_tokens=2000, temperature=None) -> dict:
        self.requests.append({"messages": [dict(m) for m in messages], "tools": tools})
        if not self.script:
            raise LlmError("Script exhausted")
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return {"content": step.get("content"), "tool_calls": step.get("tool_calls", [])}
