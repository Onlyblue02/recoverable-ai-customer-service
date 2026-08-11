from typing import Any

from customer_service.agent_http.evaluation import (
    report_outcome_is_consistent,
    run_deepseek_http_evaluation,
    verify_report_workspace_identity,
)
from customer_service.infrastructure.config.settings import DeepSeekSettings


def test_unconfigured_real_http_evaluation_is_skipped_and_never_counted_passed() -> None:
    report = run_deepseek_http_evaluation(
        DeepSeekSettings(deepseek_api_key=None, deepseek_model=None)
    )
    assert report["status"] == "SKIPPED"
    assert report["passed"] == 0
    assert report["total"] == 4
    assert all(case["status"] == "SKIPPED" for case in report["cases"])
    assert all(case["passed"] is False for case in report["cases"])


def test_report_contract_has_auditable_metadata_and_no_secret_fields() -> None:
    report: dict[str, Any] = run_deepseek_http_evaluation(
        DeepSeekSettings(deepseek_api_key=None, deepseek_model=None)
    )
    assert {
        "report_version",
        "executed_at",
        "model",
        "config_version",
        "plan_prompt",
        "response_prompt",
        "dataset_version",
        "git_revision",
        "workspace_state",
        "workspace_manifest",
        "workspace_digest",
        "environment_label",
        "status",
        "cases",
    } <= set(report)
    assert {case["case_id"] for case in report["cases"]} == {
        "T608-DS-HTTP-POLICY",
        "T608-DS-HTTP-LOW-RISK",
        "T608-DS-HTTP-HIGH-RISK",
        "T608-DS-HTTP-ADVERSARIAL",
    }
    per_case_metadata = {
        "executed_at",
        "model",
        "config_version",
        "timeout_seconds",
        "plan_prompt",
        "response_prompt",
        "dataset_version",
        "git_revision",
        "workspace_state",
        "workspace_digest",
        "environment_label",
        "duration_ms",
        "network_status",
        "failure_reason",
    }
    assert all(per_case_metadata <= set(case) for case in report["cases"])
    serialized = str(report).lower()
    assert "api_key" not in serialized
    assert "authorization" not in serialized
    assert "permit" not in serialized
    assert verify_report_workspace_identity(report)
    assert report_outcome_is_consistent(report)


def test_report_rejects_missing_or_tampered_workspace_manifest() -> None:
    report = run_deepseek_http_evaluation(
        DeepSeekSettings(deepseek_api_key=None, deepseek_model=None)
    )
    missing = {**report}
    missing.pop("workspace_manifest")
    assert verify_report_workspace_identity(missing) is False

    tampered = {**report, "workspace_manifest": [*report["workspace_manifest"]]}
    tampered["workspace_manifest"][0] = {
        **tampered["workspace_manifest"][0],
        "sha256": "0" * 64,
    }
    assert verify_report_workspace_identity(tampered) is False


def test_blocked_or_skipped_case_cannot_be_relabelled_as_current_pass() -> None:
    report = run_deepseek_http_evaluation(
        DeepSeekSettings(deepseek_api_key=None, deepseek_model=None)
    )
    forged = {**report, "status": "PASSED", "passed": 4}
    forged["cases"] = [{**case, "passed": True} for case in report["cases"]]
    assert report_outcome_is_consistent(forged) is False
