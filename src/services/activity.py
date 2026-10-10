"""Activity logging and optional MLflow tracing. Never records prompts, credentials, or chain-of-thought."""
from __future__ import annotations

import contextlib
import logging
import uuid
from datetime import datetime, timezone

log = logging.getLogger("lsi.activity")


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="milliseconds")


def new_run_id(prefix: str = "RUN") -> str:
    return f"{prefix}-{datetime.now(timezone.utc):%Y%m%d}-{uuid.uuid4().hex[:6]}"


class ActivityBuffer:
    """Collects activity records for a run; the service persists them in one batch."""

    def __init__(self, actor: str = "agent"):
        self.actor = actor
        self.records: list[dict] = []

    def __call__(self, record: dict) -> None:
        rec = {
            "activity_id": f"ACTV-{uuid.uuid4().hex[:12]}",
            "run_id": record.get("run_id"),
            "loan_id": record.get("loan_id"),
            "step": record.get("step") or "tool_call",
            "tool_name": record.get("tool_name"),
            "input_summary": record.get("input_summary", ""),
            "output_summary": record.get("output_summary", ""),
            "duration_ms": record.get("duration_ms", 0.0),
            "success": record.get("success", True),
            "error": record.get("error"),
            "actor": record.get("actor") or self.actor,
            "created_at": record.get("called_at") or utcnow(),
        }
        self.records.append(rec)
        log.info("activity run=%s loan=%s step=%s tool=%s ok=%s ms=%s", rec["run_id"], rec["loan_id"], rec["step"],
                 rec["tool_name"], rec["success"], rec["duration_ms"])


@contextlib.contextmanager
def trace_span(name: str, attributes: dict | None = None):
    """MLflow span when mlflow is importable and tracing is configured; otherwise a no-op."""
    try:
        import mlflow  # type: ignore
    except Exception:  # noqa: BLE001
        yield None
        return
    try:
        span_cm = mlflow.start_span(name=name)
    except Exception:  # noqa: BLE001
        yield None
        return
    with span_cm as span:
        try:
            if attributes:
                span.set_attributes({k: str(v) for k, v in attributes.items()})
        except Exception:  # noqa: BLE001
            pass
        yield span
