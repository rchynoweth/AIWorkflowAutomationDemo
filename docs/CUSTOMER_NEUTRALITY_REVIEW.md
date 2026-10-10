# Customer-Neutrality Review — Loan Servicing Intelligence

## Product identity

- **Product name:** Loan Servicing Intelligence
- **Subtitle:** Agent-powered portfolio monitoring and loan-servicing workflow automation
- **Status:** Reusable, customer-neutral synthetic reference application.

## Method

Automated scanner `src/quality/neutrality.py`, run by `tests/unit/test_customer_neutrality.py` and
`python -m src.quality.neutrality`. It recursively scans file **names, directory names, and contents** of all
text files in the repository (excluding `.git`, virtual environments, caches, and the license file).

### Locations searched
Source (`src/`), application (`app/`), notebooks (`notebooks/`), SQL (`sql/`), configuration (`config/`,
`app.yaml`, `databricks.yml`, `.env.example`, `.streamlit/`), tests and fixtures (`tests/`), generated data
(`data/generated/*.csv`), documentation (`README.md`, `docs/`), scripts (`scripts/`), and any runtime logs or
outbound files present under `data/` at scan time.

### Categories checked
| Category | Check |
|----------|-------|
| Customer / employee / stakeholder names | Optional private denylist via `LSI_NEUTRALITY_DENYLIST` (terms never committed) |
| Customer URLs / paths / workspace hosts | Any URL or host not on the allowlist (e.g. `example.com`, `localhost`, public docs) |
| Email addresses | Any email not at `example.com`/`example.org` or `noreply@anthropic.com` (commit attribution) |
| Real person / property / account data | Phone-number, SSN-like, and street-address patterns; generated names must match the `Synthetic …` pattern |
| Customer documents / presentations / supplied files | File-type check: no `.pptx`, `.docx`, `.pdf`, `.xlsx`, `.msg`, `.eml` in the repository |
| Claims of actual production policy/schema | Phrases asserting that content is a real organization's production schema, servicing policy, or borrower data (pattern list in `src/quality/neutrality.py`) |
| Synthetic labeling | Generated CSVs contain `synthetic_data = true` (except the manifest); UI shows the synthetic label |

## Results

| Run | Date | Files scanned | Findings | Result |
|-----|------|---------------|----------|--------|
| Initial (design docs) | 2026-10-10 | Docs + config | 0 | Pass |

*(Updated by the final validation run — see the bottom of this document.)*

## References removed

None required: the repository was authored from a customer-neutral brief. No customer names, employees,
stakeholders, URLs, documents, presentations, systems, or processes were introduced. Workspace-specific values
(hosts, user identities, warehouse IDs) are supplied at deploy time via CLI arguments or environment
variables and are not committed.

## Confirmations

- Product name and subtitle confirmed as above.
- All data, rules, thresholds, workflows, scores, and metrics are labeled synthetic in docs, config headers,
  generated data, and the UI.
- No claim is made that the schema or rules represent any lender's production schema, servicing policy,
  legal process, or regulated decision framework.
- The repository is reusable and customer-neutral.
