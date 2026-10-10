"""Configuration loading with environment overrides.

All configuration lives in ``config/*.yml``. Environment variables override a small set of deployment
settings (backend, catalog/schema, warehouse, model endpoint, processing date, agent mode).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

CONFIG_FILES = {
    "application": "application.yml",
    "business_rules": "business_rules.yml",
    "attention_scoring": "attention_scoring.yml",
    "escalation_rules": "escalation_rules.yml",
    "allowed_actions": "allowed_actions.yml",
    "demo_scenarios": "demo_scenarios.yml",
}


def repo_root() -> Path:
    """Repository root (directory containing ``config/``)."""
    return Path(__file__).resolve().parents[2]


def _truthy(value: str | None) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    """Typed view over the YAML configuration."""

    application: dict[str, Any]
    business_rules: dict[str, Any]
    attention_scoring: dict[str, Any]
    escalation_rules: dict[str, Any]
    allowed_actions: dict[str, Any]
    demo_scenarios: dict[str, Any]
    root: Path = field(default_factory=repo_root)

    # ---- convenience accessors -------------------------------------------------
    @property
    def app_name(self) -> str:
        return self.application["application"]["name"]

    @property
    def subtitle(self) -> str:
        return self.application["application"]["subtitle"]

    @property
    def synthetic_label(self) -> str:
        return self.application["application"]["synthetic_label"]

    @property
    def processing_date(self) -> date:
        return date.fromisoformat(str(self.application["processing"]["processing_date"]))

    @property
    def rule_version(self) -> str:
        return self.business_rules["version"]

    @property
    def scoring_version(self) -> str:
        return self.attention_scoring["version"]

    @property
    def escalation_version(self) -> str:
        return self.escalation_rules["version"]

    @property
    def actions_version(self) -> str:
        return self.allowed_actions["version"]

    @property
    def agent_version(self) -> str:
        return self.application["versions"]["agent_version"]

    @property
    def thresholds(self) -> dict[str, Any]:
        return self.business_rules["thresholds"]

    @property
    def seed(self) -> int:
        return int(self.application["data"]["seed"])

    @property
    def loan_count(self) -> int:
        return int(self.application["data"]["loan_count"])

    @property
    def demo_mode(self) -> bool:
        return _truthy(os.environ.get("DEMO_MODE", str(self.demo_scenarios.get("demo_mode", True))))

    @property
    def backend(self) -> str:
        return self.application["repository"]["backend"]

    @property
    def catalog(self) -> str:
        return self.application["databricks"]["catalog"]

    @property
    def schema(self) -> str:
        return self.application["databricks"]["schema"]

    @property
    def warehouse_id(self) -> str:
        return self.application["databricks"].get("warehouse_id") or ""

    @property
    def agent(self) -> dict[str, Any]:
        return self.application["agent"]

    @property
    def api_port(self) -> int:
        return int(self.application["api"]["port"])

    def path(self, key: str) -> Path:
        """Resolve a data directory from ``application.data`` relative to the repository root."""
        return self.root / self.application["data"][key]

    def versions(self) -> dict[str, str]:
        return {
            "rule_version": self.rule_version,
            "scoring_version": self.scoring_version,
            "escalation_version": self.escalation_version,
            "actions_version": self.actions_version,
            "agent_version": self.agent_version,
        }


def load_settings(config_dir: str | Path | None = None, overrides: dict[str, Any] | None = None) -> Settings:
    """Load YAML config and apply environment overrides."""
    cfg_dir = Path(config_dir) if config_dir else repo_root() / "config"
    data: dict[str, Any] = {}
    for key, filename in CONFIG_FILES.items():
        with open(cfg_dir / filename, encoding="utf-8") as fh:
            data[key] = yaml.safe_load(fh) or {}

    app = data["application"]
    env = os.environ
    if env.get("LSI_PROCESSING_DATE"):
        app["processing"]["processing_date"] = env["LSI_PROCESSING_DATE"]
    if env.get("LSI_REPOSITORY_BACKEND"):
        app["repository"]["backend"] = env["LSI_REPOSITORY_BACKEND"]
    if env.get("LSI_CATALOG"):
        app["databricks"]["catalog"] = env["LSI_CATALOG"]
    if env.get("LSI_SCHEMA"):
        app["databricks"]["schema"] = env["LSI_SCHEMA"]
    if env.get("DATABRICKS_WAREHOUSE_ID"):
        app["databricks"]["warehouse_id"] = env["DATABRICKS_WAREHOUSE_ID"]
    if env.get("LSI_AGENT_MODE"):
        app["agent"]["mode"] = env["LSI_AGENT_MODE"]
    if env.get("LSI_MODEL_ENDPOINT"):
        app["agent"]["model_endpoint"] = env["LSI_MODEL_ENDPOINT"]
    if env.get("LSI_API_PORT"):
        app["api"]["port"] = int(env["LSI_API_PORT"])

    for dotted, value in (overrides or {}).items():
        section, _, rest = dotted.partition(".")
        target = data[section]
        parts = rest.split(".")
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = value

    root = cfg_dir.parent if config_dir else repo_root()
    return Settings(root=root, **data)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
