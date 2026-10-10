"""In-memory operational state (write-through to the repository)."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class OperationalState:
    recommendations: dict[str, dict] = field(default_factory=dict)
    decisions: dict[str, dict] = field(default_factory=dict)
    actions: dict[str, dict] = field(default_factory=dict)
    verification_results: dict[str, dict] = field(default_factory=dict)
    activity: list[dict] = field(default_factory=list)
    sor_events: list[dict] = field(default_factory=list)
    runtime: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_tables(cls, tables: dict[str, list[dict]]) -> "OperationalState":
        state = cls()
        state.recommendations = {r["recommendation_id"]: r for r in tables.get("ops_recommendations", [])}
        state.decisions = {r["decision_id"]: r for r in tables.get("ops_reviewer_decisions", [])}
        state.actions = {r["action_id"]: r for r in tables.get("ops_actions", [])}
        state.verification_results = {r["verification_id"]: r for r in tables.get("ops_verification_results", [])}
        state.activity = sorted(tables.get("ops_agent_activity", []), key=lambda r: str(r.get("created_at")))
        state.sor_events = tables.get("sor_servicing_events", [])
        state.runtime = {r["state_key"]: r["state_value"] for r in tables.get("ops_runtime_state", [])}
        return state

    @property
    def refresh_cycle(self) -> int:
        return int(self.runtime.get("refresh_cycle", "0") or 0)

    def recommendations_for(self, loan_id: str) -> list[dict]:
        recs = [r for r in self.recommendations.values() if r["loan_id"] == loan_id]
        return sorted(recs, key=lambda r: str(r.get("created_at")), reverse=True)

    def actions_frame(self) -> pd.DataFrame | None:
        return pd.DataFrame(list(self.actions.values())) if self.actions else None

    def decisions_frame(self) -> pd.DataFrame | None:
        return pd.DataFrame(list(self.decisions.values())) if self.decisions else None

    def sor_frame(self) -> pd.DataFrame | None:
        return pd.DataFrame(self.sor_events) if self.sor_events else None
