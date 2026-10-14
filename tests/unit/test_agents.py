"""Deterministic agent, LLM agent guardrails (scripted LLM), fallback, briefing number guard."""
from src.agent import deterministic_briefing, DeterministicLoanServicingAgent, LlmError, number_guard, RunContext, ScriptedLlmClient, ToolCallingLoanServicingAgent
from src.medallion import briefing_facts

LOAN = "LSI-SYN-000005"


def run(tool_ctx, settings, sink=None):
    return RunContext(run_id="RUN-TEST", tool_ctx=tool_ctx, settings=settings, on_activity=sink)


def call(name, args, cid="c1"):
    return {"id": cid, "name": name, "arguments": args}


def test_deterministic_recommendation_schema(tool_ctx, settings):
    activity = []
    out = DeterministicLoanServicingAgent(settings).assess_loan(LOAN, run(tool_ctx, settings, activity.append))
    rec = out["recommendation"]
    assert rec["recommended_action"] == "CONTACT_ATTORNEY"
    assert rec["requires_human_approval"] is True and rec["status"] == "PENDING_REVIEW"
    assert rec["attention_score"] == 54 and rec["priority"] == "HIGH"
    assert rec["validation"]["valid"] and rec["proposed_event"]["status"] == "DRAFT_UNCOMMITTED"
    assert len(rec["evidence"]) >= 3 and rec["tool_calls"]
    for key in ("recommendation_id", "secondary_conditions", "score_drivers", "recommended_event_type",
                "recommended_followup_date", "suggested_note", "rationale", "confidence", "uncertainty",
                "missing_information", "created_at", "agent_version", "rule_version", "scoring_version"):
        assert key in rec
    assert any(a.get("step") == "awaiting_approval" for a in activity)


def test_llm_disallowed_action_is_overridden(tool_ctx, settings):
    llm = ScriptedLlmClient([
        {"tool_calls": [call("get_allowed_actions", {"loan_id": LOAN})]},
        {"tool_calls": [call("submit_recommendation", {"recommended_action": "CREATE_NEXT_MILESTONE",
                                                       "rationale": "x", "confidence": "HIGH"}, "c2")]},
    ])
    out = ToolCallingLoanServicingAgent(settings, llm).assess_loan(LOAN, run(tool_ctx, settings))
    rec = out["recommendation"]
    assert rec["recommended_action"] == "CONTACT_ATTORNEY"
    assert rec["confidence"] == "LOW"
    assert "not allowed" in rec["uncertainty"]


def test_llm_cannot_change_score_and_guardrail_tools_run(tool_ctx, settings):
    llm = ScriptedLlmClient([
        {"tool_calls": [call("submit_recommendation", {"recommended_action": "CREATE_FOLLOWUP", "rationale": "ok",
                                                       "confidence": "HIGH", "attention_score": 99})]},
    ])
    rec = ToolCallingLoanServicingAgent(settings, llm).assess_loan(LOAN, run(tool_ctx, settings))["recommendation"]
    assert rec["attention_score"] == 54 and rec["recommended_action"] == "CREATE_FOLLOWUP"
    origins = {c["tool_name"]: c["origin"] for c in rec["tool_calls"]}
    assert origins["calculate_loan_attention_score"] == "guardrail"


def test_llm_failure_falls_back_in_auto_mode(tool_ctx, settings):
    llm = ScriptedLlmClient([LlmError("endpoint down")])
    out = ToolCallingLoanServicingAgent(settings, llm, allow_fallback=True).assess_loan(LOAN, run(tool_ctx, settings))
    assert out["agent_mode"] == "deterministic-fallback"
    assert "LLM unavailable" in out["recommendation"]["uncertainty"]


def test_llm_failure_without_fallback_proposes_nothing(tool_ctx, settings):
    llm = ScriptedLlmClient([LlmError("endpoint down")])
    out = ToolCallingLoanServicingAgent(settings, llm, allow_fallback=False).assess_loan(LOAN, run(tool_ctx, settings))
    assert out["recommendation"] is None and "specialist review" in out["answer"]


def test_ask_declines_regulated_questions(tool_ctx, settings):
    out = DeterministicLoanServicingAgent(settings).answer_question("Can you give legal advice on this?", LOAN,
                                                                   run(tool_ctx, settings))
    assert "can't provide legal" in out["answer"]


def test_ask_why_prioritized(tool_ctx, settings):
    out = DeterministicLoanServicingAgent(settings).answer_question("Why is this loan prioritized?", LOAN,
                                                                   run(tool_ctx, settings))
    assert "54" in out["answer"] and out["tool_calls"]


def test_number_guard(evaluation):
    facts = briefing_facts(evaluation)
    ok, _ = number_guard(deterministic_briefing(facts), facts)
    assert ok
    ok, offending = number_guard("- 99999 loans are overdue", facts)
    assert not ok and offending == ["99999"]


def test_llm_briefing_rejected_when_inventing_numbers(tool_ctx, settings, evaluation):
    llm = ScriptedLlmClient([{"content": "- 123456 loans need attention"}])
    out = ToolCallingLoanServicingAgent(settings, llm).portfolio_briefing(briefing_facts(evaluation),
                                                                          run(tool_ctx, settings))
    assert out["source"] == "deterministic" and "Number guard" in out["rejected_reason"]
