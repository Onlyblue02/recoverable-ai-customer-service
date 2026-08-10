from datetime import UTC, datetime

from customer_service.approvals.repository import (
    ApprovalTaskDraft,
    ApprovalTaskRepository,
    StoredApprovalTask,
)
from customer_service.approvals.schemas import (
    ApprovalActorContext,
    ApprovalDecision,
    ApprovalDecisionRequest,
    ApprovalErrorCode,
    ApprovalStatus,
    ApprovalTaskContext,
    ApprovalTaskCreateRequest,
    ApprovalTaskResult,
    ApprovalTaskResultStatus,
    ApprovalTaskSummary,
)
from customer_service.eligibility.schemas import EligibilityStatus


class ApprovalTaskService:
    """Creates and decides high-risk tasks; it intentionally does not resume workflows."""

    def __init__(self, repository: ApprovalTaskRepository) -> None:
        self._repository = repository

    def create(
        self, request: ApprovalTaskCreateRequest, *, context: ApprovalTaskContext
    ) -> ApprovalTaskResult:
        if not self._context_is_approvable(context):
            return self._blocked(
                ApprovalErrorCode.APPROVAL_CONTEXT_MISMATCH,
                "当前证据无法创建人工审批任务。",
            )
        key = self._idempotency_key(context)
        try:
            existing = self._repository.find_by_key(key)
            if existing is not None:
                if not self._same_context(existing, context, key):
                    return self._safe_failure()
                return ApprovalTaskResult(
                    status=ApprovalTaskResultStatus.EXISTING,
                    error_code=None,
                    message="已返回原待审批任务。",
                    approval=self._summary(existing),
                )
            created = self._repository.create(
                draft=ApprovalTaskDraft(
                    idempotency_key=key,
                    user_id=context.current_user_id,
                    order=context.order,
                    order_item_id=context.order_item_id,
                    conversation_summary=request.conversation_summary,
                    policy_citations=context.policy_citations,
                    eligibility=context.eligibility,
                )
            )
            if created is None or not self._same_context(created, context, key):
                return self._safe_failure()
            return ApprovalTaskResult(
                status=ApprovalTaskResultStatus.CREATED,
                error_code=None,
                message="已创建人工审批任务，自动处理已暂停。",
                approval=self._summary(created),
            )
        except Exception:
            return self._safe_failure()

    def get_for_user(self, approval_id: str, *, current_user_id: str) -> ApprovalTaskResult:
        """Read-only, non-enumerating status lookup for controlled tool adapters."""
        try:
            stored = self._repository.find_by_id(approval_id.strip().upper())
            if stored is None or stored.user_id != current_user_id:
                return self._blocked(ApprovalErrorCode.APPROVAL_NOT_FOUND, "无法访问该审批任务。")
            return ApprovalTaskResult(
                status=ApprovalTaskResultStatus.EXISTING,
                error_code=None,
                message="已读取可信审批状态。",
                approval=self._summary(stored),
            )
        except Exception:
            return self._safe_failure()

    def rollback_uncheckpointed_creation(
        self, approval_id: str, *, context: ApprovalTaskContext
    ) -> bool:
        """Internal compensation; never changes a decided or pre-existing approval."""
        return self._repository.delete_pending(
            approval_id=approval_id,
            idempotency_key=self._idempotency_key(context),
        )

    def decide(
        self,
        approval_id: str,
        request: ApprovalDecisionRequest,
        *,
        actor_context: ApprovalActorContext,
    ) -> ApprovalTaskResult:
        try:
            current = self._repository.find_by_id(approval_id)
            if current is None:
                return self._blocked(ApprovalErrorCode.APPROVAL_NOT_FOUND, "未找到该审批任务。")
            if current.status is not ApprovalStatus.PENDING:
                return self._blocked(
                    ApprovalErrorCode.APPROVAL_ALREADY_DECIDED,
                    "该审批任务已处理，不能再次修改。",
                )
            if current.version != request.expected_version:
                return self._blocked(
                    ApprovalErrorCode.APPROVAL_VERSION_CONFLICT,
                    "审批任务已更新，请刷新后查看当前结果。",
                )
            write_result = self._repository.decide(
                approval_id=approval_id,
                expected_version=request.expected_version,
                decision=request.decision,
                note=request.note,
                recommendation=request.recommendation,
                actor_id=actor_context.actor_id,
                decided_at=datetime.now(UTC),
            )
            if write_result.task is None:
                return self._blocked(ApprovalErrorCode.APPROVAL_NOT_FOUND, "未找到该审批任务。")
            if not write_result.applied:
                return self._blocked(
                    ApprovalErrorCode.APPROVAL_VERSION_CONFLICT,
                    "审批任务已更新，请刷新后查看当前结果。",
                )
            decided = write_result.task
            return ApprovalTaskResult(
                status=ApprovalTaskResultStatus.DECIDED,
                error_code=None,
                message=self._decision_message(decided.decision),
                approval=self._summary(decided),
            )
        except Exception:
            return self._safe_failure()

    @staticmethod
    def _context_is_approvable(context: ApprovalTaskContext) -> bool:
        eligibility = context.eligibility
        binding = eligibility.input_binding
        has_item = any(
            item.order_item_id.strip().upper() == context.order_item_id
            for item in context.order.items
        )
        citation_ids = tuple(citation.policy_id for citation in context.policy_citations)
        return (
            eligibility.status is EligibilityStatus.REQUIRES_APPROVAL
            and eligibility.requires_human_approval
            and binding is not None
            and binding.rule_version == eligibility.rule_version
            and binding.order_id.strip().upper() == context.order.order_id.strip().upper()
            and binding.order_item_id.strip().upper() == context.order_item_id
            and has_item
            and citation_ids == eligibility.applicable_policy_ids
        )

    @staticmethod
    def _idempotency_key(context: ApprovalTaskContext) -> str:
        eligibility = context.eligibility
        return "|".join(
            (
                context.current_user_id,
                context.order.order_id.strip().upper(),
                context.order_item_id,
                eligibility.rule_version,
                ",".join(eligibility.applicable_policy_ids),
                ",".join(reason.value for reason in eligibility.risk_reasons),
            )
        )

    @staticmethod
    def _same_context(task: StoredApprovalTask, context: ApprovalTaskContext, key: str) -> bool:
        return (
            task.idempotency_key == key
            and task.user_id == context.current_user_id
            and task.order == context.order
            and task.order_item_id == context.order_item_id
            and task.policy_citations == context.policy_citations
            and task.eligibility == context.eligibility
        )

    @staticmethod
    def _summary(task: StoredApprovalTask) -> ApprovalTaskSummary:
        return ApprovalTaskSummary(
            approval_id=task.approval_id,
            status=task.status,
            version=task.version,
            conversation_summary=task.conversation_summary,
            user_id=task.user_id,
            order=task.order,
            order_item_id=task.order_item_id,
            policy_citations=task.policy_citations,
            eligibility=task.eligibility,
            risk_reasons=tuple(reason.value for reason in task.eligibility.risk_reasons),
            decision=task.decision,
            note=task.note,
            recommendation=task.recommendation,
            decided_by=task.decided_by,
            decided_at=task.decided_at,
        )

    @staticmethod
    def _decision_message(decision: ApprovalDecision | None) -> str:
        return {
            ApprovalDecision.APPROVE: "人工审批已批准；恢复和申请创建由后续 T-302 处理。",
            ApprovalDecision.ADJUST: "人工审批已调整；后续步骤由后续 T-302 处理。",
            ApprovalDecision.REJECT: "人工审批已拒绝；未创建模拟售后申请。",
        }[decision]  # type: ignore[index]

    @staticmethod
    def _blocked(error_code: ApprovalErrorCode, message: str) -> ApprovalTaskResult:
        return ApprovalTaskResult(
            status=ApprovalTaskResultStatus.BLOCKED,
            error_code=error_code,
            message=message,
            approval=None,
        )

    @staticmethod
    def _safe_failure() -> ApprovalTaskResult:
        return ApprovalTaskResult(
            status=ApprovalTaskResultStatus.FAILED_SAFE,
            error_code=ApprovalErrorCode.APPROVAL_WRITE_FAILED,
            message="人工审批任务暂时无法处理，请稍后重试。",
            approval=None,
        )
