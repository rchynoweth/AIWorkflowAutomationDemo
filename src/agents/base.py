"""Framework-neutral Loan Servicing Agent interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable

from src.tools.executor import ToolExecutor
from src.tools.servicing_tools import ToolContext


@dataclass
class RunContext:
    run_id: str
    tool_ctx: ToolContext
    settings: Any
    user_id: str = "SPEC-01"
    on_activity: Callable[[dict], None] | None = None
    steps: list[dict] = field(default_factory=list)

    def executor(self, loan_id: str | None = None) -> ToolExecutor:
        return ToolExecutor(self.tool_ctx, self.run_id, loan_id, self.on_activity)

    def step(self, name: str, loan_id: str | None, detail: str = "", success: bool = True) -> None:
        record = {"run_id": self.run_id, "loan_id": loan_id, "step": name, "tool_name": None,
                  "input_summary": "", "output_summary": detail[:400], "duration_ms": 0.0, "success": success,
                  "error": None if success else detail[:400]}
        self.steps.append(record)
        if self.on_activity:
            self.on_activity(record)


class LoanServicingAgent(ABC):
    agent_version: str
    mode: str

    @abstractmethod
    def assess_loan(self, loan_id: str, run: RunContext) -> dict:
        """Return {"recommendation": dict, "answer": str, "tool_calls": list, "agent_mode": str}."""

    @abstractmethod
    def answer_question(self, question: str, loan_id: str | None, run: RunContext) -> dict:
        """Return {"answer": str, "tool_calls": list, "agent_mode": str}."""

    @abstractmethod
    def portfolio_briefing(self, facts: list[dict], run: RunContext) -> dict:
        """Return {"text": str, "source": "llm"|"deterministic", "rejected_reason": str|None}."""
