import json
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from customer_service.eligibility.config import EligibilityRuleConfig
from customer_service.eligibility.engine import EligibilityEngine
from customer_service.eligibility.schemas import (
    EligibilityItemFacts,
    EligibilityRequest,
    EligibilityStatus,
)
from customer_service.infrastructure.clients.mock_business import HttpOrderGateway
from customer_service.rag.catalog import PolicyCatalog
from customer_service.tools.order_tool import OrderQueryService
from customer_service.tools.schemas import OrderAccessContext, OrderQuery
from mock_business.main import create_app

ROOT = Path(__file__).parents[3]
DATA_ROOT = ROOT / "data"
RULE_CASES_PATH = DATA_ROOT / "evaluation" / "rules" / "cases.v1.json"
PRODUCTS_PATH = DATA_ROOT / "seed" / "products" / "products.v1.json"
CONFIG_PATH = ROOT / "config" / "return-eligibility-rules.v1.json"
JsonObject = dict[str, Any]


def load_cases() -> dict[str, JsonObject]:
    document = json.loads(RULE_CASES_PATH.read_text(encoding="utf-8"))
    return {
        str(case["case_id"]): cast(JsonObject, case)
        for case in document["cases"]
        if "return_eligibility" in case["tags"]
    }


def product_categories() -> dict[str, str]:
    document = json.loads(PRODUCTS_PATH.read_text(encoding="utf-8"))
    return {
        str(product["product_id"]): str(product["category"]) for product in document["products"]
    }


CASES = load_cases()
EXPECTED = {
    "AC-FR06-N-001": EligibilityStatus.ELIGIBLE,
    "AC-FR06-B-001": EligibilityStatus.ELIGIBLE,
    "AC-FR06-N-002": EligibilityStatus.VERIFICATION_REQUIRED,
    "AC-FR06-E-001": EligibilityStatus.REQUIRES_APPROVAL,
    "AC-FR06-E-002": EligibilityStatus.REQUIRES_APPROVAL,
}


@pytest.mark.parametrize("case_id", sorted(EXPECTED))
def test_t002_fixed_eligibility_case_through_public_engine(case_id: str) -> None:
    case = CASES[case_id]
    initial = case["preconditions"]["initial_state"]
    entities = case["user_input"]["required_entities"]
    user_id = str(case["preconditions"]["fixture_refs"]["user_ids"][0])
    order_id = str(entities["order_id"])

    with TestClient(create_app(manifest_path=DATA_ROOT / "manifest.json")) as client:
        order_result = OrderQueryService(HttpOrderGateway(client)).query(
            OrderQuery(order_id=order_id),
            access_context=OrderAccessContext(current_user_id=user_id),
        )
    assert order_result.order is not None
    order = order_result.order
    order_item = order.items[0]
    category = product_categories()[order_item.product_id]
    policy_ids = tuple(case["preconditions"]["fixture_refs"]["policy_ids"])
    catalog = PolicyCatalog.from_manifest(DATA_ROOT / "manifest.json")
    policies = tuple(policy for policy in catalog.policies if policy.policy_id in policy_ids)

    result = EligibilityEngine(EligibilityRuleConfig.from_json(CONFIG_PATH)).evaluate(
        EligibilityRequest(
            order=order,
            item=EligibilityItemFacts(
                order_item_id=order_item.order_item_id,
                product_id=order_item.product_id,
                category=category,
            ),
            return_reason=initial.get("return_reason", "changed_mind"),
            item_condition=initial.get("item_condition", "resalable"),
            issue_code=entities.get("issue_code"),
            policies=policies,
        )
    )

    assert result.status is EXPECTED[case_id]
    public_text = f"{result.message} {result.model_dump_json()}"
    for required in case["expected_terminal_state"]["must_include"]:
        assert required in public_text
    for forbidden in case["expected_terminal_state"]["must_not_include"]:
        assert forbidden not in public_text


def test_t002_eligibility_cases_are_selected_by_semantics() -> None:
    assert set(CASES) == set(EXPECTED)
    for case in CASES.values():
        assert case["user_input"]["acceptance_basis"] == "semantic_match"
