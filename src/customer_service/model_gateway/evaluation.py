"""Explicit, opt-in T-204 model evaluation over synthetic representative cases."""

import argparse
import json
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from customer_service.infrastructure.config.settings import DeepSeekSettings
from customer_service.model_gateway.deepseek import DeepSeekModelGateway
from customer_service.model_gateway.gateway import ModelGateway
from customer_service.model_gateway.schemas import (
    EvidenceSnippet,
    ModelRequest,
    ModelResultStatus,
    ModelTask,
)


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    request: ModelRequest
    expected: dict[str, Any]


def load_cases(path: Path) -> tuple[str, tuple[EvaluationCase, ...]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    dataset_version = str(document["dataset_version"])
    cases = tuple(
        EvaluationCase(
            case_id=str(case["case_id"]),
            request=ModelRequest(
                case_id=str(case["case_id"]),
                task=ModelTask(case["task"]),
                text=str(case["text"]),
                prompt_version=str(case["prompt_version"]),
                evidence=tuple(
                    EvidenceSnippet.model_validate(evidence)
                    for evidence in case.get("evidence", [])
                ),
            ),
            expected=dict(case["expected"]),
        )
        for case in document["cases"]
    )
    return dataset_version, cases


def run_evaluation(
    gateway: ModelGateway,
    *,
    cases_path: Path,
    model_identifier: str,
    config_version: str,
    code_identity: dict[str, str] | None = None,
) -> dict[str, Any]:
    dataset_version, cases = load_cases(cases_path)
    identity = code_identity or _code_identity()
    results: list[dict[str, Any]] = []
    for case in cases:
        started = time.perf_counter()
        response = gateway.generate(case.request)
        actual = response.output.model_dump(mode="json") if response.output is not None else None
        passed = _matches_expected(case, actual, response.status)
        results.append(
            {
                "case_id": case.case_id,
                "task": case.request.task.value,
                "prompt_version": case.request.prompt_version,
                "status": response.status.value,
                "passed": passed,
                "actual": actual,
                "duration_ms": round((time.perf_counter() - started) * 1000),
                "failure_reason": _failure_reason(response.status, passed),
            }
        )
    return {
        "evaluation_kind": "t204_deepseek_representative",
        "dataset_version": dataset_version,
        "model_identifier": model_identifier,
        "config_version": config_version,
        "code_version": identity["code_version"],
        "workspace_state": identity["workspace_state"],
        "executed_at": datetime.now(UTC).isoformat(),
        "cases": results,
        "passed": sum(1 for result in results if result["passed"]),
        "total": len(results),
    }


def _code_identity() -> dict[str, str]:
    root = Path(__file__).parents[3]
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return {"code_version": "unavailable", "workspace_state": "unavailable"}
    return {
        "code_version": revision or "unavailable",
        "workspace_state": "dirty" if status else "clean",
    }


def _matches_expected(
    case: EvaluationCase, actual: dict[str, Any] | None, status: ModelResultStatus
) -> bool:
    allowed_statuses = {
        ModelResultStatus(value) for value in case.expected.get("allowed_statuses", ["succeeded"])
    }
    if status not in allowed_statuses:
        return False
    if status is not ModelResultStatus.SUCCEEDED:
        return True
    if actual is None:
        return False
    if case.request.task is ModelTask.AGENT_RESPONSE_DRAFT_GENERATION:
        allowed_claim_types = set(case.expected.get("allowed_claim_types", []))
        trusted_ids = {evidence.evidence_id for evidence in case.request.evidence}
        expected_ids = set(case.expected.get("evidence_ids", trusted_ids))
        claims = actual.get("claims")
        if not isinstance(claims, list):
            return False
        referenced_ids: set[str] = set()
        for claim in claims:
            if not isinstance(claim, dict):
                return False
            if allowed_claim_types and claim.get("claim_type") not in allowed_claim_types:
                return False
            evidence_ids = claim.get("evidence_ids")
            if not isinstance(evidence_ids, list) or not all(
                isinstance(evidence_id, str) for evidence_id in evidence_ids
            ):
                return False
            referenced_ids.update(evidence_ids)
        forbidden_fields = set(case.expected.get("forbidden_fields", []))
        return (
            actual.get("schema_version") == case.expected.get("schema_version")
            and referenced_ids.issubset(trusted_ids)
            and referenced_ids == expected_ids
            and not forbidden_fields.intersection(actual)
        )
    if case.request.task is not ModelTask.GROUNDED_RESPONSE_GENERATION:
        return actual == case.expected
    expected_ids = case.expected["evidence_ids"]
    required_text = case.expected.get("text_must_include", [])
    required_any_groups = case.expected.get("text_must_include_any", [])
    prohibited_text = case.expected.get("text_must_not_include", [])
    text = str(actual.get("text", ""))
    return (
        actual.get("evidence_ids") == expected_ids
        and all(term in text for term in required_text)
        and all(any(term in text for term in group) for group in required_any_groups)
        and all(term not in text for term in prohibited_text)
    )


def _failure_reason(status: ModelResultStatus, passed: bool) -> str | None:
    if passed:
        return None
    return {
        ModelResultStatus.INVALID_OUTPUT: "INVALID_STRUCTURED_OUTPUT",
        ModelResultStatus.PROVIDER_FAILURE: "PROVIDER_FAILURE",
        ModelResultStatus.UNAVAILABLE: "PROVIDER_UNAVAILABLE",
        ModelResultStatus.SUCCEEDED: "EXPECTED_RESULT_MISMATCH",
    }[status]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the opt-in T-204 DeepSeek evaluation.")
    parser.add_argument(
        "--cases",
        type=Path,
        default=Path("data/evaluation/model_gateway/cases.v1.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/evaluations/t204-deepseek.json"),
    )
    args = parser.parse_args()
    settings = DeepSeekSettings()
    if not settings.is_configured:
        print("SKIPPED: set DEEPSEEK_API_KEY and DEEPSEEK_MODEL before running the evaluation.")
        return 0
    report = run_evaluation(
        DeepSeekModelGateway(settings),
        cases_path=args.cases,
        model_identifier=settings.deepseek_model or "",
        config_version=settings.deepseek_config_version,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"WROTE: {args.output} ({report['passed']}/{report['total']} passed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
