from datetime import datetime

import pytest

from customer_service.approvals.repository import StoredApprovalTask
from customer_service.approvals.schemas import ApprovalDecision, ApprovalStatus
from customer_service.eligibility.schemas import (
    EligibilityConclusion,
    EligibilityInputBinding,
    EligibilityResult,
    EligibilityStatus,
    RiskReason,
)
from customer_service.rag.schemas import PolicyCitation
from customer_service.recovery.repository import (
    InMemoryRecoveryCheckpointRepository,
    StoredRecoveryCheckpoint,
)
from customer_service.recovery.schemas import (
    RecoveryAccessContext,
    RecoveryCheckpointRequest,
    RecoveryErrorCode,
    RecoveryStage,
)
from customer_service.recovery.service import ApprovalRecoveryService
from customer_service.service_cases.repository import InMemoryServiceCaseRepository
from customer_service.service_cases.service import ServiceCaseService
from customer_service.tools.schemas import AuthorizedOrderFacts, AuthorizedOrderItem


class ApprovalStore:
    def __init__(self, task: StoredApprovalTask) -> None:
        self.task = task

    def find_by_id(self, approval_id: str) -> StoredApprovalTask | None:
        return self.task if approval_id == self.task.approval_id else None


def trusted_task(status: ApprovalStatus = ApprovalStatus.PENDING) -> StoredApprovalTask:
    order = AuthorizedOrderFacts(
        order_id="ORD-HIGH-001",
        status="delivered",
        placed_at=datetime(2026, 7, 1),
        delivered_at=datetime(2026, 7, 2),
        currency="CNY",
        total_amount="9999.00",
        items=(
            AuthorizedOrderItem(
                order_item_id="ITEM-1",
                product_id="PROD-1",
                quantity=1,
                unit_price="9999.00",
                line_total="9999.00",
            ),
        ),
    )
    eligibility = EligibilityResult(
        rule_version="1.0.0",
        status=EligibilityStatus.REQUIRES_APPROVAL,
        eligibility=EligibilityConclusion.INDETERMINATE,
        applicable_policy_ids=("POL-1",),
        matched_rule_ids=("HIGH_VALUE_THRESHOLD",),
        missing_fields=(),
        risk_reasons=(RiskReason.HIGH_VALUE_ORDER,),
        requires_human_approval=True,
        days_since_delivery=2,
        message="approval",
        input_binding=EligibilityInputBinding(
            order_id=order.order_id,
            order_item_id="ITEM-1",
            product_id="PROD-1",
            rule_version="1.0.0",
        ),
    )
    citation = PolicyCitation(
        policy_id="POL-1",
        evidence_id="policy:POL-1:1.0.0",
        policy_version="1.0.0",
        title="policy",
        source="synthetic://policy",
        effective_from=datetime(2026, 1, 1).date(),
        effective_to=datetime(2026, 12, 31).date(),
        excerpt="approval",
    )
    terminal = status is not ApprovalStatus.PENDING
    decision = (
        ApprovalDecision.APPROVE
        if status is ApprovalStatus.APPROVED
        else (
            ApprovalDecision.REJECT
            if status is ApprovalStatus.REJECTED
            else ApprovalDecision.ADJUST
            if status is ApprovalStatus.ADJUSTED
            else None
        )
    )
    return StoredApprovalTask(
        approval_id="APR-1",
        idempotency_key="approval-key",
        user_id="USR-DEMO-001",
        order=order,
        order_item_id="ITEM-1",
        conversation_summary="high value return",
        policy_citations=(citation,),
        eligibility=eligibility,
        status=status,
        version=2 if terminal else 1,
        decision=decision,
        note="handled" if terminal else None,
        recommendation="clarify" if status is ApprovalStatus.ADJUSTED else None,
        decided_by="AGENT-1" if terminal else None,
        decided_at=datetime(2026, 7, 3) if terminal else None,
    )


def service(
    task: StoredApprovalTask, *, cases: InMemoryServiceCaseRepository | None = None
) -> ApprovalRecoveryService:
    return ApprovalRecoveryService(
        InMemoryRecoveryCheckpointRepository(),
        approvals=ApprovalStore(task),
        service_cases=ServiceCaseService(cases or InMemoryServiceCaseRepository()),
    )


def request(**values: str) -> RecoveryCheckpointRequest:
    return RecoveryCheckpointRequest(
        workflow_id=values.get("workflow_id", "WF-1"),
        approval_id=values.get("approval_id", "APR-1"),
    )


def test_public_payload_rejects_forged_business_facts() -> None:
    with pytest.raises(ValueError):
        RecoveryCheckpointRequest.model_validate(
            {"workflow_id": "WF-1", "approval_id": "APR-1", "approval": {"status": "approved"}}
        )


def test_missing_checkpoint_recovery_fails_safely_without_write_or_facts() -> None:
    cases = InMemoryServiceCaseRepository()
    runner = service(trusted_task(ApprovalStatus.APPROVED), cases=cases)

    result = runner.recover(
        "WF-MISSING", context=RecoveryAccessContext(current_user_id="USR-DEMO-001")
    )

    assert result.stage is RecoveryStage.FAILED_SAFE
    assert result.error_code is RecoveryErrorCode.CHECKPOINT_NOT_FOUND
    assert result.workflow_id is None
    assert result.approval is None
    assert result.service_case is None
    assert cases.case_count == 0


def test_pending_checkpoint_is_server_sourced_and_survives_restart() -> None:
    task = trusted_task()
    repo = InMemoryRecoveryCheckpointRepository()
    first = ApprovalRecoveryService(
        repo,
        approvals=ApprovalStore(task),
        service_cases=ServiceCaseService(InMemoryServiceCaseRepository()),
    )
    assert (
        first.checkpoint(
            request(), context=RecoveryAccessContext(current_user_id="USR-DEMO-001")
        ).stage
        is RecoveryStage.WAITING_APPROVAL
    )
    restarted = ApprovalRecoveryService(
        InMemoryRecoveryCheckpointRepository(repo.export()),
        approvals=ApprovalStore(task),
        service_cases=ServiceCaseService(InMemoryServiceCaseRepository()),
    )
    assert (
        restarted.recover(
            " wf-1 ", context=RecoveryAccessContext(current_user_id="USR-DEMO-001")
        ).stage
        is RecoveryStage.WAITING_APPROVAL
    )


@pytest.mark.parametrize(
    "workflow_version, checkpoint_schema_version", [("0.9.0", 1), (None, 1), ("1.0.0", None)]
)
def test_incompatible_checkpoint_version_fails_before_case_write(
    workflow_version: str | None, checkpoint_schema_version: int | None
) -> None:
    cases = InMemoryServiceCaseRepository()
    repository = InMemoryRecoveryCheckpointRepository(
        (
            StoredRecoveryCheckpoint(
                workflow_id="WF-1",
                approval=ApprovalRecoveryService._summary(trusted_task(ApprovalStatus.APPROVED)),
                workflow_version=workflow_version,
                checkpoint_schema_version=checkpoint_schema_version,
            ),
        )
    )
    runner = ApprovalRecoveryService(
        repository,
        approvals=ApprovalStore(trusted_task(ApprovalStatus.APPROVED)),
        service_cases=ServiceCaseService(cases),
    )
    result = runner.recover("WF-1", context=RecoveryAccessContext(current_user_id="USR-DEMO-001"))
    assert result.stage is RecoveryStage.FAILED_SAFE
    assert result.error_code is RecoveryErrorCode.WORKFLOW_VERSION_MISMATCH
    assert result.approval is None and result.service_case is None and cases.case_count == 0


@pytest.mark.parametrize(
    "status, stage",
    [
        (ApprovalStatus.ADJUSTED, RecoveryStage.NEEDS_CLARIFICATION),
        (ApprovalStatus.REJECTED, RecoveryStage.REJECTED),
    ],
)
def test_non_approved_tasks_do_not_write(status: ApprovalStatus, stage: RecoveryStage) -> None:
    result = service(trusted_task(status)).checkpoint(
        request(), context=RecoveryAccessContext(current_user_id="USR-DEMO-001")
    )
    assert result.stage is stage and result.service_case is None


def test_approved_recovery_creates_once_and_reuses_existing_case() -> None:
    cases = InMemoryServiceCaseRepository()
    runner = service(trusted_task(ApprovalStatus.APPROVED), cases=cases)
    first = runner.checkpoint(
        request(), context=RecoveryAccessContext(current_user_id="USR-DEMO-001")
    )
    second = runner.recover("WF-1", context=RecoveryAccessContext(current_user_id="USR-DEMO-001"))
    assert first.stage is second.stage is RecoveryStage.COMPLETED
    assert first.service_case == second.service_case and cases.case_count == 1


def test_cross_user_and_missing_approval_fail_without_facts() -> None:
    runner = service(trusted_task())
    denied = runner.checkpoint(
        request(), context=RecoveryAccessContext(current_user_id="USR-OTHER")
    )
    missing = runner.checkpoint(
        request(approval_id="APR-FAKE"),
        context=RecoveryAccessContext(current_user_id="USR-DEMO-001"),
    )
    assert denied.stage is RecoveryStage.FAILED_SAFE and denied.approval is None
    assert missing.error_code is RecoveryErrorCode.APPROVAL_NOT_FOUND and missing.approval is None


def test_changed_trusted_approval_binding_cannot_resume_checkpoint() -> None:
    task = trusted_task()
    store = ApprovalStore(task)
    runner = ApprovalRecoveryService(
        InMemoryRecoveryCheckpointRepository(),
        approvals=store,
        service_cases=ServiceCaseService(InMemoryServiceCaseRepository()),
    )
    runner.checkpoint(request(), context=RecoveryAccessContext(current_user_id="USR-DEMO-001"))
    store.task = trusted_task(ApprovalStatus.APPROVED).__class__(
        **{**trusted_task(ApprovalStatus.APPROVED).__dict__, "order_item_id": "ITEM-OTHER"}
    )
    result = runner.recover("WF-1", context=RecoveryAccessContext(current_user_id="USR-DEMO-001"))
    assert result.stage is RecoveryStage.FAILED_SAFE and result.approval is None


class FailingCaseRepository(InMemoryServiceCaseRepository):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def create(self, *, draft):  # type: ignore[no-untyped-def]
        self.calls += 1
        raise RuntimeError("timeout password=secret host=internal")


def test_unknown_write_is_not_blindly_retried() -> None:
    cases = FailingCaseRepository()
    runner = service(trusted_task(ApprovalStatus.APPROVED), cases=cases)
    first = runner.checkpoint(
        request(), context=RecoveryAccessContext(current_user_id="USR-DEMO-001")
    )
    second = runner.recover("WF-1", context=RecoveryAccessContext(current_user_id="USR-DEMO-001"))
    assert first.error_code is second.error_code is RecoveryErrorCode.OPERATION_STATE_UNKNOWN
    assert first.service_case is second.service_case is None and cases.calls == 1


class PersistThenTimeoutRepository(InMemoryServiceCaseRepository):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def create(self, *, draft):  # type: ignore[no-untyped-def]
        self.calls += 1
        super().create(draft=draft)
        raise TimeoutError("internal host=db password=secret")


def test_write_after_persisted_timeout_is_not_retried_or_reported_as_success() -> None:
    cases = PersistThenTimeoutRepository()
    runner = service(trusted_task(ApprovalStatus.APPROVED), cases=cases)
    first = runner.checkpoint(
        request(), context=RecoveryAccessContext(current_user_id="USR-DEMO-001")
    )
    second = runner.recover("WF-1", context=RecoveryAccessContext(current_user_id="USR-DEMO-001"))
    assert first.error_code is second.error_code is RecoveryErrorCode.OPERATION_STATE_UNKNOWN
    assert first.service_case is second.service_case is None
    assert cases.calls == 1 and cases.case_count == 1


def test_stale_checkpoint_update_is_compare_and_set_rejected() -> None:
    checkpoint = StoredRecoveryCheckpoint(
        workflow_id="WF-1",
        approval=ApprovalRecoveryService._summary(trusted_task()),
        workflow_version="1.0.0",
        checkpoint_schema_version=1,
    )
    repository = InMemoryRecoveryCheckpointRepository((checkpoint,))
    assert repository.mark_unknown("WF-1", expected_revision=2) is False
    assert repository.find("WF-1") == checkpoint
