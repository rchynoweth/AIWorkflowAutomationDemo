# Assumptions and Limitations — Loan Servicing Intelligence

## Synthetic-data statement

All data is synthetic and generated with a fixed seed. Names (`Synthetic Borrower 0001`, `Synthetic Specialist
01`, `Synthetic Legal Vendor 01`), addresses, cities, counties, postal codes, balances, events, and notes are
fabricated tokens. No real person, property, account, or organization is represented.

## Assumptions

| ID | Assumption |
|----|-----------|
| A-01 | The processing date is fixed at 2026-10-12 in demo mode so scenarios stay deterministic. |
| A-02 | The servicing/legal milestone sequence (BORROWER_OUTREACH … SALE_COMPLETED) is a generic synthetic illustration, not a legal process for any jurisdiction. |
| A-03 | Each loan has one assigned specialist and one assigned external party (attorney or vendor). |
| A-04 | Follow-up-type events (FOLLOWUP, CONTACT, ESCALATION, INFO_REQUEST, DATA_REVIEW) reset the follow-up clock for the current milestone. |
| A-05 | The simulated System of Record supersedes prior open follow-up-type events for the milestone when a new one is created (except in DUPLICATE mode). |
| A-06 | Adapter-created events are identifiable by `source = SERVICING_SYSTEM_ADAPTER` and `created_at`. |
| A-07 | Verification window is two days; actions not found after the window are NOT_FOUND. |
| A-08 | Thresholds, weights, mappings, and precedence in `config/` are illustrative and configurable. |
| A-09 | Reviewer identity is selected in the UI (synthetic specialists) for demonstration; it is not an authorization control. |
| A-10 | Portfolio scale (~1,500 loans) allows in-process evaluation; larger portfolios would evaluate in Spark and read Gold directly. |
| A-11 | The LLM is accessed through a pay-per-token Databricks Foundation Model API endpoint. |

## Limitations

- **No production integration.** The `SyntheticServicingSystemAdapter` writes to a simulated System of Record
  table. No real servicing platform, API, or browser automation is used.
- **No regulated or legal decisions.** The product does not determine lending, borrower eligibility, legal
  strategy, foreclosure authority, compliance, or loss-mitigation outcomes, and does not provide legal or
  financial advice.
- **Every consequential action requires explicit human approval.** The agent only prepares proposals.
- **Feedback does not automatically change behavior.** Reviewer decisions inform offline evaluation only.
- **Authorization is a demo model.** Roles are displayed and recorded; they are not enforced per user.
- **In-process API.** The API runs inside the App container; it is not exposed as a separately scaled service.
- **Concurrency.** The app holds in-memory state with write-through persistence; it assumes a single app
  instance and light concurrent use.
- **LLM variability.** LLM narratives and choices (within allowed actions) can vary between runs; deterministic
  facts do not.
- **Synthetic metrics.** Evaluation metrics demonstrate methodology, not real-world performance.
- **Time handling.** Business dates use the processing date; operational timestamps use UTC wall-clock time.

## Production prerequisites

Before any production use: security review (identity, OBO, secrets, network), privacy review (borrower data
handling, minimization, retention), legal and compliance review (servicing regulations, communications
content), operational review (runbooks, SLAs, incident handling), integration review (System of Record APIs,
idempotency, reconciliation), model risk/AI governance review, and accessibility review.
