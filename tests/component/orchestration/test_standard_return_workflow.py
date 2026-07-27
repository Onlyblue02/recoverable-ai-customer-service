import json
from pathlib import Path
from typing import Any, cast

from fastapi.testclient import TestClient

from customer_service.collection.schemas import CollectionContext, ItemCondition
from customer_service.collection.service import ReturnInformationCollectionService
from customer_service.eligibility.config import EligibilityRuleConfig
from customer_service.eligibility.engine import EligibilityEngine
from customer_service.eligibility.schemas import ReturnReason
from customer_service.infrastructure.clients.mock_business import HttpOrderGateway
from customer_service.orchestration.schemas import (
    StandardReturnContext,
    StandardReturnRequest,
    StandardReturnStatus,
)
from customer_service.orchestration.service import StandardReturnWorkflowService
from customer_service.rag.catalog import PolicyCatalog
from customer_service.rag.service import PolicyAnswerService
from customer_service.routing.service import IntentRoutingService
from customer_service.service_cases.repository import InMemoryServiceCaseRepository
from customer_service.service_cases.service import ServiceCaseService
from customer_service.tools.order_tool import OrderQueryService
from mock_business.main import create_app

ROOT = Path(__file__).parents[3]
DATA_ROOT = ROOT / "data"
CONFIG_PATH = ROOT / "config" / "return-eligibility-rules.v1.json"
STORIES_PATH = DATA_ROOT / "evaluation" / "e2e" / "stories.v1.json"
JsonObject = dict[str, Any]


def product_categories() -> dict[str, str]:
    document = json.loads(
        (DATA_ROOT / "seed" / "products" / "products.v1.json").read_text(encoding="utf-8")
    )
    return {
        str(product["product_id"]): str(product["category"]) for product in document["products"]
    }


def standard_story() -> JsonObject:
    document = json.loads(STORIES_PATH.read_text(encoding="utf-8"))
    return next(
        cast(JsonObject, case)
        for case in document["cases"]
        if case["case_id"] == "E2E-STANDARD-001"
    )


def workflow(repository: InMemoryServiceCaseRepository) -> StandardReturnWorkflowService:
    catalog = PolicyCatalog.from_manifest(DATA_ROOT / "manifest.json")
    client = TestClient(create_app(manifest_path=DATA_ROOT / "manifest.json"))
    return StandardReturnWorkflowService(
        router=IntentRoutingService(),
        collector=ReturnInformationCollectionService(),
        orders=OrderQueryService(HttpOrderGateway(client)),
        policies=PolicyAnswerService(catalog),
        policy_catalog=catalog,
        product_categories=product_categories(),
        eligibility=EligibilityEngine(EligibilityRuleConfig.from_json(CONFIG_PATH)),
        service_cases=ServiceCaseService(repository),
    )


def standard_context() -> StandardReturnContext:
    return StandardReturnContext(
        current_user_id="USR-DEMO-001",
        collection=CollectionContext(
            order_id="ORD-NORMAL-001",
            return_reason=ReturnReason.CHANGED_MIND,
            item_condition=ItemCondition.RESALABLE,
        ),
    )


def test_e2e_standard_story_completes_once_with_policy_evidence() -> None:
    story = standard_story()
    repository = InMemoryServiceCaseRepository()
    result = workflow(repository).advance(
        StandardReturnRequest(message="继续处理我的退货申请"), context=standard_context()
    )

    assert result.status is StandardReturnStatus.COMPLETED
    assert result.service_case is not None
    assert result.policy_citations[0].policy_id == "POL-ACTIVE-STANDARD-001"
    assert result.eligibility is not None
    assert result.eligibility.status.value == "eligible"
    assert (
        repository.case_count
        == story["expected_terminal_state"]["business_effects"]["service_cases_created"]
    )


def test_repeated_standard_workflow_returns_same_case() -> None:
    repository = InMemoryServiceCaseRepository()
    service = workflow(repository)
    first = service.advance(StandardReturnRequest(message="继续退货"), context=standard_context())
    second = service.advance(StandardReturnRequest(message="继续退货"), context=standard_context())

    assert first.status is StandardReturnStatus.COMPLETED
    assert second.status is StandardReturnStatus.COMPLETED
    assert first.service_case is not None and second.service_case is not None
    assert first.service_case.service_case_id == second.service_case.service_case_id
    assert repository.case_count == 1


def test_missing_information_stops_before_order_lookup_or_case_creation() -> None:
    repository = InMemoryServiceCaseRepository()
    result = workflow(repository).advance(
        StandardReturnRequest(message="我要退货"),
        context=StandardReturnContext(current_user_id="USR-DEMO-001"),
    )

    assert result.status is StandardReturnStatus.COLLECTING_INFORMATION
    assert result.order is None
    assert result.service_case is None
    assert repository.case_count == 0


def test_unauthorized_order_does_not_expose_or_create_a_case() -> None:
    repository = InMemoryServiceCaseRepository()
    context = standard_context().model_copy(
        update={
            "collection": CollectionContext(
                order_id="ORD-OTHER-USER-001",
                return_reason=ReturnReason.CHANGED_MIND,
                item_condition=ItemCondition.RESALABLE,
            )
        }
    )
    result = workflow(repository).advance(
        StandardReturnRequest(message="继续退货"), context=context
    )

    assert result.status is StandardReturnStatus.ORDER_UNAVAILABLE
    assert result.order is None
    assert result.service_case is None
    assert "ORD-OTHER-USER-001" not in result.model_dump_json()
    assert repository.case_count == 0
