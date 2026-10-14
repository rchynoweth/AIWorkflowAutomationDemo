"""The Loan Servicing Agent: prompts, LLM client, deterministic and tool-calling agents, and the
recommendation guardrails."""
from __future__ import annotations

import json
import re
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from src.tools import LOAN_TOOLS, PORTFOLIO_TOOLS, REGISTRY, summarize, ToolContext, ToolExecutor


# ====================================================================================================
# System instructions for the Loan Servicing Agent (synthetic demonstration)
# ====================================================================================================

SYSTEM_INSTRUCTION = """You are the Loan Servicing Agent inside Loan Servicing Intelligence, a synthetic demonstration
application. You support authorized loan-servicing specialists by investigating loans and preparing proposals.
You are not the decision-maker.

Rules you must follow:
1. Obtain every fact from tools. Never invent loans, dates, amounts, statuses, events, metrics, or scores.
2. Distinguish tool facts from your interpretation. Cite the tools you relied on.
3. Do not provide legal or financial advice, legal conclusions, or borrower-eligibility, foreclosure-authority,
   compliance, loss-mitigation, or other regulated decisions. Refer such questions to the appropriate human role.
4. Recommend only an action returned by get_allowed_actions for the loan.
5. Never calculate or change the attention score, priority, escalation state, conditions, or dates. Report them
   as returned by tools.
6. Before recommending, check for existing equivalent events, pending actions, and prior rejections.
7. State uncertainty and missing information explicitly.
8. Every action is a proposal that requires explicit human approval. Never claim an action was executed or
   submitted, and never attempt to modify the System of Record.
9. Keep notes and outreach drafts factual, neutral, brief, and free of speculation about the borrower.
10. All data is synthetic; refer to borrowers by their synthetic display names only.
"""

ASSESS_TASK = """Assess loan {loan_id} as of processing date {processing_date}.
Investigate with tools (at minimum: loan context, current milestone, follow-up status, existing events,
pending actions, prior rejections, escalation, attention score, allowed actions). Then call submit_recommendation
exactly once with: recommended_action (one of the allowed actions), rationale (2-4 sentences citing tool facts),
suggested_note (internal servicing note, <= 300 characters), suggested_outreach (short neutral message to the
assigned party if a contact action is recommended, else empty), evidence_refs (tool names you relied on),
confidence (HIGH, MEDIUM, or LOW), uncertainty (one sentence), missing_information (list of strings)."""

ASK_TASK = """A servicing specialist asks: "{question}"
{loan_clause}Processing date: {processing_date}. Use tools to obtain facts, then answer in at most 6 sentences.
Cite the tools or rule IDs you relied on. If the question asks for legal, financial, or eligibility advice,
decline briefly and name the appropriate human role."""

BRIEFING_TASK = """Write "Today's Portfolio Briefing" for servicing managers: 4-6 bullet points starting with "- ",
each at most 30 words, no heading, no numbered lists.
Use ONLY these deterministic facts (JSON). Do not introduce any number that is not present in the facts.
Do not compute new percentages or totals. Mention attention volume, top condition groups, overdue patterns,
missing follow-ups, exceptions, failed actions, pending approvals, and where to focus.
FACTS:
{facts_json}"""

SUBMIT_RECOMMENDATION_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_recommendation",
        "description": "Submit your final recommendation for human review. Does not execute anything.",
        "parameters": {
            "type": "object",
            "properties": {
                "recommended_action": {"type": "string"},
                "rationale": {"type": "string"},
                "suggested_note": {"type": "string"},
                "suggested_outreach": {"type": "string"},
                "evidence_refs": {"type": "array", "items": {"type": "string"}},
                "confidence": {"type": "string", "enum": ["HIGH", "MEDIUM", "LOW"]},
                "uncertainty": {"type": "string"},
                "missing_information": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["recommended_action", "rationale", "confidence"],
        },
    },
}


# ====================================================================================================
# LLM client adapters (OpenAI-compatible chat completions with tool calling)
# ====================================================================================================

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


# ====================================================================================================
# Framework-neutral Loan Servicing Agent interface
# ====================================================================================================

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


# ====================================================================================================
# Portfolio briefing: deterministic template and the number guard for LLM drafts (ADR-012)
# ====================================================================================================

NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


def facts_map(facts: list[dict]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for f in facts:
        out.setdefault(f["fact_group"], {})[f["fact_name"]] = f["fact_value"]
    return out


def allowed_numbers(facts: list[dict]) -> set[str]:
    allowed: set[str] = set()
    for f in facts:
        for text in (str(f["fact_value"]), str(f["fact_name"])):
            for n in NUMBER.findall(text):
                allowed.add(n.replace(",", ""))
                allowed.add(n.lstrip("0") or "0")
    return allowed


def number_guard(text: str, facts: list[dict]) -> tuple[bool, list[str]]:
    """Return (ok, offending_numbers). Every number in ``text`` must appear in the facts."""
    allowed = allowed_numbers(facts)
    offending = []
    for n in NUMBER.findall(text):
        norm = n.replace(",", "")
        if norm not in allowed and (norm.lstrip("0") or "0") not in allowed:
            offending.append(n)
    return not offending, offending


def deterministic_briefing(facts: list[dict]) -> str:
    m = facts_map(facts)
    k = m.get("kpi", {})
    lines = [
        f"- {k.get('need_attention', '0')} of {k.get('active_loans', '0')} active synthetic loans need attention "
        f"today; {k.get('critical', '0')} are CRITICAL priority.",
    ]
    top = m.get("top_attention_condition", {})
    if top:
        lines.append("- Largest attention groups: " + ", ".join(f"{c} ({n})" for c, n in top.items()) + ".")
    ov = m.get("overdue", {})
    if k.get("overdue", "0") != "0":
        lines.append(f"- {k.get('overdue')} loans have overdue follow-ups"
                     + (f"; {ov.get('overdue_30_plus')} are 30+ days and {ov.get('overdue_60_plus')} are 60+ days "
                        f"overdue (max {ov.get('max_days_overdue')} days)." if ov else "."))
    lines.append(f"- {k.get('missing_followup', '0')} missing follow-ups, {k.get('data_exceptions', '0')} data "
                 f"exceptions, and {k.get('duplicate_risk', '0')} duplicate-risk loans need data review.")
    lines.append(f"- {k.get('verification_failures', '0')} approved actions failed verification; "
                 f"{k.get('pending_actions', '0')} are awaiting verification and "
                 f"{k.get('recommendations_awaiting_approval', '0')} recommendations await approval.")
    ms = m.get("top_attention_milestone", {})
    if ms:
        focus = ", ".join(ms.keys())
        lines.append(f"- Focus: start with CRITICAL loans, then overdue items in {focus}.")
    return "\n".join(lines)


# ====================================================================================================
# Assemble recommendations from tool facts plus (optional) model narrative, enforcing guardrails
# ====================================================================================================

MANDATORY_TOOLS = [
    "get_loan_context", "get_current_milestone", "check_milestone_completion", "check_followup_status",
    "check_pending_action", "check_previous_rejection", "get_assigned_party", "calculate_escalation_state",
    "calculate_loan_attention_score", "get_allowed_actions",
]
CONFIDENCE_ORDER = ["LOW", "MEDIUM", "HIGH"]
MEDIUM_CAP_CONDITIONS = {"DATA_EXCEPTION", "DUPLICATE_RISK", "VERIFICATION_FAILURE"}
CONTACT_ACTIONS = {"CONTACT_ATTORNEY", "CONTACT_SERVICING_VENDOR"}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def new_recommendation_id() -> str:
    return f"REC-{datetime.now(timezone.utc):%Y%m%d}-{uuid.uuid4().hex[:8].upper()}"


def ensure_mandatory(executor: ToolExecutor, loan_id: str) -> list[str]:
    failed = []
    for name in MANDATORY_TOOLS:
        if name not in executor.results:
            res = executor.call(name, {"loan_id": loan_id}, origin="guardrail")
            if not res["success"]:
                failed.append(f"{name}: {res['error']}")
    return failed


def _ev(source_type: str, identifier: str, description: str, value) -> dict:
    return {"source_type": source_type, "source_identifier": identifier, "description": description,
            "value": value, "observed_at": now_iso()}


def build_evidence(executor: ToolExecutor, state: dict) -> list[dict]:
    r = executor.results
    evidence = []
    for cond in state.get("raw_conditions", []):
        evidence.append(_ev("RULE", cond["rule_id"], f"Condition {cond['code']}", cond["detail"]))
    cm = r.get("get_current_milestone") or {}
    if cm.get("has_servicing_track"):
        evidence.append(_ev("EVENT", cm.get("event_id") or "", "Current milestone",
                            f"{cm.get('milestone_type')} ({cm.get('status')}) opened {cm.get('event_date')}"))
    fu = r.get("check_followup_status") or {}
    if fu.get("effective_followup_date"):
        evidence.append(_ev("TOOL", "check_followup_status", "Effective follow-up date",
                            f"{fu['effective_followup_date']} (days to follow-up {fu.get('days_to_followup')}, "
                            f"days overdue {fu.get('days_overdue')})"))
    sc = r.get("calculate_loan_attention_score") or {}
    if sc:
        evidence.append(_ev("TOOL", "calculate_loan_attention_score", "Attention score",
                            f"{sc.get('score')} ({sc.get('priority')})"))
    es = r.get("calculate_escalation_state") or {}
    if es:
        evidence.append(_ev("TOOL", "calculate_escalation_state", "Escalation state",
                            f"{es.get('escalation_state')} -> {es.get('required_role')}"))
    pa = r.get("check_pending_action") or {}
    if pa.get("has_pending"):
        evidence.append(_ev("ACTION", pa["pending_actions"][0]["action_id"], "Pending approved action",
                            pa["pending_actions"][0]["action_type"]))
    rj = r.get("check_previous_rejection") or {}
    if rj.get("rejected_actions_in_lookback"):
        evidence.append(_ev("DECISION", "check_previous_rejection", "Rejected inside lookback",
                            ", ".join(rj["rejected_actions_in_lookback"])))
    ap = r.get("get_assigned_party") or {}
    if ap and ap.get("required_party_type"):
        evidence.append(_ev("TOOL", "get_assigned_party", "Required party present",
                            f"{ap['required_party_type']}: {'yes' if ap.get('party_ok') else 'no'}"))
    if state.get("latest_verification_status"):
        evidence.append(_ev("ACTION", state.get("latest_action_id") or "", "Latest action verification",
                            state["latest_verification_status"]))
    return evidence


def deterministic_missing_information(state: dict, executor: ToolExecutor) -> list[str]:
    missing = []
    for cond in state.get("raw_conditions", []):
        rid = cond["rule_id"]
        if rid == "RULE-DATA-001":
            missing.append(f"Active milestone rule for {state.get('current_milestone')}")
        elif rid == "RULE-DATA-002":
            missing.append("Corrected milestone completion/event dates")
        elif rid == "RULE-DATA-003":
            missing.append("Active assigned party of the required type")
        elif rid == "RULE-DATA-004":
            missing.append("Active assigned servicing specialist")
        elif rid == "RULE-FOLLOWUP-002":
            missing.append("Follow-up date for the current milestone")
        elif rid == "RULE-VERIFICATION-001":
            missing.append("Confirmation from the servicing system that the approved event exists")
    return missing


def template_narrative(state: dict, action: str, draft: dict) -> dict:
    primary = state["primary_condition"]
    details = "; ".join(c["detail"] for c in state["raw_conditions"] if c["code"] == primary) or primary
    milestone = state.get("current_milestone") or "no active milestone"
    rationale = (f"Rule facts: {details}. Attention score {state['attention_score']} ({state['priority']}) driven by "
                 f"{state['top_drivers_text'] or 'no drivers'}. Escalation is {state['escalation_state']}. "
                 f"{action} is the first allowed action for {primary} under the synthetic action catalog.")
    if action == "NO_ACTION":
        note = f"Synthetic note: no new action proposed; {primary.lower().replace('_', ' ')} on {milestone}."
    else:
        fu = draft.get("followup_date")
        note = f"Synthetic note: {action} proposed for {milestone}" + (f"; follow-up {fu}." if fu else ".")
    outreach = ""
    if action in CONTACT_ACTIONS:
        outreach = (f"Hello {state.get('party_name') or 'assigned party'}, please share a status update on the "
                    f"{milestone} step for loan {state['loan_id']}. The current follow-up date is "
                    f"{state.get('effective_followup_date') or 'not set'}. Thank you.")
    return {"rationale": rationale, "suggested_note": note, "suggested_outreach": outreach}


def build_recommendation(executor: ToolExecutor, loan_id: str, state: dict, settings, agent_mode: str, run_id: str,
                         choice: dict | None = None, fallback_reason: str | None = None) -> dict:
    """Merge deterministic tool facts and optional model choice into a Recommendation dict."""
    failed = ensure_mandatory(executor, loan_id)
    r = executor.results
    uncertainty_notes: list[str] = []
    if fallback_reason:
        uncertainty_notes.append(f"LLM unavailable; deterministic analysis used ({fallback_reason}).")

    allowed_info = r.get("get_allowed_actions") or {"allowed_actions": ["NO_ACTION"], "default_action": "NO_ACTION"}
    allowed = allowed_info["allowed_actions"]
    default_action = allowed_info["default_action"]
    chosen = (choice or {}).get("recommended_action") or default_action
    chosen = str(chosen).strip().upper()
    overridden = False
    if chosen not in allowed:
        uncertainty_notes.append(f"Model proposed {chosen}, which is not allowed; replaced with deterministic "
                                 f"default {default_action}.")
        chosen, overridden = default_action, True

    status = "PENDING_REVIEW"
    if failed:
        status = "FAILED"
        chosen = "NO_ACTION"
        uncertainty_notes.append("Mandatory tool failure; no action proposed. Route to specialist review.")

    narrative_seed = template_narrative(state, chosen, {})
    note = (choice or {}).get("suggested_note") if choice and not overridden else None
    outreach = (choice or {}).get("suggested_outreach") if choice and not overridden else None
    if chosen == "ESCALATE_TO_SPECIALIST":
        draft = executor.call("prepare_escalation", {"loan_id": loan_id, "reason": note or None})
    else:
        draft = executor.call("prepare_followup_event", {"loan_id": loan_id, "action_type": chosen,
                                                         "note": note or narrative_seed["suggested_note"],
                                                         "outreach": outreach or narrative_seed["suggested_outreach"]})
    draft_data = draft["data"] or {}
    if draft_data.get("creates_event"):
        executor.call("check_existing_event", {"loan_id": loan_id, "event_type": draft_data["event_type"],
                                               "milestone_type": draft_data.get("milestone_type"),
                                               "action_type": chosen})
    validation = executor.call("validate_proposed_event", {
        "loan_id": loan_id, "action_type": chosen, "event_type": draft_data.get("event_type"),
        "followup_date": draft_data.get("followup_date"), "note": draft_data.get("event_note"),
    })
    validation_data = validation["data"] or {"valid": False, "errors": [{"code": "TOOL_ERROR",
                                                                         "message": validation["error"]}]}
    template = template_narrative(state, chosen, draft_data)

    # Confidence: model value bounded by deterministic caps.
    cap = "HIGH"
    if state["primary_condition"] in MEDIUM_CAP_CONDITIONS:
        cap = "MEDIUM"
    if fallback_reason or overridden or not validation_data.get("valid", False) or failed:
        cap = "LOW" if (overridden or failed or not validation_data.get("valid", False)) else "MEDIUM"
    model_conf = str((choice or {}).get("confidence") or "HIGH").upper()
    if model_conf not in CONFIDENCE_ORDER:
        model_conf = "MEDIUM"
    confidence = CONFIDENCE_ORDER[min(CONFIDENCE_ORDER.index(model_conf), CONFIDENCE_ORDER.index(cap))]
    if not validation_data.get("valid", False):
        codes = ", ".join(e["code"] for e in validation_data.get("errors", []))
        uncertainty_notes.append(f"Proposed event failed validation ({codes}); reviewer must edit or reject.")

    missing = deterministic_missing_information(state, executor)
    for item in (choice or {}).get("missing_information") or []:
        if item and item not in missing:
            missing.append(str(item)[:200])
    model_uncertainty = (choice or {}).get("uncertainty")
    uncertainty = " ".join(([model_uncertainty] if model_uncertainty and not overridden else []) + uncertainty_notes)

    sc = r.get("calculate_loan_attention_score") or {}
    es = r.get("calculate_escalation_state") or {}
    rec = {
        "recommendation_id": new_recommendation_id(),
        "loan_id": loan_id,
        "primary_condition": state["primary_condition"],
        "secondary_conditions": state["secondary_conditions"],
        "attention_score": int(sc.get("score", state["attention_score"])),
        "priority": sc.get("priority", state["priority"]),
        "score_drivers": sc.get("score_drivers", state["score_drivers"]),
        "recommended_action": chosen,
        "recommended_event_type": draft_data.get("event_type"),
        "recommended_followup_date": draft_data.get("followup_date"),
        "suggested_note": draft_data.get("event_note") or template["suggested_note"],
        "suggested_outreach": draft_data.get("outreach_text") or "",
        "rationale": ((choice or {}).get("rationale") if choice and not overridden else None) or template["rationale"],
        "evidence": build_evidence(executor, state),
        "confidence": confidence,
        "uncertainty": uncertainty or "None material; all facts came from deterministic tools.",
        "missing_information": missing,
        "tool_calls": executor.records,
        "created_at": now_iso(),
        "agent_version": f"{settings.agent_version}-{agent_mode}",
        "rule_version": settings.rule_version,
        "scoring_version": settings.scoring_version,
        "status": status,
        "requires_human_approval": True,
        "allowed_actions": allowed,
        "escalation_state": es.get("escalation_state", state["escalation_state"]),
        "state_fingerprint": state["state_fingerprint"],
        "proposed_event": draft_data,
        "validation": validation_data,
        "agent_mode": agent_mode,
        "run_id": run_id,
        "synthetic_data": True,
    }
    if (choice or {}).get("evidence_refs"):
        rec["evidence"].append(_ev("TOOL", "submit_recommendation", "Tools cited by the agent",
                                   ", ".join(map(str, choice["evidence_refs"]))[:300]))
    return rec


# ====================================================================================================
# Deterministic Loan Servicing Agent: fixed investigation plan, templated narrative
# ====================================================================================================

INVESTIGATION_PLAN = [
    "get_loan_context", "get_event_history", "get_current_milestone", "check_milestone_completion",
    "check_followup_status", "check_pending_action", "check_previous_rejection", "get_assigned_party",
    "calculate_escalation_state", "calculate_loan_attention_score", "get_allowed_actions",
]
DECLINE_TERMS = ("legal advice", "lawsuit", "eligib", "should i foreclose", "foreclosure authority", "loss mitigation",
                 "financial advice", "compliance decision", "is it legal")


class DeterministicLoanServicingAgent(LoanServicingAgent):
    mode = "deterministic"

    def __init__(self, settings):
        self.settings = settings
        self.agent_version = f"{settings.agent_version}-deterministic"

    def assess_loan(self, loan_id: str, run: RunContext, fallback_reason: str | None = None) -> dict:
        loan_id = loan_id.strip().upper()
        executor = run.executor(loan_id)
        run.step("candidate_detected", loan_id, "Assessment requested")
        first = executor.call(INVESTIGATION_PLAN[0], {"loan_id": loan_id})
        if not first["success"]:
            return {"recommendation": None, "answer": f"Assessment failed: {first['error']}",
                    "tool_calls": executor.records, "agent_mode": self.mode, "error": first["error"]}
        for name in INVESTIGATION_PLAN[1:]:
            executor.call(name, {"loan_id": loan_id})
        state = run.tool_ctx.result(loan_id)
        rec = build_recommendation(executor, loan_id, state, self.settings, self.mode, run.run_id,
                                   choice=None, fallback_reason=fallback_reason)
        run.step("recommendation_generated", loan_id, f"{rec['recommended_action']} ({rec['confidence']})")
        run.step("awaiting_approval", loan_id, rec["status"])
        return {"recommendation": rec, "answer": rec["rationale"], "tool_calls": executor.records,
                "agent_mode": self.mode}

    # ---- governed questions ---------------------------------------------------------------
    def answer_question(self, question: str, loan_id: str | None, run: RunContext) -> dict:
        q = (question or "").lower()
        executor = run.executor(loan_id)
        if any(term in q for term in DECLINE_TERMS):
            return {"answer": "I can't provide legal, financial, eligibility, or other regulated determinations. "
                              "Please refer this question to the appropriate servicing manager or counsel. I can "
                              "summarize the loan's servicing facts if helpful.",
                    "tool_calls": [], "agent_mode": self.mode}
        if not loan_id:
            summary = executor.call("get_portfolio_health_summary", {})["data"]
            queue = executor.call("get_priority_queue", {"limit": 5})["data"]
            top = ", ".join(f"{r['loan_id']} ({r['priority']}, {r['primary_condition']})" for r in queue["rows"])
            answer = (f"{summary['need_attention']} of {summary['active_loans']} active loans need attention; "
                      f"{summary['critical']} are CRITICAL. Top of the queue: {top}. "
                      "(get_portfolio_health_summary, get_priority_queue)")
            return {"answer": answer, "tool_calls": executor.records, "agent_mode": self.mode}

        loan_id = loan_id.strip().upper()
        ctx_res = executor.call("get_loan_context", {"loan_id": loan_id})
        if not ctx_res["success"]:
            return {"answer": f"Loan {loan_id} was not found.", "tool_calls": executor.records, "agent_mode": self.mode}
        state = run.tool_ctx.result(loan_id)
        score = executor.call("calculate_loan_attention_score", {"loan_id": loan_id})["data"]
        cond_text = "; ".join(f"{c['code']} ({c['rule_id']}): {c['detail']}" for c in state["raw_conditions"])

        if any(w in q for w in ("why", "prioriti", "flag", "priority", "score")):
            drivers = executor.call("get_attention_score_drivers", {"loan_id": loan_id})["data"]
            answer = (f"{loan_id} is {state['priority']} with score {score['score']}. Conditions: {cond_text}. "
                      f"Score drivers: {drivers['summary']}. Escalation is {state['escalation_state']} "
                      f"(required role {state['required_role']}). The score is calculated deterministically from "
                      "config/attention_scoring.yml. (calculate_loan_attention_score, get_attention_score_drivers)")
        elif "reject" in q:
            answer = ("Rejecting records your decision and reason, creates no outbound event, and removes the "
                      "rejected action from this loan's allowed actions for 14 days (RULE-REVIEW-001) unless "
                      f"escalation reaches ESCALATE or CRITICAL. The loan stays in the queue while {state['primary_condition']} "
                      "persists. (check_previous_rejection)")
            executor.call("check_previous_rejection", {"loan_id": loan_id})
        elif "next" in q:
            nxt = executor.call("get_next_required_milestone", {"loan_id": loan_id})["data"]
            allowed = executor.call("get_allowed_actions", {"loan_id": loan_id})["data"]
            answer = (f"Current milestone: {state['current_milestone'] or 'none'}; configured next milestone: "
                      f"{nxt['next_milestone_type'] or 'none'} (exists already: {nxt['exists_already']}). "
                      f"Allowed actions now: {', '.join(allowed['allowed_actions'])}; deterministic default "
                      f"{allowed['default_action']}. (get_next_required_milestone, get_allowed_actions)")
        elif "missing" in q:
            missing = deterministic_missing_information(state, executor)
            answer = ("Missing information: " + ("; ".join(missing) if missing else "none detected by the rules")
                      + f". Conditions: {cond_text}.")
        elif "pending" in q:
            pa = executor.call("check_pending_action", {"loan_id": loan_id})["data"]
            pr = executor.call("check_pending_recommendation", {"loan_id": loan_id})["data"]
            answer = (f"Pending actions: {', '.join(a['action_id'] + ' ' + a['action_type'] for a in pa['pending_actions']) or 'none'}. "
                      f"Recommendations awaiting review: {len(pr['pending_recommendations'])}. "
                      "(check_pending_action, check_pending_recommendation)")
        elif "follow" in q or "existing" in q or "duplicate" in q:
            fu = executor.call("check_followup_status", {"loan_id": loan_id})["data"]
            ex = executor.call("check_existing_event", {"loan_id": loan_id, "event_type": "FOLLOWUP"})["data"]
            answer = (f"Effective follow-up: {fu['effective_followup_date'] or 'none'} (days to follow-up "
                      f"{fu['days_to_followup']}, days overdue {fu['days_overdue']}); open follow-up events for the "
                      f"current milestone: {fu['open_followup_events']}; open not-overdue FOLLOWUP equivalents: "
                      f"{len(ex['open_equivalent_events'])}. (check_followup_status, check_existing_event)")
        elif "rule" in q:
            rule = executor.call("get_milestone_rule", {"milestone_type": state["current_milestone"] or ""})["data"]
            answer = (f"Applicable rules: {', '.join(state['condition_rule_ids'])}. Milestone rule for "
                      f"{state['current_milestone']}: " + (
                          f"follow-up {rule.get('default_followup_days')} days, look-ahead {rule.get('lookahead_days')} "
                          f"days, overdue action {rule.get('overdue_action')}, severity {rule.get('severity')} (synthetic)."
                          if rule.get("found") else "no active rule (RULE-DATA-001)."))
        elif "evidence" in q:
            for name in ("get_current_milestone", "check_followup_status", "calculate_escalation_state"):
                executor.call(name, {"loan_id": loan_id})
            answer = (f"Evidence: {cond_text}. Milestone {state['current_milestone']}, effective follow-up "
                      f"{state['effective_followup_date']}, escalation {state['escalation_state']}, score "
                      f"{score['score']} ({score['priority']}).")
        else:
            narrative = template_narrative(state, state["default_action"], {})
            answer = narrative["rationale"]
        return {"answer": answer, "tool_calls": executor.records, "agent_mode": self.mode}

    def portfolio_briefing(self, facts: list[dict], run: RunContext) -> dict:
        return {"text": deterministic_briefing(facts), "source": "deterministic", "rejected_reason": None}


# ====================================================================================================
# LLM tool-calling Loan Servicing Agent (OpenAI-compatible chat with tools)
# ====================================================================================================

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


# ====================================================================================================
# Agent selection by mode (auto | llm | deterministic)
# ====================================================================================================

def create_agent(settings, mode: str | None = None, llm: LlmClient | None = None) -> LoanServicingAgent:
    mode = (mode or settings.agent.get("mode") or "auto").lower()
    deterministic = DeterministicLoanServicingAgent(settings)
    if mode == "deterministic":
        return deterministic
    client = llm or DatabricksFoundationModelClient(settings.agent["model_endpoint"],
                                                    int(settings.agent.get("request_timeout_seconds", 90)))
    return ToolCallingLoanServicingAgent(settings, client, deterministic, allow_fallback=(mode == "auto"))
