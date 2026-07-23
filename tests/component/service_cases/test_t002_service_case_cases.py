import json
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from customer_service.eligibility.schemas import (
    EligibilityConclusion,
    EligibilityInputBinding,
    EligibilityResult,
    EligibilityStatus,
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
    ServiceCaseStatus,
)
from customer_service.service_cases.service import ServiceCaseService
from customer_service.tools.schemas import AuthorizedOrderFacts, AuthorizedOrderItem

ROOT = Path(__file__).parents[3]
RULE_CASES_PATH = ROOT / "data" / "evaluation" / "rules" / "cases.v1.json"
JsonObject = dict[str, Any]


def load_cases() -> dict[str, JsonObject]:
    document = json.loads(RULE_CASES_PATH.read_text(encoding="utf-8"))
    return {
        str(case["case_id"]): cast(JsonObject, case)
        for case in document["cases"]
        if "service_case_creation" in case["tags"]
    }


CASES = load_cases()


def authorized_order(
    order_id: str, *, order_item_id: str = "ITEM-NORMAL-001"
) -> AuthorizedOrderFacts:
    return AuthorizedOrderFacts(
        order_id=order_id,
        status="delivered",
        placed_at=datetime.fromisoformat("2026-07-15T09:00:00+00:00"),
        delivered_at=datetime.fromisoformat("2026-07-18T10:00:00+00:00"),
        currency="CNY",
        total_amount="129.00",
        items=(
            AuthorizedOrderItem(
                order_item_id=order_item_id,
                product_id="PROD-GENERAL-001",
                quantity=1,
                unit_price="129.00",
                line_total="129.00",
            ),
        ),
    )


def eligible_result(bound_order: AuthorizedOrderFacts) -> EligibilityResult:
    item = bound_order.items[0]
    return EligibilityResult(
        rule_version="1.0.0",
        status=EligibilityStatus.ELIGIBLE,
        eligibility=EligibilityConclusion.ELIGIBLE,
        applicable_policy_ids=("POL-ACTIVE-STANDARD-001",),
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


def test_t002_normal_case_creates_one_case_through_public_service() -> None:
    case = CASES["AC-FR07-N-001"]
    order_id = str(case["user_input"]["required_entities"]["order_id"])
    repository = InMemoryServiceCaseRepository()
    result = ServiceCaseService(repository).create(
        ServiceCaseCreateRequest(
            order=authorized_order(order_id),
            order_item_id="ITEM-NORMAL-001",
        ),
        access_context=ServiceCaseAccessContext(current_user_id="USR-DEMO-001"),
        eligibility_context=ServiceCaseEligibilityContext(
            eligibility=eligible_result(authorized_order(order_id))
        ),
    )

    assert result.status is ServiceCaseStatus.CREATED
    assert result.service_case is not None
    assert result.service_case.status == "created"
    expected_effects = case["expected_terminal_state"]["business_effects"]
    assert repository.case_count == expected_effects["service_cases_created"]


def test_t002_duplicate_case_returns_existing_seeded_result() -> None:
    case = CASES["AC-FR07-E-001"]
    repository = InMemoryServiceCaseRepository.from_manifest(ROOT / "data" / "manifest.json")
    result = ServiceCaseService(repository).create(
        ServiceCaseCreateRequest(
            order=authorized_order("ORD-EXISTING-CASE-001", order_item_id="ITEM-EXISTING-CASE-001"),
            order_item_id="ITEM-EXISTING-CASE-001",
        ),
        access_context=ServiceCaseAccessContext(current_user_id="USR-DEMO-001"),
        eligibility_context=ServiceCaseEligibilityContext(
            eligibility=eligible_result(
                authorized_order("ORD-EXISTING-CASE-001", order_item_id="ITEM-EXISTING-CASE-001")
            )
        ),
    )

    assert result.status is ServiceCaseStatus.EXISTING
    assert result.service_case is not None
    assert result.service_case.service_case_id == "SC-DEMO-001"
    assert repository.case_count == 1
    assert case["expected_terminal_state"]["business_effects"]["service_cases_created"] == 0


class FailingRepository(InMemoryServiceCaseRepository):
    def create(self, *, draft: ServiceCaseDraft) -> StoredServiceCase | None:
        del draft
        raise RuntimeError("write failure")


def test_t002_failed_write_does_not_claim_completion() -> None:
    case = CASES["AC-FR07-E-002"]
    result = ServiceCaseService(FailingRepository()).create(
        ServiceCaseCreateRequest(
            order=authorized_order("ORD-NORMAL-001"),
            order_item_id="ITEM-NORMAL-001",
        ),
        access_context=ServiceCaseAccessContext(current_user_id="USR-DEMO-001"),
        eligibility_context=ServiceCaseEligibilityContext(
            eligibility=eligible_result(authorized_order("ORD-NORMAL-001"))
        ),
    )

    assert result.status is ServiceCaseStatus.FAILED_SAFE
    assert result.service_case is None
    public_text = result.model_dump_json()
    for forbidden in case["expected_terminal_state"]["must_not_include"]:
        assert forbidden not in public_text
