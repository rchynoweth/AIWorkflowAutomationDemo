"""Tool executor: input validation, timing, structured result, and activity logging."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Callable

from pydantic import ValidationError

from src.tools.registry import REGISTRY
from src.tools.servicing_tools import ToolContext, ToolError


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="milliseconds")


def summarize(value, limit: int = 400) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str, separators=(",", ":"))
    return text if len(text) <= limit else text[: limit - 3] + "..."


class ToolExecutor:
    """Runs registered tools against a ToolContext and records every call."""

    def __init__(self, ctx: ToolContext, run_id: str, loan_id: str | None = None,
                 on_record: Callable[[dict], None] | None = None):
        self.ctx = ctx
        self.run_id = run_id
        self.loan_id = loan_id
        self.records: list[dict] = []
        self.results: dict[str, dict] = {}
        self.on_record = on_record

    def call(self, name: str, arguments: dict | None = None, origin: str = "plan") -> dict:
        arguments = dict(arguments or {})
        started = time.perf_counter()
        called_at = utcnow()
        spec = REGISTRY.get(name)
        data, error = None, None
        try:
            if spec is None:
                raise ToolError(f"UNKNOWN_TOOL:{name}")
            params = spec.input_model(**arguments)
            data = spec.fn(self.ctx, **params.model_dump())
        except ValidationError as exc:
            error = "INVALID_INPUT: " + "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        except ToolError as exc:
            error = str(exc)
        except Exception as exc:  # noqa: BLE001 - tool failures never crash the agent
            error = f"TOOL_ERROR: {type(exc).__name__}: {exc}"
        duration = round((time.perf_counter() - started) * 1000, 2)
        result = {"tool_name": name, "success": error is None, "data": data, "error": error,
                  "duration_ms": duration, "called_at": called_at, "input": arguments}
        record = {
            "tool_name": name, "success": error is None, "duration_ms": duration,
            "input_summary": summarize(arguments, 200), "output_summary": summarize(data if error is None else error),
            "error": error, "called_at": called_at, "origin": origin,
        }
        self.records.append(record)
        if error is None:
            self.results[name] = data
        if self.on_record:
            self.on_record({"run_id": self.run_id, "loan_id": self.loan_id or arguments.get("loan_id"), **record})
        return result
