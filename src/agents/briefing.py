"""Portfolio briefing: deterministic template and the number guard for LLM drafts (ADR-012)."""
from __future__ import annotations

import re

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
