import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from customer_service.agent_response.schemas import AgentResponseOutcome
from customer_service.agent_response.service import AgentResponseService, EvidenceContextResolver
from customer_service.agent_runtime.executor import ControlledAgentExecutor
from customer_service.agent_runtime.schemas import AgentEventType, AgentStatus
from customer_service.agent_tools.execution import ControlledToolExecutor
from customer_service.agent_tools.schemas import (
    ParameterSource,
    PlanValidationContext,
    ToolId,
    TrustedParameter,
)
from customer_service.agent_tools.validator import ToolPlanValidator
from customer_service.approvals.repository import InMemoryApprovalTaskRepository
from customer_service.approvals.schemas import (
    ApprovalActorContext,
    ApprovalDecision,
    ApprovalDecisionRequest,
)
from customer_service.approvals.service import ApprovalTaskService
from customer_service.eligibility.config import EligibilityRuleConfig
from customer_service.eligibility.engine import EligibilityEngine
from customer_service.eligibility.schemas import ReturnReason
from customer_service.infrastructure.clients.mock_business import HttpOrderGateway
from customer_service.model_gateway.fake import FakeModelGateway
from customer_service.model_gateway.schemas import AgentPlanCandidate
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
    assert started.service_case is None and cases.case_count == 0
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


class FailingCheckpointRepository(InMemoryRecoveryCheckpointRepository):
    def save_if_absent(self, record):  # type: ignore[no-untyped-def]
        raise RuntimeError("checkpoint unavailable")


def test_checkpoint_failure_compensates_new_pending_approval() -> None:
    service, cases, approvals, _ = workflow(checkpoints=FailingCheckpointRepository())
    result = service.start(HighRiskStartRequest(message="高金额退货"), context=context())
    assert result.status is HighRiskWorkflowStatus.FAILED_SAFE
    assert approvals.task_count == 0 and cases.case_count == 0


def test_t605_high_risk_continuation_waits_then_resumes_once_after_human_decision() -> None:
    high_risk, cases, approvals, checkpoints = workflow()
    order_service = OrderQueryService(
        HttpOrderGateway(TestClient(create_app(manifest_path=DATA_ROOT / "manifest.json")))
    )
    catalog = PolicyCatalog.from_manifest(DATA_ROOT / "manifest.json")
    runtime = ControlledAgentExecutor()
    validator = ToolPlanValidator(executor=runtime)
    state = runtime.receive_turn(
        conversation_id="CONV-HIGH", turn_id="TURN-HIGH", user_id="USR-DEMO-001"
    )
    state = runtime.apply_event(state, AgentEventType.USER_MESSAGE)
    state = runtime.apply_event(state, AgentEventType.MODEL_RESULT)
    state = runtime.accept_validated_model_plan(state)
    plan = AgentPlanCandidate.model_validate(
        {
            "schema_version": "agent-plan-v1",
            "intent": "return_request",
            "requested_capability": "return.evaluate",
            "extracted_parameters": {
                "order_id": "ORD-HIGH-VALUE-001",
                "return_reason": "changed_mind",
                "item_condition": "resalable",
            },
            "clarification_fields": [],
            "uncertainty_reason": None,
        }
    )
    trusted = (
        TrustedParameter(
            name="order_id",
            value="ORD-HIGH-VALUE-001",
            source=ParameterSource.CONFIRMED_FIELD,
        ),
        TrustedParameter(
            name="return_reason",
            value="changed_mind",
            source=ParameterSource.CONFIRMED_FIELD,
        ),
        TrustedParameter(
            name="item_condition",
            value="resalable",
            source=ParameterSource.CONFIRMED_FIELD,
        ),
    )
    validated = validator.validate(
        state,
        plan,
        PlanValidationContext(authorized_user_id="USR-DEMO-001", trusted_parameters=trusted),
    )
    assert validated.permit is not None
    approval_service = ApprovalTaskService(approvals)
    recovery = ApprovalRecoveryService(
        checkpoints,
        approvals=approvals,
        service_cases=ServiceCaseService(cases),
    )
    tool = ControlledToolExecutor(
        permits=validator.execution_verifier,
        orders=order_service,
        policies=PolicyAnswerService(catalog),
        catalog=catalog,
        product_categories=product_categories(),
        eligibility=EligibilityEngine(EligibilityRuleConfig.from_json(CONFIG_PATH)),
        high_risk=high_risk,
        recovery=recovery,
        approvals=approval_service,
    )
    evaluated = tool.execute(state=state, permit=validated.permit)
    assert evaluated.continuation_state is not None and evaluated.evidence is not None
    assert evaluated.evidence.order_item_id == "ITEM-HIGH-VALUE-001"
    started = tool.execute(state=evaluated.continuation_state, permit=evaluated.continuations[0])
    continuation_state = started.continuation_state
    assert started.evidence is not None and continuation_state is not None and cases.case_count == 0
    assert started.evidence.order_item_id == evaluated.evidence.order_item_id
    approval_id = next(
        field.value for field in started.evidence.public_fields if field.name == "approval_id"
    )
    decided = approval_service.decide(
        approval_id,
        ApprovalDecisionRequest(
            decision=ApprovalDecision.APPROVE,
            note="批准",
            expected_version=1,
        ),
        actor_context=ApprovalActorContext(actor_id="USR-AGENT-001"),
    )
    assert decided.approval is not None
    resume = next(
        permit for permit in started.continuations if permit.step.tool_id is ToolId.HIGH_RISK_RESUME
    )
    completed = tool.execute(state=continuation_state, permit=resume)
    repeated = tool.execute(state=continuation_state, permit=resume)
    assert completed.succeeded and completed.evidence is not None and cases.case_count == 1
    assert completed.evidence.order_item_id == evaluated.evidence.order_item_id
    assert repeated.code == "EXECUTION_PERMIT_INVALID"
    drafting_state = state.model_copy(update={"status": AgentStatus.DRAFTING})
    resolver = EvidenceContextResolver(tool.evidence_verifier)
    assert (
        resolver.resolve(drafting_state, (evaluated.evidence,), now=datetime.now(UTC)) is not None
    )
    assert (
        resolver.resolve(drafting_state, (completed.evidence,), now=datetime.now(UTC)) is not None
    )
    service_case_id = next(
        field.value for field in completed.evidence.public_fields if field.name == "service_case_id"
    )
    response = AgentResponseService(
        executor=runtime,
        model_gateway=FakeModelGateway(
            {
                "TURN-HIGH": {
                    "schema_version": "agent-response-draft-v1",
                    "text": (
                        "该退货申请需要人工审批。人工审批已批准。"
                        f"售后申请已创建，编号为 {service_case_id}。"
                    ),
                    "claims": [
                        {
                            "claim_type": "eligibility",
                            "evidence_ids": [completed.evidence.evidence_id],
                        },
                        {
                            "claim_type": "approval",
                            "evidence_ids": [completed.evidence.evidence_id],
                        },
                        {
                            "claim_type": "completion",
                            "evidence_ids": [completed.evidence.evidence_id],
                        },
                    ],
                }
            }
        ),
        evidence_verifier=tool.evidence_verifier,
    ).generate(
        drafting_state,
        text="查询审批结果",
        evidence=(evaluated.evidence, completed.evidence),
        prompt_version="t606-v1",
    )
    assert response.outcome is AgentResponseOutcome.ALLOWED


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
