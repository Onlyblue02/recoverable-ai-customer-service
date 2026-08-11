"""Run a small, repeatable public-path acceptance report over synthetic fixtures."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from fastapi.testclient import TestClient

from customer_service.approvals.schemas import (
    ApprovalActorContext,
    ApprovalDecision,
    ApprovalDecisionRequest,
)
from customer_service.approvals.service import ApprovalTaskService
from customer_service.main import create_app
from customer_service.recovery.repository import InMemoryRecoveryCheckpointRepository
from customer_service.recovery.schemas import RecoveryAccessContext, RecoveryCheckpointRequest
from customer_service.recovery.service import ApprovalRecoveryService
from customer_service.response_gate.schemas import (
    ResponseDraft,
    ResponseEvidenceContext,
    ResponseGateAction,
)
from customer_service.response_gate.service import ResponseGateService
from customer_service.service_cases.repository import InMemoryServiceCaseRepository
from customer_service.service_cases.service import ServiceCaseService

ROOT = Path(__file__).parents[3]
DATA_ROOT = ROOT / "data"
FAILURE_CASES_PATH = DATA_ROOT / "evaluation" / "failures" / "cases.v1.json"


@dataclass(frozen=True)
class AcceptanceResult:
    case_id: str
    capability: str
    dataset_version: str
    code_version: str
    run_id: str
    executed_at: str
    duration_ms: int
    prompt_version: str
    model_identifier: str
    model_mode: str
    expected: dict[str, Any]
    actual: dict[str, Any]
    passed: bool
    status: str
    failure_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "capability": self.capability,
            "dataset_version": self.dataset_version,
            "code_version": self.code_version,
            "run_id": self.run_id,
            "executed_at": self.executed_at,
            "duration_ms": self.duration_ms,
            "prompt_version": self.prompt_version,
            "model_identifier": self.model_identifier,
            "model_mode": self.model_mode,
            "expected": self.expected,
            "actual": self.actual,
            "passed": self.passed,
            "status": self.status,
            "failure_reason": self.failure_reason,
        }


def run_fixed_acceptance() -> dict[str, Any]:
    """Run representative T-002 cases through the public consumer/approval paths."""

    client = TestClient(create_app())
    identity = _code_identity()
    run_id = str(uuid4())
    executed_at = datetime.now(UTC).isoformat()
    metadata = {
        "dataset_version": "1.0.0",
        "code_version": identity["code_version"],
        "run_id": run_id,
        "executed_at": executed_at,
    }
    results = (
        _execute(_policy_case, client, metadata),
        _execute(_authorized_order_case, client, metadata),
        _execute(_unavailable_order_case, client, metadata),
        _execute(_standard_return_case, client, metadata),
        _execute(_high_risk_return_case, client, metadata),
        _execute(_checkpoint_import_recovery_case, client, metadata),
        _execute(_ungrounded_policy_gate_case, client, metadata),
        _execute(_false_completion_gate_case, client, metadata),
        _execute(_approval_bypass_gate_case, client, metadata),
        _execute(_payload_boundary_case, client, metadata),
    )
    failures = _load_preserved_failures(FAILURE_CASES_PATH)
    return {
        "report_kind": "t403_fixed_acceptance",
        "report_version": "1.0.0",
        "evaluation_version": "1.0.0",
        "dataset_version": "1.0.0",
        "reference_date": "2026-07-20",
        "code_version": identity["code_version"],
        "workspace_state": identity["workspace_state"],
        "run_id": run_id,
        "executed_at": executed_at,
        "cases": [result.as_dict() for result in results],
        "passed": sum(result.passed for result in results),
        "total": len(results),
        "preserved_failures": failures,
    }


def stable_projection(report: dict[str, Any]) -> dict[str, Any]:
    """Remove run metadata so two identical synthetic runs can be compared."""

    return {
        "evaluation_version": report["evaluation_version"],
        "dataset_version": report["dataset_version"],
        "cases": [
            {
                key: value
                for key, value in case.items()
                if key not in {"run_id", "executed_at", "duration_ms", "code_version"}
            }
            for case in report["cases"]
        ],
        "passed": report["passed"],
        "total": report["total"],
        "preserved_failures": report["preserved_failures"],
    }


def _execute(
    case: Callable[[TestClient], AcceptanceResult], client: TestClient, metadata: dict[str, str]
) -> AcceptanceResult:
    started = time.perf_counter()
    result = case(client)
    return replace(
        result,
        duration_ms=round((time.perf_counter() - started) * 1000),
        dataset_version=metadata["dataset_version"],
        code_version=metadata["code_version"],
        run_id=metadata["run_id"],
        executed_at=metadata["executed_at"],
    )


def _policy_case(client: TestClient) -> AcceptanceResult:
    body = _send(client, "我想了解退货政策")
    citation_ids = [citation["policy_id"] for citation in body["citations"]]
    actual = {"status": body["agent_status"], "citation_ids": citation_ids}
    expected = {
        "status": "completed",
        "citation_ids": ["POL-ACTIVE-STANDARD-001"],
    }
    return _result("AC-FR03-N-001", "policy", expected, actual)


def _authorized_order_case(client: TestClient) -> AcceptanceResult:
    body = _send(client, "查询订单 ORD-NORMAL-001")
    actual = {
        "status": body["agent_status"],
        "authorized_order_visible": "ORD-NORMAL-001" in body["message"],
    }
    expected = {
        "status": "completed",
        "authorized_order_visible": True,
    }
    return _result("AC-FR04-N-001", "order", expected, actual)


def _unavailable_order_case(client: TestClient) -> AcceptanceResult:
    missing = _send(client, "查询订单 ORD-NOT-FOUND-001")
    unauthorized = _send(client, "查询订单 ORD-OTHER-USER-001")
    actual = {
        "missing_status": missing["agent_status"],
        "unauthorized_status": unauthorized["agent_status"],
        "same_message": missing["message"] == unauthorized["message"],
        "orders_absent": "ORD-" not in missing["message"] and "ORD-" not in unauthorized["message"],
    }
    expected = {
        "missing_status": "failed_safe",
        "unauthorized_status": "failed_safe",
        "same_message": True,
        "orders_absent": True,
    }
    return _result("AC-FR04-E-002", "security_boundary", expected, actual)


def _standard_return_case(client: TestClient) -> AcceptanceResult:
    conversation_id = _new_conversation(client)
    _post(client, conversation_id, "我要退货，订单号是 ORD-NORMAL-001")
    _post(client, conversation_id, "我不想要了")
    completed = _post(client, conversation_id, "商品未使用，包装完整")
    repeated = _post(client, conversation_id, "商品未使用，包装完整")
    actual = {
        "status": completed["agent_status"],
        "has_service_case": completed["service_case_id"] is not None,
        "same_service_case_on_repeat": completed["service_case_id"] == repeated["service_case_id"],
        "citation_ids": [citation["policy_id"] for citation in completed["citations"]],
    }
    expected = {
        "status": "completed",
        "has_service_case": True,
        "same_service_case_on_repeat": True,
        "citation_ids": ["POL-ACTIVE-STANDARD-001"],
    }
    return _result("E2E-STANDARD-001", "standard_return_and_rules", expected, actual)


def _high_risk_return_case(client: TestClient) -> AcceptanceResult:
    conversation_id = _new_conversation(client)
    _post(client, conversation_id, "我要退货，订单号是 ORD-HIGH-VALUE-001")
    _post(client, conversation_id, "我不想要了")
    waiting = _post(client, conversation_id, "商品未使用，包装完整")
    task = client.get("/api/v1/approvals").json()[-1]
    decision = client.post(
        f"/api/v1/approvals/{task['approval_id']}/decisions",
        json={"decision": "approve", "note": "已核验。", "expected_version": task["version"]},
    )
    restored = client.get(f"/api/v1/conversations/{conversation_id}").json()
    actual = {
        "waiting_status": waiting["agent_status"],
        "approval_status": decision.json().get("status") if decision.status_code == 200 else None,
        "restored_status": restored["agent_status"],
        "has_service_case": restored["service_case_id"] is not None,
    }
    expected = {
        "waiting_status": "waiting_approval",
        "approval_status": "approved",
        "restored_status": "completed",
        "has_service_case": True,
    }
    return _result("E2E-HIGH-RISK-001", "high_risk_recovery", expected, actual)


def _checkpoint_import_recovery_case(client: TestClient) -> AcceptanceResult:
    evidence, case_count = _recover_after_checkpoint_import(client)
    actual = {
        "approval_status": evidence.approval.status.value if evidence.approval else None,
        "has_service_case": evidence.service_case is not None,
        "service_cases_created": case_count,
    }
    expected = {
        "approval_status": "approved",
        "has_service_case": True,
        "service_cases_created": 1,
    }
    return _result("AC-FR11-N-001", "checkpoint_export_import_recovery", expected, actual)


def _ungrounded_policy_gate_case(client: TestClient) -> AcceptanceResult:
    evidence, _ = _recover_after_checkpoint_import(client)
    citation = evidence.policy_citations[0]
    forged = citation.model_copy(update={"source": "fake://policy"})
    result = ResponseGateService().evaluate(
        ResponseDraft(
            message="伪造政策允许退货。",
            policy_citations=(forged,),
            claims_policy_conclusion=True,
        ),
        evidence=evidence,
    )
    actual = {"action": result.action.value, "response_exposed": result.response is not None}
    expected = {"action": ResponseGateAction.CLARIFY.value, "response_exposed": False}
    return _result("AC-FR03-E-003", "ungrounded_answer_gate", expected, actual)


def _false_completion_gate_case(client: TestClient) -> AcceptanceResult:
    evidence, _ = _recover_after_checkpoint_import(client)
    result = ResponseGateService().evaluate(
        ResponseDraft(message="申请已完成，编号 SC-FAKE-999。"),
        evidence=evidence.model_copy(update={"service_case": None}),
    )
    actual = {"action": result.action.value, "response_exposed": result.response is not None}
    expected = {"action": ResponseGateAction.ESCALATE.value, "response_exposed": False}
    return _result("AC-FR09-E-002", "false_completion_gate", expected, actual)


def _approval_bypass_gate_case(client: TestClient) -> AcceptanceResult:
    evidence, _ = _recover_after_checkpoint_import(client)
    assert evidence.service_case is not None
    result = ResponseGateService().evaluate(
        ResponseDraft(
            message="申请已完成。",
            policy_citations=evidence.policy_citations,
            order=evidence.order,
            eligibility=evidence.eligibility,
            service_case=evidence.service_case,
            claims_policy_conclusion=True,
            claims_order_facts=True,
            claims_eligibility=True,
            claims_completion=True,
        ),
        evidence=evidence.model_copy(update={"approval": None}),
    )
    actual = {"action": result.action.value, "response_exposed": result.response is not None}
    expected = {"action": ResponseGateAction.ESCALATE.value, "response_exposed": False}
    return _result("AC-FR08-E-003", "approval_bypass_gate", expected, actual)


def _payload_boundary_case(client: TestClient) -> AcceptanceResult:
    conversation_id = _new_conversation(client)
    response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"message": "我要退货", "current_user_id": "USR-DEMO-002"},
    )
    actual = {"http_status": response.status_code}
    expected = {"http_status": 422}
    return _result("AC-FR04-E-003", "security_boundary", expected, actual)


def _recover_after_checkpoint_import(
    client: TestClient,
) -> tuple[ResponseEvidenceContext, int]:
    conversation_id = _new_conversation(client)
    _post(client, conversation_id, "我要退货，订单号是 ORD-HIGH-VALUE-001")
    _post(client, conversation_id, "我不想要了")
    _post(client, conversation_id, "商品未使用，包装完整")
    task_summary = client.get("/api/v1/approvals").json()[-1]
    workflow_id = f"T403-{conversation_id}"
    cases = InMemoryServiceCaseRepository()
    checkpoint_repository = InMemoryRecoveryCheckpointRepository()
    repository = cast(Any, client.app).state.agent_application.approval_repository
    source = ApprovalRecoveryService(
        checkpoint_repository,
        approvals=repository,
        service_cases=ServiceCaseService(cases),
    )
    checkpoint = source.checkpoint(
        RecoveryCheckpointRequest(workflow_id=workflow_id, approval_id=task_summary["approval_id"]),
        context=RecoveryAccessContext(current_user_id="USR-DEMO-001"),
    )
    exported = checkpoint_repository.export()
    ApprovalTaskService(repository).decide(
        task_summary["approval_id"],
        ApprovalDecisionRequest(
            decision=ApprovalDecision.APPROVE,
            note="验收批准。",
            expected_version=task_summary["version"],
        ),
        actor_context=ApprovalActorContext(actor_id="USR-AGENT-001"),
    )
    restored = ApprovalRecoveryService(
        InMemoryRecoveryCheckpointRepository(exported),
        approvals=repository,
        service_cases=ServiceCaseService(cases),
    ).recover(workflow_id, context=RecoveryAccessContext(current_user_id="USR-DEMO-001"))
    if checkpoint.approval is None or restored.approval is None or restored.service_case is None:
        raise RuntimeError("checkpoint import recovery failed")
    return (
        ResponseEvidenceContext(
            policy_citations=restored.approval.policy_citations,
            current_user_id="USR-DEMO-001",
            order=restored.approval.order,
            eligibility=restored.approval.eligibility,
            service_case=restored.service_case,
            approval=restored.approval,
        ),
        cases.case_count,
    )


def _new_conversation(client: TestClient) -> str:
    response = client.post("/api/v1/conversations")
    if response.status_code != 200:
        raise RuntimeError("conversation creation failed")
    return str(response.json()["conversation_id"])


def _post(client: TestClient, conversation_id: str, message: str) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"message": message},
        headers={"Idempotency-Key": str(uuid4())},
    )
    if response.status_code != 200:
        raise RuntimeError("conversation message failed")
    return dict(response.json())


def _send(client: TestClient, message: str) -> dict[str, Any]:
    return _post(client, _new_conversation(client), message)


def _result(
    case_id: str, capability: str, expected: dict[str, Any], actual: dict[str, Any]
) -> AcceptanceResult:
    passed = expected == actual
    return AcceptanceResult(
        case_id=case_id,
        capability=capability,
        dataset_version="",
        code_version="",
        run_id="",
        executed_at="",
        duration_ms=0,
        prompt_version="not_applicable",
        model_identifier="none",
        model_mode="deterministic",
        expected=expected,
        actual=actual,
        passed=passed,
        status="passed" if passed else "failed",
        failure_reason=None if passed else "ACTUAL_RESULT_MISMATCH",
    )


def _load_preserved_failures(path: Path) -> list[dict[str, Any]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    return [_validate_failure_source(dict(failure)) for failure in document["failures"]]


def _validate_failure_source(failure: dict[str, Any]) -> dict[str, Any]:
    source_path = ROOT / str(failure["source"])
    if not source_path.is_file():
        return _evidence_unavailable(failure, "SOURCE_REPORT_MISSING")
    actual_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
    if actual_hash != failure["source_sha256"]:
        return _evidence_unavailable(failure, "SOURCE_REPORT_HASH_MISMATCH")
    source = json.loads(source_path.read_text(encoding="utf-8"))
    case = next(
        (item for item in source.get("cases", []) if item.get("case_id") == failure["failure_id"]),
        None,
    )
    summary = failure["source_summary"]
    if case is None or any(
        case.get(key) != summary[key] for key in ("prompt_version", "status", "passed")
    ):
        return _evidence_unavailable(failure, "SOURCE_CASE_MISMATCH")
    if any(
        source.get(key) != summary[key]
        for key in ("dataset_version", "model_identifier", "config_version", "code_version")
    ):
        return _evidence_unavailable(failure, "SOURCE_METADATA_MISMATCH")
    return failure


def _evidence_unavailable(failure: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        **failure,
        "status": "evidence_unavailable",
        "failure_reason": reason,
        "improvement_suggestion": (
            "Restore or re-run the source evaluation before citing this as real failure evidence."
        ),
    }


def _code_identity() -> dict[str, str]:
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        state = subprocess.run(
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
        "workspace_state": "dirty" if state else "clean",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the T-403 fixed acceptance report.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/evaluations/t403-fixed-acceptance.json"),
    )
    args = parser.parse_args()
    report = run_fixed_acceptance()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"WROTE: {args.output} ({report['passed']}/{report['total']} passed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
