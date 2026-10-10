"""LLM tool-calling Loan Servicing Agent (OpenAI-compatible chat with tools)."""
from __future__ import annotations

import json

from src.agents.base import LoanServicingAgent, RunContext
from src.agents.briefing import number_guard
from src.agents.deterministic_agent import DECLINE_TERMS, DeterministicLoanServicingAgent
from src.agents.llm_client import LlmClient, LlmError
from src.agents.prompts import ASK_TASK, ASSESS_TASK, BRIEFING_TASK, SUBMIT_RECOMMENDATION_TOOL, SYSTEM_INSTRUCTION
from src.agents.recommendation_builder import build_recommendation
from src.tools.executor import summarize
from src.tools.registry import LOAN_TOOLS, PORTFOLIO_TOOLS, REGISTRY


class ToolCallingLoanServicingAgent(LoanServicingAgent):
    mode = "llm"

    def __init__(self, settings, llm: LlmClient, fallback: DeterministicLoanServicingAgent | None = None,
                 allow_fallback: bool = True):
        self.settings = settings
        self.llm = llm
        self.fallback = fallback or DeterministicLoanServicingAgent(settings)
        self.allow_fallback = allow_fallback
        self.agent_version = f"{settings.agent_version}-llm"
        cfg = settings.agent
        self.max_iterations = int(cfg.get("max_tool_iterations", 12))
        self.temperature = cfg.get("temperature")
        self.temperature = float(self.temperature) if self.temperature is not None else None
        self.max_tokens = int(cfg.get("max_tokens", 2500))

    # ---- loop ---------------------------------------------------------------------------
    def _loop(self, messages: list[dict], tools: list[dict], executor, loan_id: str | None,
              stop_tool: str | None = None) -> tuple[dict | None, str | None]:
        """Run the tool loop. Returns (stop_tool_arguments, final_text)."""
        for _ in range(self.max_iterations):
            reply = self.llm.chat(messages, tools=tools, max_tokens=self.max_tokens, temperature=self.temperature)
            calls = reply.get("tool_calls") or []
            if not calls:
                return None, reply.get("content")
            messages.append({"role": "assistant", "content": reply.get("content") or "",
                             "tool_calls": [{"id": c["id"], "type": "function",
                                             "function": {"name": c["name"],
                                                          "arguments": json.dumps(c["arguments"])}} for c in calls]})
            stop_args = None
            for call in calls:
                if stop_tool and call["name"] == stop_tool:
                    stop_args = call["arguments"]
                    content = json.dumps({"status": "received; awaiting human review"})
                else:
                    args = dict(call["arguments"])
                    spec = REGISTRY.get(call["name"])
                    if loan_id and spec and "loan_id" in spec.input_model.model_fields:
                        args.setdefault("loan_id", loan_id)
                    result = executor.call(call["name"], args, origin="agent")
                    content = json.dumps({"success": result["success"], "data": result["data"],
                                          "error": result["error"]}, default=str)
                    if len(content) > 12000:
                        content = content[:12000] + "...(truncated)"
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": content})
            if stop_args is not None:
                return stop_args, None
        raise LlmError(f"Tool loop exceeded {self.max_iterations} iterations")

    # ---- assessment ---------------------------------------------------------------------
    def assess_loan(self, loan_id: str, run: RunContext) -> dict:
        loan_id = loan_id.strip().upper()
        if loan_id not in run.tool_ctx.evaluation.facts:
            return {"recommendation": None, "answer": "Assessment failed: LOAN_NOT_FOUND", "tool_calls": [],
                    "agent_mode": self.mode, "error": "LOAN_NOT_FOUND"}
        executor = run.executor(loan_id)
        run.step("candidate_detected", loan_id, f"LLM assessment requested ({self.llm.model})")
        tools = [REGISTRY[n].openai_tool() for n in LOAN_TOOLS] + [SUBMIT_RECOMMENDATION_TOOL]
        messages = [{"role": "system", "content": SYSTEM_INSTRUCTION},
                    {"role": "user", "content": ASSESS_TASK.format(
                        loan_id=loan_id, processing_date=run.tool_ctx.processing_date.isoformat())}]
        try:
            choice, text = self._loop(messages, tools, executor, loan_id, stop_tool="submit_recommendation")
            if choice is None:
                choice = {"rationale": text or "", "confidence": "LOW",
                          "uncertainty": "Agent did not submit a structured recommendation."}
        except LlmError as exc:
            run.step("llm_failure", loan_id, str(exc), success=False)
            if not self.allow_fallback:
                return {"recommendation": None, "answer": "Agent analysis failed — route to specialist review.",
                        "tool_calls": executor.records, "agent_mode": self.mode, "error": str(exc)}
            result = self.fallback.assess_loan(loan_id, run, fallback_reason=str(exc)[:160])
            result["agent_mode"] = "deterministic-fallback"
            return result
        state = run.tool_ctx.result(loan_id)
        rec = build_recommendation(executor, loan_id, state, self.settings, self.mode, run.run_id, choice=choice)
        run.step("recommendation_generated", loan_id, f"{rec['recommended_action']} ({rec['confidence']})")
        run.step("awaiting_approval", loan_id, rec["status"])
        return {"recommendation": rec, "answer": rec["rationale"], "tool_calls": executor.records,
                "agent_mode": self.mode}

    # ---- governed questions -------------------------------------------------------------
    def answer_question(self, question: str, loan_id: str | None, run: RunContext) -> dict:
        if any(term in (question or "").lower() for term in DECLINE_TERMS):
            return self.fallback.answer_question(question, loan_id, run)
        loan_id = loan_id.strip().upper() if loan_id else None
        executor = run.executor(loan_id)
        names = (LOAN_TOOLS if loan_id else []) + PORTFOLIO_TOOLS
        tools = [REGISTRY[n].openai_tool() for n in names]
        loan_clause = f"The question is about loan {loan_id}. " if loan_id else ""
        messages = [{"role": "system", "content": SYSTEM_INSTRUCTION},
                    {"role": "user", "content": ASK_TASK.format(question=question, loan_clause=loan_clause,
                                                                processing_date=run.tool_ctx.processing_date)}]
        try:
            _, text = self._loop(messages, tools, executor, loan_id)
            if not text:
                raise LlmError("Empty answer")
            return {"answer": text.strip(), "tool_calls": executor.records, "agent_mode": self.mode}
        except LlmError as exc:
            run.step("llm_failure", loan_id, str(exc), success=False)
            if not self.allow_fallback:
                raise
            result = self.fallback.answer_question(question, loan_id, run)
            result["agent_mode"] = "deterministic-fallback"
            return result

    # ---- briefing -----------------------------------------------------------------------
    def portfolio_briefing(self, facts: list[dict], run: RunContext) -> dict:
        compact = [{"group": f["fact_group"], "name": f["fact_name"], "value": f["fact_value"]} for f in facts]
        messages = [{"role": "system", "content": SYSTEM_INSTRUCTION},
                    {"role": "user", "content": BRIEFING_TASK.format(facts_json=json.dumps(compact))}]
        try:
            reply = self.llm.chat(messages, tools=None, max_tokens=1500, temperature=self.temperature)
            text = (reply.get("content") or "").strip()
            ok, offending = number_guard(text, facts)
            run.step("briefing_generated", None, summarize(text, 200), success=ok)
            if text and ok:
                return {"text": text, "source": "llm", "rejected_reason": None}
            reason = f"Number guard rejected values not in facts: {', '.join(offending[:5])}" if text else "Empty draft"
        except LlmError as exc:
            reason = f"LLM unavailable: {str(exc)[:120]}"
        result = self.fallback.portfolio_briefing(facts, run)
        result["rejected_reason"] = reason
        return result
