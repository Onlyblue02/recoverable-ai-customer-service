from datetime import datetime

import pytest
from pydantic import ValidationError

from customer_service.eligibility.schemas import (
    EligibilityConclusion,
    EligibilityInputBinding,
    EligibilityResult,
    EligibilityStatus,
    RiskReason,
)
from customer_service.service_cases.repository import (
    InMemoryServiceCaseRepository,
    ServiceCaseDraft,
    StoredServiceCase,
)
from customer_service.service_cases.schemas import (
    ServiceCaseAccessContext,
    ServiceCaseCreateRequest,
    ServiceCaseEligibilityContext,
    ServiceCaseErrorCode,
    ServiceCaseResult,
    ServiceCaseStatus,
)
from customer_service.service_cases.service import ServiceCaseService
from customer_service.tools.schemas import AuthorizedOrderFacts, AuthorizedOrderItem


def order(
    *,
    order_id: str = "ORD-TEST-001",
    item_id: str = "ITEM-TEST-001",
    product_id: str = "PROD-TEST-001",
    total_amount: str = "129.00",
) -> AuthorizedOrderFacts:
    return AuthorizedOrderFacts(
        order_id=order_id,
        status="delivered",
        placed_at=datetime.fromisoformat("2026-07-15T09:00:00+00:00"),
        delivered_at=datetime.fromisoformat("2026-07-18T10:00:00+00:00"),
        currency="CNY",
        total_amount=total_amount,
        items=(
            AuthorizedOrderItem(
                order_item_id=item_id,
                product_id=product_id,
                quantity=1,
                unit_price=total_amount,
                line_total=total_amount,
            ),
        ),
    )


def eligible_result(bound_order: AuthorizedOrderFacts) -> EligibilityResult:
    item = bound_order.items[0]
    return EligibilityResult(
        rule_version="1.0.0",
        status=EligibilityStatus.ELIGIBLE,
        eligibility=EligibilityConclusion.ELIGIBLE,
        applicable_policy_ids=("POL-TEST-001",),
        matched_rule_ids=("STANDARD_WINDOW_INCLUSIVE",),
        missing_fields=(),
        risk_reasons=(),
        requires_human_approval=False,
        days_since_delivery=2,
        message="符合低风险退货条件。",
        input_binding=EligibilityInputBinding(
            order_id=bound_order.order_id,
            order_item_id=item.order_item_id,
            product_id=item.product_id,
            rule_version="1.0.0",
        ),
    )


def approval_result(bound_order: AuthorizedOrderFacts) -> EligibilityResult:
    item = bound_order.items[0]
    return EligibilityResult(
        rule_version="1.0.0",
        status=EligibilityStatus.REQUIRES_APPROVAL,
        eligibility=EligibilityConclusion.INDETERMINATE,
        applicable_policy_ids=("POL-TEST-001",),
        matched_rule_ids=("HIGH_VALUE_THRESHOLD",),
        missing_fields=(),
        risk_reasons=(RiskReason.HIGH_VALUE_ORDER,),
        requires_human_approval=True,
        days_since_delivery=2,
        message="命中高金额规则，等待人工审批。",
        input_binding=EligibilityInputBinding(
            order_id=bound_order.order_id,
            order_item_id=item.order_item_id,
            product_id=item.product_id,
            rule_version="1.0.0",
        ),
    )


def request(**overrides: object) -> ServiceCaseCreateRequest:
    values: dict[str, object] = {
        "order": order(),
        "order_item_id": "ITEM-TEST-001",
    }
    values.update(overrides)
    return ServiceCaseCreateRequest.model_validate(values)


def trusted_eligibility(
    bound_order: AuthorizedOrderFacts | None = None,
) -> ServiceCaseEligibilityContext:
    return ServiceCaseEligibilityContext(eligibility=eligible_result(bound_order or order()))


def service(repository: InMemoryServiceCaseRepository | None = None) -> ServiceCaseService:
    return ServiceCaseService(repository or InMemoryServiceCaseRepository())


def context(user_id: str = "USR-DEMO-001") -> ServiceCaseAccessContext:
    return ServiceCaseAccessContext(current_user_id=user_id)


def create(
    creator: ServiceCaseService,
    case_request: ServiceCaseCreateRequest | None = None,
    *,
    access_context: ServiceCaseAccessContext | None = None,
    eligibility: ServiceCaseEligibilityContext | None = None,
) -> ServiceCaseResult:
    actual_request = case_request or request()
    return creator.create(
        actual_request,
        access_context=access_context or context(),
        eligibility_context=eligibility or trusted_eligibility(actual_request.order),
    )


def test_public_payload_rejects_workflow_and_eligibility_override_fields() -> None:
    with pytest.raises(ValidationError):
        ServiceCaseCreateRequest.model_validate(
            {
                "order": order().model_dump(),
                "order_item_id": "ITEM-TEST-001",
                "workflow_id": "RANDOM-OVERRIDE",
                "eligibility": eligible_result(order()).model_dump(),
            }
        )


def test_eligible_request_creates_a_single_simulated_service_case() -> None:
    repository = InMemoryServiceCaseRepository()
    result = create(service(repository))

    assert result.status is ServiceCaseStatus.CREATED
    assert result.error_code is None
    assert result.service_case is not None
    assert result.service_case.service_case_id == "SC-SIM-001"
    assert repository.case_count == 1


def test_repeated_or_random_workflow_attempts_cannot_bypass_stable_key() -> None:
    repository = InMemoryServiceCaseRepository()
    creator = service(repository)

    first = create(creator)
    second = create(creator)

    assert first.status is ServiceCaseStatus.CREATED
    assert second.status is ServiceCaseStatus.EXISTING
    assert first.service_case == second.service_case
    assert repository.case_count == 1


def test_identifier_normalization_is_stable_and_different_item_is_independent() -> None:
    repository = InMemoryServiceCaseRepository()
    creator = service(repository)
    canonical = order()
    spaced = order(order_id=" ord-test-001 ", item_id=" item-test-001 ")
    other_item = order(item_id="ITEM-TEST-002", product_id="PROD-TEST-002")

    first = create(creator, request(order=canonical, order_item_id="ITEM-TEST-001"))
    same = create(
        creator,
        request(order=spaced, order_item_id=" item-test-001 "),
        eligibility=trusted_eligibility(canonical),
    )
    different = create(
        creator,
        request(order=other_item, order_item_id="ITEM-TEST-002"),
        eligibility=trusted_eligibility(other_item),
    )

    assert first.status is ServiceCaseStatus.CREATED
    assert same.status is ServiceCaseStatus.EXISTING
    assert different.status is ServiceCaseStatus.CREATED
    assert repository.case_count == 2


def test_cross_order_or_item_eligibility_replay_is_blocked_without_write() -> None:
    repository = InMemoryServiceCaseRepository()
    creator = service(repository)
    low_value = order()
    high_value = order(
        order_id="ORD-HIGH-001",
        item_id="ITEM-HIGH-001",
        product_id="PROD-HIGH-001",
        total_amount="9999.00",
    )
    same_order_other_item = order(item_id="ITEM-OTHER-001", product_id="PROD-OTHER-001")

    cross_order = create(
        creator,
        request(order=high_value, order_item_id="ITEM-HIGH-001"),
        eligibility=trusted_eligibility(low_value),
    )
    cross_item = create(
        creator,
        request(order=same_order_other_item, order_item_id="ITEM-OTHER-001"),
        eligibility=trusted_eligibility(low_value),
    )

    assert cross_order.status is ServiceCaseStatus.BLOCKED
    assert cross_item.status is ServiceCaseStatus.BLOCKED
    assert cross_order.error_code is ServiceCaseErrorCode.ELIGIBILITY_CONTEXT_MISMATCH
    assert cross_item.error_code is ServiceCaseErrorCode.ELIGIBILITY_CONTEXT_MISMATCH
    assert repository.case_count == 0


@pytest.mark.parametrize(
    "status,conclusion",
    [
        (EligibilityStatus.REQUIRES_APPROVAL, EligibilityConclusion.INDETERMINATE),
        (EligibilityStatus.VERIFICATION_REQUIRED, EligibilityConclusion.CONDITIONAL),
        (EligibilityStatus.INELIGIBLE, EligibilityConclusion.INELIGIBLE),
        (EligibilityStatus.NEEDS_INFORMATION, EligibilityConclusion.INDETERMINATE),
    ],
)
def test_non_creatable_trusted_eligibility_cannot_write(
    status: EligibilityStatus, conclusion: EligibilityConclusion
) -> None:
    bound_order = order()
    base = approval_result(bound_order)
    if status is not EligibilityStatus.REQUIRES_APPROVAL:
        base = base.model_copy(
            update={
                "status": status,
                "eligibility": conclusion,
                "requires_human_approval": False,
                "risk_reasons": (
                    (RiskReason.ISSUE_VERIFICATION_REQUIRED,)
                    if status is EligibilityStatus.VERIFICATION_REQUIRED
                    else ()
                ),
                "missing_fields": (
                    ("return_reason",) if status is EligibilityStatus.NEEDS_INFORMATION else ()
                ),
            }
        )
    repository = InMemoryServiceCaseRepository()
    result = create(
        service(repository), eligibility=ServiceCaseEligibilityContext(eligibility=base)
    )

    assert result.status is ServiceCaseStatus.BLOCKED
    assert result.error_code is ServiceCaseErrorCode.ELIGIBILITY_NOT_CREATABLE
    assert repository.case_count == 0


def test_unbound_order_item_cannot_write() -> None:
    repository = InMemoryServiceCaseRepository()
    result = create(service(repository), request(order_item_id="ITEM-NOT-IN-ORDER"))

    assert result.status is ServiceCaseStatus.BLOCKED
    assert result.error_code is ServiceCaseErrorCode.ORDER_ITEM_NOT_AUTHORIZED
    assert result.service_case is None
    assert repository.case_count == 0


@pytest.mark.parametrize("status", ["pending", "unknown", "failed"])
def test_unconfirmed_or_wrong_existing_records_are_never_public_success(status: str) -> None:
    key = "USR-DEMO-001|ORD-TEST-001|ITEM-TEST-001"
    repository = InMemoryServiceCaseRepository(
        seed_cases=(
            StoredServiceCase(
                service_case_id="SC-UNCONFIRMED",
                user_id="USR-DEMO-001",
                order_id="ORD-TEST-001",
                order_item_id="ITEM-TEST-001",
                status=status,
                idempotency_key=key,
            ),
        )
    )
    result = create(service(repository))

    assert result.status is ServiceCaseStatus.FAILED_SAFE
    assert result.service_case is None
    assert "SC-UNCONFIRMED" not in result.model_dump_json()


@pytest.mark.parametrize(
    "field,value",
    [
        ("user_id", "USR-OTHER-001"),
        ("order_id", "ORD-OTHER-001"),
        ("order_item_id", "ITEM-OTHER-001"),
        ("idempotency_key", "WRONG-KEY"),
    ],
)
def test_wrong_existing_binding_is_never_public_success(field: str, value: str) -> None:
    values = {
        "service_case_id": "SC-WRONG",
        "user_id": "USR-DEMO-001",
        "order_id": "ORD-TEST-001",
        "order_item_id": "ITEM-TEST-001",
        "status": "created",
        "idempotency_key": "USR-DEMO-001|ORD-TEST-001|ITEM-TEST-001",
    }
    values[field] = value
    case = StoredServiceCase(**values)
    repository = MismatchingLookupRepository(case)
    result = create(service(repository))

    assert result.status is ServiceCaseStatus.FAILED_SAFE
    assert result.service_case is None
    assert "SC-WRONG" not in result.model_dump_json()


class MismatchingLookupRepository(InMemoryServiceCaseRepository):
    def __init__(self, case: StoredServiceCase) -> None:
        super().__init__()
        self._case = case

    def find_by_idempotency_key(self, key: str) -> StoredServiceCase | None:
        del key
        return self._case


class FailingRepository(InMemoryServiceCaseRepository):
    def create(self, *, draft: ServiceCaseDraft) -> StoredServiceCase | None:
        del draft
        raise RuntimeError("database password=secret host=db.internal")


class EmptyConfirmationRepository(InMemoryServiceCaseRepository):
    def create(self, *, draft: ServiceCaseDraft) -> StoredServiceCase | None:
        del draft
        return None


@pytest.mark.parametrize("service_case_id", ["", "   "])
def test_malformed_created_confirmation_is_safe_without_public_exception(
    service_case_id: str,
) -> None:
    repository = MalformedCreatedConfirmationRepository(service_case_id)

    result = create(service(repository))

    assert result.status is ServiceCaseStatus.FAILED_SAFE
    assert result.error_code is ServiceCaseErrorCode.SERVICE_CASE_WRITE_FAILED
    assert result.service_case is None
    public_text = result.model_dump_json()
    assert "service_case_id" not in public_text
    assert "已创建" not in public_text
    assert "已完成" not in public_text


class MalformedCreatedConfirmationRepository(InMemoryServiceCaseRepository):
    def __init__(self, service_case_id: str) -> None:
        super().__init__()
        self._service_case_id = service_case_id

    def create(self, *, draft: ServiceCaseDraft) -> StoredServiceCase | None:
        return StoredServiceCase(
            service_case_id=self._service_case_id,
            user_id=draft.user_id,
            order_id=draft.order_id,
            order_item_id=draft.order_item_id,
            status="created",
            idempotency_key=draft.idempotency_key,
        )


class CreateThenTimeoutRepository(InMemoryServiceCaseRepository):
    def create(self, *, draft: ServiceCaseDraft) -> StoredServiceCase | None:
        super().create(draft=draft)
        raise TimeoutError("internal timeout")


def test_write_failure_or_empty_confirmation_is_safe_without_success_claim() -> None:
    for repository in (FailingRepository(), EmptyConfirmationRepository()):
        result = create(service(repository))
        assert result.status is ServiceCaseStatus.FAILED_SAFE
        assert result.error_code is ServiceCaseErrorCode.SERVICE_CASE_WRITE_FAILED
        assert result.service_case is None
        public_text = result.model_dump_json()
        assert "secret" not in public_text
        assert "SC-SIM" not in public_text
        assert "已创建" not in public_text


def test_timeout_after_write_reuses_same_stable_key_on_retry() -> None:
    repository = CreateThenTimeoutRepository()
    creator = service(repository)

    first = create(creator)
    second = create(creator)

    assert first.status is ServiceCaseStatus.FAILED_SAFE
    assert second.status is ServiceCaseStatus.EXISTING
    assert repository.case_count == 1


def test_result_schema_rejects_success_without_persisted_case() -> None:
    with pytest.raises(ValidationError):
        ServiceCaseResult(
            status=ServiceCaseStatus.CREATED,
            error_code=None,
            message="申请已创建。",
            service_case=None,
        )
