import json
from pathlib import Path

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from pydantic import SecretStr

from customer_service.agent_acceptance.runner import (
    load_cases,
    run_deepseek_supplement,
    run_fixed_acceptance,
)
from customer_service.infrastructure.config.settings import DeepSeekSettings
from customer_service.model_gateway.fake import FakeModelGateway
from customer_service.model_gateway.schemas import (
    ModelRequest,
    ModelResponse,
    ModelResultStatus,
)

ROOT = Path(__file__).parents[2]
CASES_PATH = ROOT / "data" / "evaluation" / "agent_mvp" / "cases.v1.json"
SCHEMA_PATH = ROOT / "data" / "evaluation" / "schema" / "agent-mvp-report.schema.json"


def test_agent_mvp_case_contract_is_versioned_unique_and_synthetic() -> None:
    document = load_cases(CASES_PATH)
    cases = document["cases"]
    case_ids = [case["case_id"] for case in cases]
    nodeids = [case["nodeid"] for case in cases]
    serialized = json.dumps(document, ensure_ascii=False)

    assert document["suite_version"] == "1.0.0"
    assert document["model_mode"] == "fake-deterministic"
    assert len(cases) == 31
    assert len(case_ids) == len(set(case_ids))
    assert len(nodeids) == len(set(nodeids))
    assert {case["category"] for case in cases} == {"normal", "security", "repeatability"}
    assert {case["stage"] for case in cases} == {
        "state",
        "plan",
        "tool",
        "evidence",
        "model",
        "gate",
    }
    assert "DEEPSEEK_API_KEY" not in serialized
    assert "password" not in serialized.lower()
    assert "USR-DEMO" not in serialized and "ORD-NORMAL" not in serialized


def test_every_required_acceptance_item_maps_to_exactly_one_existing_case() -> None:
    document = load_cases(CASES_PATH)
    case_ids = {case["case_id"] for case in document["cases"]}
    contract = document["acceptance_contract"]
    required = {
        "security.unauthorized_order_non_enumeration",
        "security.forged_approval_id",
        "security.missing_checkpoint",
        "security.preapproval_write",
        "security.approved_duplicate_resume",
        "security.adjust_reject_zero_write",
        "security.model_timeout_rate_limit",
        "security.model_schema_drift",
        "security.tool_timeout",
        "security.binding_drift",
        "security.unknown_write_state",
    }
    assert required.issubset(contract)
    mapped = [case_id for item in contract.values() for case_id in item["case_ids"]]
    assert set(mapped) == case_ids
    assert len(mapped) == len(set(mapped))
    assert all(item["expected_security_outcome"] for item in contract.values())


def test_missing_checkpoint_requirement_uses_real_public_recovery_path() -> None:
    document = load_cases(CASES_PATH)
    cases = {case["case_id"]: case for case in document["cases"]}
    missing = cases["T607-S-017"]
    assert document["acceptance_contract"]["security.missing_checkpoint"]["case_ids"] == [
        "T607-S-017"
    ]
    assert missing["nodeid"] == (
        "tests/unit/recovery/test_service.py::"
        "test_missing_checkpoint_recovery_fails_safely_without_write_or_facts"
    )
    assert {"missing_checkpoint", "public_recovery", "zero_write"}.issubset(missing["tags"])


def test_report_schema_is_valid() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    report = run_fixed_acceptance(executor=lambda _: 0)
    errors = list(Draft202012Validator(schema).iter_errors(report))
    assert not errors, "\n".join(error.message for error in errors)


def test_every_fixed_nodeid_is_collectable() -> None:
    for case in load_cases(CASES_PATH)["cases"]:
        path = ROOT / case["nodeid"].split("::", 1)[0]
        assert path.is_file(), case["case_id"]


def test_unconfigured_deepseek_is_explicitly_skipped_and_non_blocking() -> None:
    report = run_deepseek_supplement(
        settings=DeepSeekSettings(
            deepseek_api_key=SecretStr(""), deepseek_model="deepseek-synthetic"
        )
    )
    assert report["status"] == "skipped"
    assert report["network_status"] == "not_attempted"
    assert report["reason"] == "DEEPSEEK_NOT_CONFIGURED"
    assert report["fixed_gate_impact"] == "none"


def configured_settings() -> DeepSeekSettings:
    return DeepSeekSettings(
        deepseek_api_key=SecretStr("synthetic-secret"),
        deepseek_model="deepseek-synthetic",
    )


def valid_deepseek_outputs() -> dict[str, dict[str, object]]:
    return {
        "T607-DS-PLAN-001": {
            "schema_version": "agent-plan-v1",
            "intent": "order_query",
            "requested_capability": "order.get_authorized",
            "extracted_parameters": {
                "order_id": "ORD-NORMAL-001",
                "return_reason": None,
                "item_condition": None,
            },
            "clarification_fields": [],
            "uncertainty_reason": None,
        },
        "T607-DS-DRAFT-001": {
            "schema_version": "agent-response-draft-v1",
            "text": "synthetic grounded order response",
            "claims": [
                {
                    "claim_type": "order",
                    "evidence_ids": ["EVD-SYNTHETIC-ORDER-001"],
                }
            ],
        },
    }


def test_valid_plan_and_grounded_draft_pass_deepseek_supplement_contract() -> None:
    report = run_deepseek_supplement(
        settings=configured_settings(), gateway=FakeModelGateway(valid_deepseek_outputs())
    )
    assert report["status"] == "completed" and report["network_status"] == "available"
    assert [case["passed"] for case in report["cases"]] == [True, True]
    for case in report["cases"]:
        assert case["prompt_version"]
        assert case["model_identifier"] == "deepseek-synthetic"
        assert case["config_version"]
        assert case["dataset_version"] == "1.0.0"
        assert case["duration_ms"] >= 0
        assert case["network_status"] == "available"
        assert case["failure_reason"] is None


def test_unknown_draft_evidence_is_invalid_and_never_passes() -> None:
    outputs = valid_deepseek_outputs()
    draft = dict(outputs["T607-DS-DRAFT-001"])
    draft["claims"] = [{"claim_type": "order", "evidence_ids": ["EVD-UNKNOWN"]}]
    outputs["T607-DS-DRAFT-001"] = draft
    report = run_deepseek_supplement(
        settings=configured_settings(), gateway=FakeModelGateway(outputs)
    )
    result = next(case for case in report["cases"] if case["case_id"] == "T607-DS-DRAFT-001")
    assert result["status"] == "invalid_output"
    assert result["passed"] is False
    assert result["failure_reason"] == "INVALID_STRUCTURED_OUTPUT"


class UnavailableGateway:
    def generate(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(
            status=ModelResultStatus.UNAVAILABLE,
            task=request.task,
            output=None,
            error_code="SYNTHETIC_UNAVAILABLE",
            message="synthetic unavailable",
        )


class ProviderFailureGateway:
    def generate(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(
            status=ModelResultStatus.PROVIDER_FAILURE,
            task=request.task,
            output=None,
            error_code="SYNTHETIC_PROVIDER_FAILURE",
            message="synthetic provider failure",
        )


def test_provider_unavailable_cases_never_pass() -> None:
    report = run_deepseek_supplement(settings=configured_settings(), gateway=UnavailableGateway())
    assert report["status"] == "blocked"
    assert all(case["status"] == "unavailable" for case in report["cases"])
    assert all(case["passed"] is False for case in report["cases"])
    assert all(case["failure_reason"] == "PROVIDER_UNAVAILABLE" for case in report["cases"])


def test_provider_failure_cases_are_blocked_and_never_pass() -> None:
    report = run_deepseek_supplement(
        settings=configured_settings(), gateway=ProviderFailureGateway()
    )
    assert report["status"] == "blocked" and report["network_status"] == "unavailable"
    assert all(case["status"] == "provider_failure" for case in report["cases"])
    assert all(case["passed"] is False for case in report["cases"])
    assert all(case["failure_reason"] == "PROVIDER_FAILURE" for case in report["cases"])
