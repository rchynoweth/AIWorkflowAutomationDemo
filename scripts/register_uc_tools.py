"""Register the agent's Unity Catalog tool functions through a SQL warehouse and smoke-test each one.

Usage: python scripts/register_uc_tools.py --warehouse-id <id> [--catalog main] [--schema loan_servicing_intelligence]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import load_settings  # noqa: E402
from src.storage import DatabricksSqlRepository  # noqa: E402
from src.tools import uc_function_statements  # noqa: E402

SAMPLE_ARGS = {"lsi_get_milestone_rule": "'TITLE_REVIEW'", "lsi_priority_queue": "5",
               "lsi_portfolio_health_summary": "", "lsi_specialist_workload": "", "lsi_get_failed_verifications": ""}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--warehouse-id", required=True)
    parser.add_argument("--catalog", default="main")
    parser.add_argument("--schema", default="loan_servicing_intelligence")
    args = parser.parse_args()
    repo = DatabricksSqlRepository(load_settings(), warehouse_id=args.warehouse_id, catalog=args.catalog,
                                   schema=args.schema, async_writes=False)
    failures = 0
    for name, statement in uc_function_statements(args.catalog, args.schema):
        try:
            repo.execute(statement)
            sample = SAMPLE_ARGS.get(name, "'LSI-SYN-000005'")
            rows = repo.execute(f"SELECT * FROM `{args.catalog}`.`{args.schema}`.`{name}`({sample}) LIMIT 3")
            print(f"OK   {name:32s} {len(rows)} row(s)")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"FAIL {name:32s} {str(exc)[:300]}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
