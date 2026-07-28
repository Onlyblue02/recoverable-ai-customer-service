import json
from pathlib import Path

import pytest

from customer_service.acceptance_reporting import runner
from customer_service.acceptance_reporting.runner import run_fixed_acceptance, stable_projection


def test_fixed_acceptance_report_covers_required_capabilities_and_is_repeatable() -> None:
    first = run_fixed_acceptance()
    second = run_fixed_acceptance()

    assert first["evaluation_version"] == "1.0.0"
    assert first["dataset_version"] == "1.0.0"
    assert first["passed"] == 10
    assert first["total"] == 10
    assert all(case["passed"] for case in first["cases"])
    assert {
        "policy",
        "order",
        "standard_return_and_rules",
        "high_risk_recovery",
        "checkpoint_export_import_recovery",
        "ungrounded_answer_gate",
        "false_completion_gate",
        "approval_bypass_gate",
        "security_boundary",
    } <= {case["capability"] for case in first["cases"]}
    required_metadata = {
        "dataset_version",
        "code_version",
        "run_id",
        "executed_at",
        "duration_ms",
        "prompt_version",
        "model_identifier",
        "model_mode",
        "expected",
        "actual",
        "passed",
        "status",
        "failure_reason",
    }
    assert all(required_metadata <= set(case) for case in first["cases"])
    assert all(case["model_mode"] == "deterministic" for case in first["cases"])
    assert all(case["prompt_version"] == "not_applicable" for case in first["cases"])
    assert stable_projection(first) == stable_projection(second)


def test_report_preserves_a_real_failure_with_reason_and_improvement() -> None:
    report = run_fixed_acceptance()

    failure = report["preserved_failures"][0]
    assert failure["failure_id"] == "T204-T203-GROUNDED-REWRITE-001"
    assert failure["source"] == "reports/evaluations/t204-deepseek.json"
    assert failure["status"] == "failed"
    assert failure["prompt_version"] == "t204-grounded-v1"
    assert failure["config_version"] == "1"
    assert failure["code_version"] == "e0aba799803ebed425ec1f605fb0bd40c690108d"
    assert failure["failure_reason"] == "LIMITED_REWRITE_SYNONYM_COVERAGE"
    assert "Expand" in failure["improvement_suggestion"]


@pytest.mark.parametrize(
    ("mutation", "expected_reason"),
    (("hash", "SOURCE_REPORT_HASH_MISMATCH"), ("source", "SOURCE_REPORT_MISSING")),
)
def test_missing_or_drifted_failure_evidence_is_not_reported_as_real_failure(
    mutation: str,
    expected_reason: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    document = json.loads(runner.FAILURE_CASES_PATH.read_text(encoding="utf-8"))
    if mutation == "hash":
        document["failures"][0]["source_sha256"] = "0" * 64
    else:
        document["failures"][0]["source"] = "reports/evaluations/missing.json"
    fixture = tmp_path / "failures.json"
    fixture.write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setattr(runner, "FAILURE_CASES_PATH", fixture)

    report = run_fixed_acceptance()

    failure = report["preserved_failures"][0]
    assert failure["status"] == "evidence_unavailable"
    assert failure["failure_reason"] == expected_reason
    assert "Restore or re-run" in failure["improvement_suggestion"]
