"""Every registered tool is typed, logged, independently runnable, and fails safely."""
import pytest

from src.tools.executor import ToolExecutor
from src.tools.registry import ALL_TOOLS, REGISTRY

LOAN = "LSI-SYN-000005"
ARGS = {
    "check_existing_event": {"loan_id": LOAN, "event_type": "CONTACT"},
    "calculate_followup_date": {"loan_id": LOAN, "action_type": "CONTACT_ATTORNEY"},
    "prepare_followup_event": {"loan_id": LOAN, "action_type": "CONTACT_ATTORNEY"},
    "validate_proposed_event": {"loan_id": LOAN, "action_type": "CONTACT_ATTORNEY"},
    "get_milestone_rule": {"milestone_type": "TITLE_REVIEW"},
    "verify_servicing_event_created": {"action_id": None},
    "compare_approved_to_actual": {"action_id": None},
}


def test_registry_has_29_tools_with_schemas():
    assert len(REGISTRY) == 29
    for spec in REGISTRY.values():
        tool = spec.openai_tool()
        assert tool["function"]["name"] == spec.name and tool["function"]["description"]
        assert tool["function"]["parameters"]["type"] == "object"


@pytest.mark.parametrize("name", ALL_TOOLS)
def test_tool_runs(tool_ctx, evaluation, name):
    args = dict(ARGS.get(name, {"loan_id": LOAN}))
    if "action_id" in args:
        args["action_id"] = evaluation.facts["LSI-SYN-000015"].actions[0]["action_id"]
    spec = REGISTRY[name]
    if "loan_id" not in spec.input_model.model_fields:
        args.pop("loan_id", None)
    records = []
    result = ToolExecutor(tool_ctx, "RUN-T", LOAN, records.append).call(name, args)
    assert result["success"], result["error"]
    assert records and records[0]["tool_name"] == name and records[0]["duration_ms"] >= 0


def test_unknown_loan_is_not_fabricated(tool_ctx):
    result = ToolExecutor(tool_ctx, "RUN-T").call("get_loan_context", {"loan_id": "LSI-SYN-999999"})
    assert not result["success"] and result["error"] == "LOAN_NOT_FOUND" and result["data"] is None


def test_invalid_input_rejected(tool_ctx):
    result = ToolExecutor(tool_ctx, "RUN-T").call("get_loan_context", {"loan": "x"})
    assert not result["success"] and result["error"].startswith("INVALID_INPUT")


def test_score_tool_matches_engine(tool_ctx, evaluation):
    data = ToolExecutor(tool_ctx, "RUN-T").call("calculate_loan_attention_score", {"loan_id": LOAN})["data"]
    assert data["score"] == evaluation.get(LOAN)["attention_score"] == 54


def test_prepare_tool_never_commits(tool_ctx):
    draft = ToolExecutor(tool_ctx, "RUN-T").call("prepare_followup_event",
                                                 {"loan_id": LOAN, "action_type": "CONTACT_ATTORNEY"})["data"]
    assert draft["status"] == "DRAFT_UNCOMMITTED" and draft["event_type"] == "CONTACT"


def test_verification_tools(tool_ctx, evaluation):
    action_id = evaluation.facts["LSI-SYN-000017"].actions[0]["action_id"]
    ex = ToolExecutor(tool_ctx, "RUN-T")
    assert ex.call("verify_servicing_event_created", {"action_id": action_id})["data"]["verification_status"] == "MISMATCH"
    diff = ex.call("compare_approved_to_actual", {"action_id": action_id})["data"]["differences"]
    assert diff[0]["field"] == "followup_date"
