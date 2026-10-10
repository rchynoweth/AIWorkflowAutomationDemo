# Client Demo Script — Loan Servicing Intelligence

> Say it early and often: **every borrower, loan, rule, threshold, score, and metric you will see is synthetic.**
> Duration: 20–25 minutes. Audience: business and technical stakeholders.

## Before the demo (10 minutes ahead)

1. Start the app: `databricks apps start loan-servicing-intelligence` (it is kept stopped to avoid idle cost).
2. Open the app URL once to warm the serverless SQL warehouse (first query ~10–20 s from a cold start).
3. In the sidebar choose reviewer **Synthetic Specialist 01 (LOAN_SERVICING_SPECIALIST)**.
4. Click **Reset demo** in the sidebar (demo mode) so recommendations, decisions, actions, and verification
   start clean. Processing date shows **2026-10-12**.

Key loans:

| Loan | Use |
|------|-----|
| `LSI-SYN-000005` | Main path: TITLE_REVIEW 18 days overdue, HIGH, CONTACT_ATTORNEY → approve → VERIFIED |
| `LSI-SYN-000006` | Severely overdue, CRITICAL, escalation |
| `LSI-SYN-000004` | Configured adapter failure (FAIL) → returns to queue |
| `LSI-SYN-000016` | Pre-existing failed verification (NOT_FOUND) |
| `LSI-SYN-000019` | Looks urgent but already covered by a pending action (ALREADY_ACTIONED, LOW) |

## Script

The app opens on **Demo Story**, which contains this storyline as ten clickable chapters with talk track
(`config/demo_story.yml`). Click **Open** on each chapter, or **Next chapter** in the banner at the top of each
page. Turn presenter notes off in the sidebar when sharing the screen with notes hidden.

1. **Open Home — portfolio-wide monitoring.** "Instead of opening loans one at a time, every active loan is
   evaluated every cycle by deterministic, configurable rules." Point to the synthetic badge.
2. **Portfolio metrics and AI briefing.** Walk the KPI cards and health segments; click **Critical**. Read
   Today's Portfolio Briefing: "The agent wrote this, but only from the deterministic facts in the expander —
   any number not in the facts is rejected automatically."
3. **Open the prioritized task list.** Go to **Priority Queue**. Show filters and the *why prioritized* column.
4. **Select a high-priority overdue loan.** Pick `LSI-SYN-000005`.
5. **Loan 360 and event timeline.** Header, Overview, then **Events**: completed milestones, the current
   TITLE_REVIEW milestone, and the overdue follow-up in red.
6. **Deterministic condition and score.** Overview: condition OVERDUE (RULE-FOLLOWUP-003), score 54 = 30
   (overdue) + 18 (days overdue) + 6 (severity). "The model never calculates this."
7. **Agent evidence and recommendation.** **Agent Analysis → Run agent analysis.** Show the tool calls, the
   evidence table, rationale, recommended CONTACT_ATTORNEY, proposed follow-up date, draft note and outreach,
   confidence, uncertainty, missing information, and the allowed-actions list.
8. **Ask why the loan was prioritized.** In **Ask the Agent**, click "Why is this loan prioritized?" Show the
   answer and its tool calls.
9. **Approve or edit.** Click **Edit**, shorten the follow-up date, adjust the note, approve. "The action is
   revalidated — currency, duplicates, pending actions, fields, allowed actions — before anything is created."
10. **Show the outbound event.** Expand the outbound event JSON (loan-servicing-system-compatible, synthetic).
11. **Run the synthetic adapter.** Click **Submit via synthetic adapter** → status SUBMITTED. "This simulates
    the System of Record; there is no browser automation and no real platform."
12. **Refresh ingestion.** Click **Refresh source & verify** (or the sidebar control).
13. **Verification success.** Status **VERIFIED**; the timeline shows the new event with a check; the loan
    drops out of the attention queue.
14. **Configured failure returns to the queue.** Open `LSI-SYN-000004`, run analysis, approve, submit
    (adapter configured to FAIL), refresh → **FAILED** → condition VERIFICATION_FAILURE, back in the queue at
    higher priority. Also show `LSI-SYN-000016` (NOT_FOUND from a prior cycle) and `LSI-SYN-000019` (urgent
    looking but covered by a pending action, so LOW).
15. **Evaluation — rule vs agent quality.** Open **Evaluation**: deterministic rule metrics are 100% against
    the scenario manifest; agent metrics (agreement, compliance, evidence, failures) are measured separately;
    reviewer acceptance/edit/rejection rates are signals for controlled, offline improvement only. Open
    **Agent Activity** to show the trace chain.
16. **Close.** "All data, rules, thresholds, and metrics are synthetic. Agents do the investigative work,
    people stay accountable for consequential decisions, and the servicing platform remains the System of Record."

## Fallbacks

- LLM slow/unavailable: the header shows agent mode; deterministic agent produces the same structure.
- Warehouse cold: wait for the first load; subsequent interactions are in-memory.
- Anything odd: sidebar **Reset demo**.

## After the demo

`databricks apps stop loan-servicing-intelligence` — the warehouse auto-stops after 10 minutes and the
model endpoint is pay-per-token, so nothing else keeps running.
