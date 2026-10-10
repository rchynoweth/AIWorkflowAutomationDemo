"""System instructions for the Loan Servicing Agent (synthetic demonstration)."""

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
