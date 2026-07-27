import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from customer_service.approvals.repository import InMemoryApprovalTaskRepository
from customer_service.approvals.schemas import ApprovalActorContext, ApprovalDecision
from customer_service.approvals.service import ApprovalTaskService
from customer_service.eligibility.config import EligibilityRuleConfig
from customer_service.eligibility.engine import EligibilityEngine
from customer_service.eligibility.schemas import ReturnReason
from customer_service.infrastructure.clients.mock_business import HttpOrderGateway
from customer_service.orchestration.high_risk_schemas import (
    HighRiskContext,
    HighRiskDecisionInput,
    HighRiskStartRequest,
    HighRiskWorkflowStatus,
)
from customer_service.orchestration.high_risk_service import HighRiskReturnWorkflowService
from customer_service.rag.catalog import PolicyCatalog
from customer_service.rag.service import PolicyAnswerService
from customer_service.recovery.repository import InMemoryRecoveryCheckpointRepository
from customer_service.recovery.service import ApprovalRecoveryService
from customer_service.response_gate.service import ResponseGateService
from customer_service.service_cases.repository import InMemoryServiceCaseRepository
from customer_service.service_cases.service import ServiceCaseService
from customer_service.tools.order_tool import OrderQueryService
from mock_business.main import create_app

ROOT = Path(__file__).parents[3]
DATA_ROOT = ROOT / "data"
CONFIG_PATH = ROOT / "config" / "return-eligibility-rules.v1.json"


def product_categories() -> dict[str, str]:
    document = json.loads(
        (DATA_ROOT / "seed" / "products" / "products.v1.json").read_text(encoding="utf-8")
    )
    return {
        str(product["product_id"]): str(product["category"]) for product in document["products"]
    }


def workflow(
    *,
    approvals: InMemoryApprovalTaskRepository | None = None,
    cases: InMemoryServiceCaseRepository | None = None,
    checkpoints: InMemoryRecoveryCheckpointRepository | None = None,
) -> tuple[
    HighRiskReturnWorkflowService,
    InMemoryServiceCaseRepository,
    InMemoryApprovalTaskRepository,
    InMemoryRecoveryCheckpointRepository,
]:
    catalog = PolicyCatalog.from_manifest(DATA_ROOT / "manifest.json")
    approvals = approvals or InMemoryApprovalTaskRepository()
    cases = cases or InMemoryServiceCaseRepository()
    checkpoints = checkpoints or InMemoryRecoveryCheckpointRepository()
    case_service = ServiceCaseService(cases)
    return (
        HighRiskReturnWorkflowService(
            orders=OrderQueryService(
                HttpOrderGateway(TestClient(create_app(manifest_path=DATA_ROOT / "manifest.json")))
            ),
            policies=PolicyAnswerService(catalog),
            policy_catalog=catalog,
            product_categories=product_categories(),
            eligibility=EligibilityEngine(EligibilityRuleConfig.from_json(CONFIG_PATH)),
            approvals=ApprovalTaskService(approvals),
            recovery=ApprovalRecoveryService(
                checkpoints, approvals=approvals, service_cases=case_service
            ),
            checkpoints=checkpoints,
            gate=ResponseGateService(),
        ),
        cases,
        approvals,
        checkpoints,
    )


def context() -> HighRiskContext:
    return HighRiskContext(
        workflow_id="WF-HIGH-001",
        current_user_id="USR-DEMO-001",
        order_id="ORD-HIGH-VALUE-001",
        return_reason=ReturnReason.CHANGED_MIND,
        item_condition="resalable",
    )


def test_high_risk_approved_story_creates_one_grounded_case() -> None:
    service, cases, _, _ = workflow()
    started = service.start(HighRiskStartRequest(message="高金额退货"), context=context())
    assert (
        started.status is HighRiskWorkflowStatus.WAITING_APPROVAL and started.approval is not None
    )
    completed = service.decide_and_resume(
        HighRiskDecisionInput(
            decision=ApprovalDecision.APPROVE,
            note="批准",
            expected_version=started.approval.version,
        ),
        context=context(),
        actor_context=ApprovalActorContext(actor_id="USR-AGENT-001"),
    )
    repeated = service.decide_and_resume(
        HighRiskDecisionInput(
            decision=ApprovalDecision.APPROVE,
            note="批准",
            expected_version=started.approval.version,
        ),
        context=context(),
        actor_context=ApprovalActorContext(actor_id="USR-AGENT-001"),
    )
    assert completed.status is HighRiskWorkflowStatus.COMPLETED
    assert completed.service_case is not None and completed.gate_action is not None
    assert completed.gate_action.value == "allow"
    assert repeated.status is HighRiskWorkflowStatus.COMPLETED and cases.case_count == 1


def test_adjust_and_reject_do_not_create_cases() -> None:
    for decision, recommendation, expected in (
        (ApprovalDecision.ADJUST, "补充商品照片", HighRiskWorkflowStatus.NEEDS_CLARIFICATION),
        (ApprovalDecision.REJECT, None, HighRiskWorkflowStatus.REJECTED),
    ):
        service, cases, _, _ = workflow()
        started = service.start(HighRiskStartRequest(message="高金额退货"), context=context())
        assert started.approval is not None
        result = service.decide_and_resume(
            HighRiskDecisionInput(
                decision=decision,
                note="人工处理",
                recommendation=recommendation,
                expected_version=started.approval.version,
            ),
            context=context(),
            actor_context=ApprovalActorContext(actor_id="USR-AGENT-001"),
        )
        assert result.status is expected and result.service_case is None and cases.case_count == 0


def test_decision_payload_rejects_forged_actor_and_uses_trusted_actor() -> None:
    with pytest.raises(ValueError):
        HighRiskDecisionInput.model_validate(
            {
                "decision": "approve",
                "note": "批准",
                "expected_version": 1,
                "actor_id": "USR-ADMIN-001",
            }
        )
    service, cases, _, _ = workflow()
    started = service.start(HighRiskStartRequest(message="高金额退货"), context=context())
    assert started.approval is not None
    completed = service.decide_and_resume(
        HighRiskDecisionInput(
            decision=ApprovalDecision.APPROVE,
            note="批准",
            expected_version=started.approval.version,
        ),
        context=context(),
        actor_context=ApprovalActorContext(actor_id="USR-AGENT-001"),
    )
    assert completed.approval is not None and completed.approval.decided_by == "USR-AGENT-001"
    assert cases.case_count == 1


@pytest.mark.parametrize(
    ("decision", "recommendation", "expected"),
    [
        (ApprovalDecision.APPROVE, None, HighRiskWorkflowStatus.COMPLETED),
        (ApprovalDecision.ADJUST, "补充商品照片", HighRiskWorkflowStatus.NEEDS_CLARIFICATION),
        (ApprovalDecision.REJECT, None, HighRiskWorkflowStatus.REJECTED),
    ],
)
def test_interrupted_high_risk_workflow_rebuilds_and_resumes(
    decision: ApprovalDecision, recommendation: str | None, expected: HighRiskWorkflowStatus
) -> None:
    first, cases, approvals, checkpoints = workflow()
    started = first.start(HighRiskStartRequest(message="高金额退货"), context=context())
    assert (
        started.status is HighRiskWorkflowStatus.WAITING_APPROVAL and started.approval is not None
    )
    restored_checkpoints = InMemoryRecoveryCheckpointRepository(checkpoints.export())
    restored, _, _, _ = workflow(approvals=approvals, cases=cases, checkpoints=restored_checkpoints)
    result = restored.decide_and_resume(
        HighRiskDecisionInput(
            decision=decision,
            note="人工处理",
            recommendation=recommendation,
            expected_version=started.approval.version,
        ),
        context=context(),
        actor_context=ApprovalActorContext(actor_id="USR-AGENT-001"),
    )
    repeat = restored.decide_and_resume(
        HighRiskDecisionInput(
            decision=decision,
            note="人工处理",
            recommendation=recommendation,
            expected_version=started.approval.version,
        ),
        context=context(),
        actor_context=ApprovalActorContext(actor_id="USR-AGENT-001"),
    )
    assert result.status is expected
    assert cases.case_count == (1 if expected is HighRiskWorkflowStatus.COMPLETED else 0)
    assert repeat.status is expected
