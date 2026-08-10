from datetime import datetime

import pytest
from pydantic import ValidationError

from customer_service.approvals.repository import (
    ApprovalDecisionWriteResult,
    InMemoryApprovalTaskRepository,
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
)
from customer_service.approvals.service import ApprovalTaskService
from customer_service.eligibility.schemas import (
    EligibilityConclusion,
    EligibilityInputBinding,
    EligibilityResult,
    EligibilityStatus,
    RiskReason,
)
from customer_service.rag.schemas import PolicyCitation
from customer_service.tools.schemas import AuthorizedOrderFacts, AuthorizedOrderItem


def order() -> AuthorizedOrderFacts:
    return AuthorizedOrderFacts(
        order_id="ORD-HIGH-VALUE-001",
        status="delivered",
        placed_at=datetime.fromisoformat("2026-07-15T09:00:00+00:00"),
        delivered_at=datetime.fromisoformat("2026-07-18T10:00:00+00:00"),
        currency="CNY",
        total_amount="9999.00",
        items=(
            AuthorizedOrderItem(
                order_item_id="ITEM-HIGH-VALUE-001",
                product_id="PROD-GENERAL-002",
                quantity=1,
                unit_price="9999.00",
                line_total="9999.00",
            ),
        ),
    )


def citation() -> PolicyCitation:
    return PolicyCitation(
        policy_id="POL-ACTIVE-STANDARD-001",
        evidence_id="policy:POL-ACTIVE-STANDARD-001:1.0.0",
        policy_version="1.0.0",
        title="标准退货政策",
        source="synthetic://policies/standard-v1",
        effective_from=datetime.fromisoformat("2026-01-01T00:00:00+00:00").date(),
        effective_to=datetime.fromisoformat("2026-12-31T00:00:00+00:00").date(),
        excerpt="高金额订单需要人工审批。",
    )


def approval_eligibility(*, reason: RiskReason = RiskReason.HIGH_VALUE_ORDER) -> EligibilityResult:
    actual_order = order()
    return EligibilityResult(
        rule_version="1.0.0",
        status=EligibilityStatus.REQUIRES_APPROVAL,
        eligibility=EligibilityConclusion.INDETERMINATE,
        applicable_policy_ids=("POL-ACTIVE-STANDARD-001",),
        matched_rule_ids=("HIGH_VALUE_THRESHOLD",),
        missing_fields=(),
        risk_reasons=(reason,),
        requires_human_approval=True,
        days_since_delivery=2,
        message="高风险订单需要人工审批。",
        input_binding=EligibilityInputBinding(
            order_id=actual_order.order_id,
            order_item_id=actual_order.items[0].order_item_id,
            product_id=actual_order.items[0].product_id,
            rule_version="1.0.0",
        ),
    )


def context(**overrides: object) -> ApprovalTaskContext:
    values: dict[str, object] = {
        "current_user_id": "USR-DEMO-001",
        "order": order(),
        "order_item_id": "ITEM-HIGH-VALUE-001",
        "eligibility": approval_eligibility(),
        "policy_citations": (citation(),),
    }
    values.update(overrides)
    return ApprovalTaskContext.model_validate(values)


def create_request() -> ApprovalTaskCreateRequest:
    return ApprovalTaskCreateRequest(
        conversation_summary="用户申请退回高金额相机，商品状态已确认。"
    )


def decision(
    choice: ApprovalDecision = ApprovalDecision.APPROVE, *, version: int = 1
) -> ApprovalDecisionRequest:
    values: dict[str, object] = {
        "decision": choice,
        "note": "已核对订单、政策和风险原因。",
        "expected_version": version,
    }
    if choice is ApprovalDecision.ADJUST:
        values["recommendation"] = "请先补充商品照片。"
    return ApprovalDecisionRequest.model_validate(values)


def test_create_high_risk_task_is_idempotent_and_has_complete_human_context() -> None:
    repository = InMemoryApprovalTaskRepository()
    service = ApprovalTaskService(repository)

    first = service.create(create_request(), context=context())
    second = service.create(create_request(), context=context())

    assert first.status is ApprovalTaskResultStatus.CREATED
    assert second.status is ApprovalTaskResultStatus.EXISTING
    assert first.approval == second.approval
    assert first.approval is not None
    assert first.approval.status is ApprovalStatus.PENDING
    assert first.approval.order.order_id == "ORD-HIGH-VALUE-001"
    assert first.approval.policy_citations[0].policy_id == "POL-ACTIVE-STANDARD-001"
    assert first.approval.risk_reasons == ("HIGH_VALUE_ORDER",)
    assert repository.task_count == 1


def test_controlled_status_lookup_does_not_enumerate_other_users() -> None:
    repository = InMemoryApprovalTaskRepository()
    service = ApprovalTaskService(repository)
    created = service.create(create_request(), context=context())
    assert created.approval is not None
    denied = service.get_for_user(
        created.approval.approval_id,
        current_user_id="USR-OTHER",
    )
    missing = service.get_for_user("APR-FAKE", current_user_id="USR-DEMO-001")
    assert denied.status is missing.status is ApprovalTaskResultStatus.BLOCKED
    assert denied.error_code is missing.error_code is ApprovalErrorCode.APPROVAL_NOT_FOUND
    assert denied.approval is missing.approval is None


@pytest.mark.parametrize(
    ("choice", "status"),
    [
        (ApprovalDecision.APPROVE, ApprovalStatus.APPROVED),
        (ApprovalDecision.ADJUST, ApprovalStatus.ADJUSTED),
        (ApprovalDecision.REJECT, ApprovalStatus.REJECTED),
    ],
)
def test_pending_task_accepts_one_terminal_human_decision(
    choice: ApprovalDecision, status: ApprovalStatus
) -> None:
    service = ApprovalTaskService(InMemoryApprovalTaskRepository())
    created = service.create(create_request(), context=context())
    assert created.approval is not None

    result = service.decide(
        created.approval.approval_id,
        decision(choice),
        actor_context=ApprovalActorContext(actor_id="USR-AGENT-001"),
    )

    assert result.status is ApprovalTaskResultStatus.DECIDED
    assert result.approval is not None
    assert result.approval.status is status
    assert result.approval.decision is choice
    assert result.approval.decided_by == "USR-AGENT-001"
    assert result.approval.version == 2
    assert result.approval.recommendation == (
        "请先补充商品照片。" if choice is ApprovalDecision.ADJUST else None
    )


def test_processed_or_stale_approval_cannot_be_modified_again() -> None:
    service = ApprovalTaskService(InMemoryApprovalTaskRepository())
    created = service.create(create_request(), context=context())
    assert created.approval is not None
    approval_id = created.approval.approval_id
    first = service.decide(
        approval_id,
        decision(),
        actor_context=ApprovalActorContext(actor_id="USR-AGENT-001"),
    )
    duplicate = service.decide(
        approval_id,
        decision(ApprovalDecision.REJECT, version=2),
        actor_context=ApprovalActorContext(actor_id="USR-AGENT-002"),
    )

    assert first.status is ApprovalTaskResultStatus.DECIDED
    assert duplicate.status is ApprovalTaskResultStatus.BLOCKED
    assert duplicate.error_code is ApprovalErrorCode.APPROVAL_ALREADY_DECIDED
    assert duplicate.approval is None


def test_stale_version_is_rejected_before_mutating_the_pending_task() -> None:
    service = ApprovalTaskService(InMemoryApprovalTaskRepository())
    created = service.create(create_request(), context=context())
    assert created.approval is not None

    result = service.decide(
        created.approval.approval_id,
        decision(version=2),
        actor_context=ApprovalActorContext(actor_id="USR-AGENT-001"),
    )

    assert result.status is ApprovalTaskResultStatus.BLOCKED
    assert result.error_code is ApprovalErrorCode.APPROVAL_VERSION_CONFLICT
    assert result.approval is None


class InterleavingRepository(InMemoryApprovalTaskRepository):
    """Runs a competing decision after A reads but before A's compare-and-set."""

    def __init__(self, winner: ApprovalDecision) -> None:
        super().__init__()
        self._winner = winner
        self._service: ApprovalTaskService | None = None
        self._interleaved = False
        self.winner_result: ApprovalTaskResult | None = None

    def set_service(self, service: ApprovalTaskService) -> None:
        self._service = service

    def decide(self, **kwargs: object) -> ApprovalDecisionWriteResult:
        if not self._interleaved:
            self._interleaved = True
            assert self._service is not None
            self.winner_result = self._service.decide(
                str(kwargs["approval_id"]),
                decision(self._winner),
                actor_context=ApprovalActorContext(actor_id="USR-AGENT-WINNER"),
            )
        return super().decide(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "winner",
    [ApprovalDecision.APPROVE, ApprovalDecision.ADJUST, ApprovalDecision.REJECT],
)
def test_interleaved_competitor_is_not_reported_as_the_loser_success(
    winner: ApprovalDecision,
) -> None:
    repository = InterleavingRepository(winner)
    service = ApprovalTaskService(repository)
    repository.set_service(service)
    created = service.create(create_request(), context=context())
    assert created.approval is not None

    loser = service.decide(
        created.approval.approval_id,
        decision(ApprovalDecision.REJECT),
        actor_context=ApprovalActorContext(actor_id="USR-AGENT-LOSER"),
    )
    stored = repository.find_by_id(created.approval.approval_id)

    assert repository.winner_result is not None
    assert repository.winner_result.status is ApprovalTaskResultStatus.DECIDED
    assert loser.status is ApprovalTaskResultStatus.BLOCKED
    assert loser.error_code is ApprovalErrorCode.APPROVAL_VERSION_CONFLICT
    assert loser.approval is None
    assert stored is not None
    assert stored.decision is winner
    assert stored.decided_by == "USR-AGENT-WINNER"
    assert stored.version == 2


def test_non_approval_or_forged_evidence_context_never_creates_a_task() -> None:
    repository = InMemoryApprovalTaskRepository()
    service = ApprovalTaskService(repository)
    low_risk = approval_eligibility().model_copy(
        update={
            "status": EligibilityStatus.ELIGIBLE,
            "eligibility": EligibilityConclusion.ELIGIBLE,
            "risk_reasons": (),
            "requires_human_approval": False,
        }
    )
    mismatch = approval_eligibility().model_copy(
        update={"applicable_policy_ids": ("POL-OTHER-001",)}
    )

    for eligibility in (low_risk, mismatch):
        result = service.create(create_request(), context=context(eligibility=eligibility))
        assert result.status is ApprovalTaskResultStatus.BLOCKED
        assert result.error_code is ApprovalErrorCode.APPROVAL_CONTEXT_MISMATCH
        assert result.approval is None
    assert repository.task_count == 0


def test_public_payloads_reject_identity_order_evidence_and_actor_overrides() -> None:
    with pytest.raises(ValidationError):
        ApprovalTaskCreateRequest.model_validate(
            {"conversation_summary": "x", "current_user_id": "USR-ATTACKER-001"}
        )
    with pytest.raises(ValidationError):
        ApprovalDecisionRequest.model_validate(
            {
                "decision": "approve",
                "note": "ok",
                "expected_version": 1,
                "actor_id": "USR-ATTACKER-001",
            }
        )
