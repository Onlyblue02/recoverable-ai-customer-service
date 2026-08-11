"""Versioned, repeatable T-607 acceptance runner over synthetic pytest scenarios."""

import argparse
import json
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from customer_service.acceptance_reporting.runner import _load_preserved_failures
from customer_service.infrastructure.config.settings import DeepSeekSettings
from customer_service.model_gateway.deepseek import DeepSeekModelGateway
from customer_service.model_gateway.evaluation import run_evaluation
from customer_service.model_gateway.gateway import ModelGateway

ROOT = Path(__file__).parents[3]
DEFAULT_CASES = ROOT / "data" / "evaluation" / "agent_mvp" / "cases.v1.json"
DEFAULT_DEEPSEEK_CASES = ROOT / "data" / "evaluation" / "agent_mvp" / "deepseek-cases.v1.json"
FAILURES = ROOT / "data" / "evaluation" / "failures" / "cases.v1.json"

CaseExecutor = Callable[[str], int]


def load_cases(path: Path = DEFAULT_CASES) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("agent acceptance document must be an object")
    return document


def run_fixed_acceptance(
    *, cases_path: Path = DEFAULT_CASES, executor: CaseExecutor | None = None
) -> dict[str, Any]:
    document = load_cases(cases_path)
    execute = executor or _run_pytest_case
    identity = _code_identity()
    results: list[dict[str, Any]] = []
    for case in document["cases"]:
        requirement, expected_security_outcome = _acceptance_contract(document, case["case_id"])
        started = time.perf_counter()
        exit_code = execute(str(case["nodeid"]))
        passed = exit_code == 0
        results.append(
            {
                "case_id": case["case_id"],
                "category": case["category"],
                "stage": case["stage"],
                "capability": case["capability"],
                "acceptance_requirement": requirement,
                "expected": {
                    "pytest_exit_code": 0,
                    "terminal_status": "passed",
                    "security_outcome": expected_security_outcome,
                },
                "actual": {
                    "pytest_exit_code": exit_code,
                    "terminal_status": "passed" if passed else "failed",
                    "security_outcome": (
                        expected_security_outcome if passed else "ASSERTION_FAILED"
                    ),
                },
                "passed": passed,
                "status": "passed" if passed else "failed",
                "failure_reason": None if passed else f"{case['stage'].upper()}_ASSERTION_FAILED",
                "audit_ref": {
                    "case_id": case["case_id"],
                    "stage": case["stage"],
                    "nodeid": case["nodeid"],
                },
                "duration_ms": round((time.perf_counter() - started) * 1000),
            }
        )
    return {
        "report_kind": "t607_agent_mvp_fixed_acceptance",
        "report_version": "1.0.0",
        "suite_version": document["suite_version"],
        "dataset_version": document["dataset_version"],
        "model_mode": "fake-deterministic",
        "code_version": identity["code_version"],
        "workspace_state": identity["workspace_state"],
        "run_id": str(uuid4()),
        "executed_at": datetime.now(UTC).isoformat(),
        "cases": results,
        "passed": sum(result["passed"] for result in results),
        "failed": sum(not result["passed"] for result in results),
        "total": len(results),
        "preserved_failures": _load_preserved_failures(FAILURES),
    }


def _acceptance_contract(document: dict[str, Any], case_id: str) -> tuple[str, str]:
    matches = [
        (requirement, str(contract["expected_security_outcome"]))
        for requirement, contract in document["acceptance_contract"].items()
        if case_id in contract["case_ids"]
    ]
    if len(matches) != 1:
        raise ValueError(f"case {case_id} must map to exactly one acceptance requirement")
    return matches[0]


def stable_projection(report: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in report.items()
        if key not in {"run_id", "executed_at", "code_version", "workspace_state", "cases"}
    } | {
        "cases": [
            {key: value for key, value in case.items() if key != "duration_ms"}
            for case in report["cases"]
        ]
    }


def run_deepseek_supplement(
    *,
    cases_path: Path = DEFAULT_DEEPSEEK_CASES,
    settings: DeepSeekSettings | None = None,
    gateway: ModelGateway | None = None,
) -> dict[str, Any]:
    settings = settings or DeepSeekSettings()
    base = {
        "report_kind": "t607_deepseek_supplement",
        "report_version": "1.0.0",
        "dataset_version": str(load_cases(cases_path)["dataset_version"]),
        "model_identifier": settings.deepseek_model or "unconfigured",
        "config_version": settings.deepseek_config_version,
        "executed_at": datetime.now(UTC).isoformat(),
    }
    if not settings.is_configured:
        return {
            **base,
            "status": "skipped",
            "network_status": "not_attempted",
            "duration_ms": 0,
            "reason": "DEEPSEEK_NOT_CONFIGURED",
            "fixed_gate_impact": "none",
            "cases": [],
        }
    started = time.perf_counter()
    report = run_evaluation(
        gateway or DeepSeekModelGateway(settings),
        cases_path=cases_path,
        model_identifier=settings.deepseek_model or "",
        config_version=settings.deepseek_config_version,
    )
    provider_blocked = bool(report["cases"]) and all(
        case["status"] in {"provider_failure", "unavailable"} for case in report["cases"]
    )
    case_contracts = {case["case_id"]: case for case in load_cases(cases_path)["cases"]}
    cases = []
    for case in report["cases"]:
        contract = case_contracts[case["case_id"]]
        passed = bool(case["passed"]) and case["status"] == "succeeded"
        cases.append(
            {
                **case,
                "passed": passed,
                "failure_reason": case.get("failure_reason") if not passed else None,
                "prompt_version": contract["prompt_version"],
                "model_identifier": base["model_identifier"],
                "config_version": base["config_version"],
                "dataset_version": base["dataset_version"],
                "network_status": (
                    "unavailable"
                    if case["status"] in {"provider_failure", "unavailable"}
                    else "available"
                ),
            }
        )
    return {
        **base,
        "status": "blocked" if provider_blocked else "completed",
        "network_status": "unavailable" if provider_blocked else "available",
        "duration_ms": round((time.perf_counter() - started) * 1000),
        "reason": "DEEPSEEK_PROVIDER_UNAVAILABLE" if provider_blocked else None,
        "fixed_gate_impact": "none",
        "cases": cases,
    }


def _run_pytest_case(nodeid: str) -> int:
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", nodeid, "-q", "-p", "no:cacheprovider"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.returncode


def _code_identity() -> dict[str, str]:
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=ROOT,
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Run T-607 Agent MVP acceptance reporting.")
    parser.add_argument("--mode", choices=("fake", "deepseek"), default="fake")
    parser.add_argument(
        "--output", type=Path, default=Path("reports/evaluations/t607-agent-mvp.json")
    )
    args = parser.parse_args()
    report = run_fixed_acceptance() if args.mode == "fake" else run_deepseek_supplement()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"WROTE: {args.output} ({report.get('status', 'completed')})")
    return 0 if report.get("failed", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
