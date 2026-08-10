from customer_service.approvals.schemas import (
    ApprovalActorContext,
    ApprovalDecisionRequest,
    ApprovalTaskContext,
    ApprovalTaskCreateRequest,
    ApprovalTaskResultStatus,
)
from customer_service.approvals.service import ApprovalTaskService
from customer_service.eligibility.engine import EligibilityEngine
from customer_service.eligibility.schemas import (
    EligibilityItemFacts,
    EligibilityRequest,
    EligibilityStatus,
)
from customer_service.orchestration.high_risk_schemas import (
    HighRiskContext,
    HighRiskDecisionInput,
    HighRiskStartRequest,
    HighRiskWorkflowResult,
    HighRiskWorkflowStatus,
)
from customer_service.rag.catalog import PolicyCatalog
from customer_service.rag.schemas import PolicyAnswerStatus, PolicyQuery
from customer_service.rag.service import PolicyAnswerService
from customer_service.recovery.repository import InMemoryRecoveryCheckpointRepository
from customer_service.recovery.schemas import (
    RecoveryAccessContext,
    RecoveryCheckpointRequest,
    RecoveryStage,
)
from customer_service.recovery.service import ApprovalRecoveryService
from customer_service.response_gate.schemas import ResponseDraft, ResponseEvidenceContext
from customer_service.response_gate.service import ResponseGateService
from customer_service.tools.order_tool import OrderQueryService
from customer_service.tools.schemas import OrderAccessContext, OrderQuery, OrderQueryStatus


class HighRiskReturnWorkflowService:
    """T-304 minimal composition of existing high-risk services."""

    def __init__(
        self,
        *,
        orders: OrderQueryService,
        policies: PolicyAnswerService,
        policy_catalog: PolicyCatalog,
        product_categories: dict[str, str],
        eligibility: EligibilityEngine,
        approvals: ApprovalTaskService,
        recovery: ApprovalRecoveryService,
        checkpoints: InMemoryRecoveryCheckpointRepository,
        gate: ResponseGateService,
    ) -> None:
        self._orders, self._policies, self._catalog = orders, policies, policy_catalog
        self._categories, self._eligibility, self._approvals = (
            product_categories,
            eligibility,
            approvals,
        )
        self._recovery, self._checkpoints, self._gate = recovery, checkpoints, gate

    def start(
        self, request: HighRiskStartRequest, *, context: HighRiskContext
    ) -> HighRiskWorkflowResult:
        order_result = self._orders.query(
            OrderQuery(order_id=context.order_id),
            access_context=OrderAccessContext(current_user_id=context.current_user_id),
        )
        if (
            order_result.status is not OrderQueryStatus.FOUND
            or order_result.order is None
            or len(order_result.order.items) != 1
        ):
            return self._failed("无法安全读取高风险订单。")
        order, item = order_result.order, order_result.order.items[0]
        category = self._categories.get(item.product_id)
        if category is None:
            return self._failed("缺少当前政策依据。")
        policy = self._policies.answer(
            PolicyQuery(category=category, return_reason=context.return_reason.value)
        )
        if policy.status is not PolicyAnswerStatus.ANSWERED:
            return self._failed("当前政策依据不足，已停止自动处理。")
        policies = tuple(
            p for p in self._catalog.policies if p.policy_id in policy.candidate_policy_ids
        )
        decision = self._eligibility.evaluate(
            EligibilityRequest(
                order=order,
                item=EligibilityItemFacts(
                    order_item_id=item.order_item_id, product_id=item.product_id, category=category
                ),
                return_reason=context.return_reason,
                item_condition=context.item_condition,
                policies=policies,
            )
        )
        if decision.status is not EligibilityStatus.REQUIRES_APPROVAL:
            return self._failed("当前事项不属于可恢复的高风险审批路径。")
        approval_context = ApprovalTaskContext(
            current_user_id=context.current_user_id,
            order=order,
            order_item_id=item.order_item_id,
            eligibility=decision,
            policy_citations=policy.citations,
        )
        created = self._approvals.create(
            ApprovalTaskCreateRequest(conversation_summary=request.message),
            context=approval_context,
        )
        if (
            created.status
            not in {ApprovalTaskResultStatus.CREATED, ApprovalTaskResultStatus.EXISTING}
            or created.approval is None
        ):
            return self._failed("人工审批任务未创建成功。")
        recovered = self._recovery.checkpoint(
            RecoveryCheckpointRequest(
                workflow_id=context.workflow_id, approval_id=created.approval.approval_id
            ),
            context=RecoveryAccessContext(current_user_id=context.current_user_id),
        )
        if recovered.stage is not RecoveryStage.WAITING_APPROVAL:
            if created.status is ApprovalTaskResultStatus.CREATED:
                self._approvals.rollback_uncheckpointed_creation(
                    created.approval.approval_id, context=approval_context
                )
            return self._failed("无法安全保存审批检查点。")
        return HighRiskWorkflowResult(
            status=HighRiskWorkflowStatus.WAITING_APPROVAL,
            message="已进入人工审批等待。",
            approval=created.approval,
            service_case=None,
            gate_action=None,
            business_operation_requested=False,
        )

    def decide_and_resume(
        self,
        decision: HighRiskDecisionInput,
        *,
        context: HighRiskContext,
        actor_context: ApprovalActorContext,
    ) -> HighRiskWorkflowResult:
        stored = self._checkpoints.find(context.workflow_id.strip().upper())
        if stored is None:
            return self._failed("未找到可恢复的审批任务。")
        decided = self._approvals.decide(
            stored.approval.approval_id,
            ApprovalDecisionRequest(
                decision=decision.decision,
                note=decision.note,
                recommendation=decision.recommendation,
                expected_version=decision.expected_version,
            ),
            actor_context=actor_context,
        )
        if decided.status not in {
            ApprovalTaskResultStatus.DECIDED,
            ApprovalTaskResultStatus.BLOCKED,
        }:
            return self._failed("无法安全记录人工决定。")
        resumed = self._recovery.recover(
            context.workflow_id,
            context=RecoveryAccessContext(current_user_id=context.current_user_id),
        )
        if (
            resumed.stage is RecoveryStage.COMPLETED
            and resumed.approval is not None
            and resumed.service_case is not None
        ):
            draft = ResponseDraft(
                message="人工已批准，模拟售后申请已创建。",
                policy_citations=resumed.approval.policy_citations,
                order=resumed.approval.order,
                eligibility=resumed.approval.eligibility,
                service_case=resumed.service_case,
                approval=resumed.approval,
                claims_policy_conclusion=True,
                claims_order_facts=True,
                claims_eligibility=True,
                claims_completion=True,
            )
            gated = self._gate.evaluate(
                draft,
                evidence=ResponseEvidenceContext(
                    policy_citations=resumed.approval.policy_citations,
                    current_user_id=context.current_user_id,
                    order=resumed.approval.order,
                    eligibility=resumed.approval.eligibility,
                    service_case=resumed.service_case,
                    approval=resumed.approval,
                ),
            )
            if gated.response is None:
                return self._failed("最终回复未通过质量门禁。")
            return HighRiskWorkflowResult(
                status=HighRiskWorkflowStatus.COMPLETED,
                message=gated.message,
                approval=resumed.approval,
                service_case=resumed.service_case,
                gate_action=gated.action,
                business_operation_requested=True,
            )
        if resumed.stage is RecoveryStage.NEEDS_CLARIFICATION:
            return HighRiskWorkflowResult(
                status=HighRiskWorkflowStatus.NEEDS_CLARIFICATION,
                message="人工已调整建议，请补充所需信息。",
                approval=resumed.approval,
                service_case=None,
                gate_action=None,
                business_operation_requested=False,
            )
        if resumed.stage is RecoveryStage.REJECTED:
            return HighRiskWorkflowResult(
                status=HighRiskWorkflowStatus.REJECTED,
                message="人工审核未通过，未创建模拟售后申请。",
                approval=resumed.approval,
                service_case=None,
                gate_action=None,
                business_operation_requested=False,
            )
        return self._failed("当前审批仍未满足安全恢复条件。")

    @staticmethod
    def _failed(message: str) -> HighRiskWorkflowResult:
        return HighRiskWorkflowResult(
            status=HighRiskWorkflowStatus.FAILED_SAFE,
            message=message,
            approval=None,
            service_case=None,
            gate_action=None,
            business_operation_requested=False,
        )
