from typing import Protocol

from customer_service.approvals.repository import StoredApprovalTask
from customer_service.approvals.schemas import ApprovalDecision, ApprovalStatus, ApprovalTaskSummary
from customer_service.recovery.repository import (
    InMemoryRecoveryCheckpointRepository,
    RecoveryOperationState,
    StoredRecoveryCheckpoint,
)
from customer_service.recovery.schemas import (
    RecoveryAccessContext,
    RecoveryCheckpointRequest,
    RecoveryErrorCode,
    RecoveryResult,
    RecoveryStage,
)
from customer_service.service_cases.schemas import ServiceCaseAccessContext, ServiceCaseStatus
from customer_service.service_cases.service import ServiceCaseService


class ApprovalRecoveryService:
    """Resume only a server-stored, approved task through the controlled case port."""

    def __init__(
        self,
        repository: InMemoryRecoveryCheckpointRepository,
        *,
        approvals: "ApprovalTaskLookup",
        service_cases: ServiceCaseService,
        workflow_version: str = "1.0.0",
        checkpoint_schema_version: int = 1,
    ) -> None:
        self._repository = repository
        self._approvals = approvals
        self._service_cases = service_cases
        self._workflow_version = workflow_version
        self._checkpoint_schema_version = checkpoint_schema_version

    def checkpoint(
        self, request: RecoveryCheckpointRequest, *, context: RecoveryAccessContext
    ) -> RecoveryResult:
        try:
            approval = self._approval(request.approval_id)
            if approval is None:
                return self._failed(RecoveryErrorCode.APPROVAL_NOT_FOUND)
            if approval.user_id != context.current_user_id:
                return self._failed(RecoveryErrorCode.APPROVAL_CONTEXT_MISMATCH)
            stored = self._repository.save_if_absent(
                StoredRecoveryCheckpoint(
                    workflow_id=request.workflow_id,
                    approval=approval,
                    workflow_version=self._workflow_version,
                    checkpoint_schema_version=self._checkpoint_schema_version,
                )
            )
            if not self._version_matches(stored):
                return self._failed(RecoveryErrorCode.WORKFLOW_VERSION_MISMATCH)
            if not self._same_binding(stored.approval, approval):
                return self._failed(RecoveryErrorCode.CHECKPOINT_CONTEXT_MISMATCH)
            return self._recover(stored, approval, context)
        except Exception:
            return self._failed(RecoveryErrorCode.CHECKPOINT_UNAVAILABLE)

    def recover(self, workflow_id: str, *, context: RecoveryAccessContext) -> RecoveryResult:
        try:
            stored = self._repository.find(workflow_id.strip().upper())
            if stored is None:
                return self._failed(RecoveryErrorCode.CHECKPOINT_NOT_FOUND)
            if not self._version_matches(stored):
                return self._failed(RecoveryErrorCode.WORKFLOW_VERSION_MISMATCH)
            approval = self._approval(stored.approval.approval_id)
            if approval is None:
                return self._failed(RecoveryErrorCode.APPROVAL_NOT_FOUND)
            if approval.user_id != context.current_user_id or not self._same_binding(
                stored.approval, approval
            ):
                return self._failed(RecoveryErrorCode.APPROVAL_CONTEXT_MISMATCH)
            return self._recover(stored, approval, context)
        except Exception:
            return self._failed(RecoveryErrorCode.CHECKPOINT_UNAVAILABLE)

    def _recover(
        self,
        stored: StoredRecoveryCheckpoint,
        approval: ApprovalTaskSummary,
        context: RecoveryAccessContext,
    ) -> RecoveryResult:
        if approval.status is ApprovalStatus.PENDING:
            return self._result(RecoveryStage.WAITING_APPROVAL, stored.workflow_id, approval)
        if approval.status is ApprovalStatus.ADJUSTED:
            return self._result(RecoveryStage.NEEDS_CLARIFICATION, stored.workflow_id, approval)
        if approval.status is ApprovalStatus.REJECTED:
            return self._result(RecoveryStage.REJECTED, stored.workflow_id, approval)
        if approval.decision is not ApprovalDecision.APPROVE:
            return self._failed(RecoveryErrorCode.APPROVAL_CONTEXT_MISMATCH)
        if stored.operation_state is RecoveryOperationState.UNKNOWN:
            return self._failed(RecoveryErrorCode.OPERATION_STATE_UNKNOWN)
        result = self._service_cases.create_after_approval(
            approval,
            access_context=ServiceCaseAccessContext(current_user_id=context.current_user_id),
        )
        if (
            result.status not in {ServiceCaseStatus.CREATED, ServiceCaseStatus.EXISTING}
            or result.service_case is None
        ):
            if not self._repository.mark_unknown(
                stored.workflow_id, expected_revision=stored.revision
            ):
                return self._failed(RecoveryErrorCode.CHECKPOINT_VERSION_CONFLICT)
            return self._failed(RecoveryErrorCode.OPERATION_STATE_UNKNOWN)
        if not self._repository.mark_completed(
            stored.workflow_id, result.service_case, expected_revision=stored.revision
        ):
            return self._failed(RecoveryErrorCode.CHECKPOINT_VERSION_CONFLICT)
        return RecoveryResult(
            stage=RecoveryStage.COMPLETED,
            error_code=None,
            message="已恢复并确认模拟售后申请。",
            workflow_id=stored.workflow_id,
            approval=approval,
            service_case=result.service_case,
        )

    def _approval(self, approval_id: str) -> ApprovalTaskSummary | None:
        task = self._approvals.find_by_id(approval_id)
        return None if task is None else self._summary(task)

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
    def _same_binding(left: ApprovalTaskSummary, right: ApprovalTaskSummary) -> bool:
        return (
            left.approval_id == right.approval_id
            and left.user_id == right.user_id
            and left.order == right.order
            and left.order_item_id == right.order_item_id
            and left.policy_citations == right.policy_citations
            and left.eligibility == right.eligibility
            and right.version >= left.version
        )

    def _version_matches(self, stored: StoredRecoveryCheckpoint) -> bool:
        return (
            stored.workflow_version == self._workflow_version
            and stored.checkpoint_schema_version == self._checkpoint_schema_version
            and stored.revision >= 1
        )

    @staticmethod
    def _result(
        stage: RecoveryStage, workflow_id: str, approval: ApprovalTaskSummary
    ) -> RecoveryResult:
        return RecoveryResult(
            stage=stage,
            error_code=None,
            message="已读取可信审批状态。",
            workflow_id=workflow_id,
            approval=approval,
            service_case=None,
        )

    @staticmethod
    def _failed(error_code: RecoveryErrorCode) -> RecoveryResult:
        return RecoveryResult(
            stage=RecoveryStage.FAILED_SAFE,
            error_code=error_code,
            message="无法安全恢复原任务，请人工处理。",
            workflow_id=None,
            approval=None,
            service_case=None,
        )


class ApprovalTaskLookup(Protocol):
    def find_by_id(self, approval_id: str) -> StoredApprovalTask | None: ...
