"""Shared fixtures (synthetic data only; no Databricks required)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["LSI_AGENT_MODE"] = "deterministic"
os.environ["LSI_REPOSITORY_BACKEND"] = "local"

from src.config.settings import load_settings  # noqa: E402
from src.ingestion.bronze import ingest_directory  # noqa: E402
from src.repositories.local import LocalRepository  # noqa: E402
from src.services.portfolio_engine import evaluate_portfolio  # noqa: E402
from src.services.servicing_service import LoanServicingService  # noqa: E402
from src.services.state import OperationalState  # noqa: E402
from src.tools.servicing_tools import ToolContext  # noqa: E402
from src.transformations.silver import build_silver  # noqa: E402

GENERATED = ROOT / "data" / "generated"


@pytest.fixture(scope="session")
def settings():
    return load_settings()


@pytest.fixture(scope="session")
def settings_no_baseline():
    return load_settings(overrides={"demo_scenarios.baseline_recommendations": {"enabled": False}})


@pytest.fixture(scope="session")
def bronze():
    return ingest_directory(GENERATED)


@pytest.fixture(scope="session")
def silver(bronze, settings):
    return build_silver(bronze, settings)


@pytest.fixture(scope="session")
def evaluation(silver, settings):
    return evaluate_portfolio(silver, settings)


@pytest.fixture(scope="session")
def tool_ctx(evaluation, settings):
    return ToolContext(evaluation, OperationalState(), settings)


@pytest.fixture()
def service(tmp_path, settings_no_baseline):
    repo = LocalRepository(settings_no_baseline, source_dir=GENERATED, state_dir=tmp_path / "state")
    svc = LoanServicingService(settings_no_baseline, repo, agent_mode="deterministic")
    svc.settings.application["data"]["outbound_dir"] = str(tmp_path / "outbound")
    return svc.load()


def loan(n: int) -> str:
    return f"LSI-SYN-{n:06d}"
