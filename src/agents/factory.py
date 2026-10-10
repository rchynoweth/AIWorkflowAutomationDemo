"""Agent selection by mode (auto | llm | deterministic)."""
from __future__ import annotations

from src.agents.base import LoanServicingAgent
from src.agents.deterministic_agent import DeterministicLoanServicingAgent
from src.agents.llm_client import DatabricksFoundationModelClient, LlmClient
from src.agents.tool_calling_agent import ToolCallingLoanServicingAgent


def create_agent(settings, mode: str | None = None, llm: LlmClient | None = None) -> LoanServicingAgent:
    mode = (mode or settings.agent.get("mode") or "auto").lower()
    deterministic = DeterministicLoanServicingAgent(settings)
    if mode == "deterministic":
        return deterministic
    client = llm or DatabricksFoundationModelClient(settings.agent["model_endpoint"],
                                                    int(settings.agent.get("request_timeout_seconds", 90)))
    return ToolCallingLoanServicingAgent(settings, client, deterministic, allow_fallback=(mode == "auto"))
