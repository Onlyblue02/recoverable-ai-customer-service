import json
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from customer_service.infrastructure.clients.mock_business import HttpOrderGateway
from customer_service.tools.order_tool import OrderGateway, OrderGatewayOutcome, OrderQueryService
from customer_service.tools.schemas import (
    OrderAccessContext,
    OrderErrorCode,
    OrderQuery,
    OrderQueryStatus,
)
from mock_business.main import create_app

ROOT = Path(__file__).parents[3]
DATA_ROOT = ROOT / "data"
RETRIEVAL_CASES_PATH = DATA_ROOT / "evaluation" / "retrieval" / "cases.v1.json"

JsonObject = dict[str, Any]


def load_order_cases() -> dict[str, JsonObject]:
    document = json.loads(RETRIEVAL_CASES_PATH.read_text(encoding="utf-8"))
    return {
        str(case["case_id"]): cast(JsonObject, case)
        for case in document["cases"]
        if "order_query" in case["tags"]
    }


ORDER_CASES = load_order_cases()
EXPECTED_RESULTS = {
    "AC-FR04-N-001": (OrderQueryStatus.FOUND, None),
    "AC-FR04-E-001": (
        OrderQueryStatus.MISSING_ORDER_ID,
        OrderErrorCode.MISSING_ORDER_ID,
    ),
    "AC-FR04-E-002": (
        OrderQueryStatus.ORDER_UNAVAILABLE,
        OrderErrorCode.ORDER_UNAVAILABLE,
    ),
    "AC-FR04-E-003": (
        OrderQueryStatus.ORDER_UNAVAILABLE,
        OrderErrorCode.ORDER_UNAVAILABLE,
    ),
}


class CountingGateway:
    def __init__(self, delegate: OrderGateway) -> None:
        self._delegate = delegate
        self.calls: list[tuple[str, str]] = []

    def lookup(self, *, current_user_id: str, order_id: str) -> OrderGatewayOutcome:
        self.calls.append((current_user_id, order_id))
        return self._delegate.lookup(current_user_id=current_user_id, order_id=order_id)


@pytest.mark.parametrize("case_id", sorted(EXPECTED_RESULTS))
def test_t002_order_cases_through_public_service_and_mock_boundary(case_id: str) -> None:
    case = ORDER_CASES[case_id]
    current_user_id = str(case["preconditions"]["initial_state"]["requesting_user_id"])
    raw_order_id = case["user_input"]["required_entities"]["order_id"]
    order_id = str(raw_order_id) if raw_order_id is not None else None

    with TestClient(create_app(manifest_path=DATA_ROOT / "manifest.json")) as client:
        gateway = CountingGateway(HttpOrderGateway(client))
        service = OrderQueryService(gateway)
        result = service.query(
            OrderQuery(order_id=order_id),
            access_context=OrderAccessContext(current_user_id=current_user_id),
        )

    expected_status, expected_error = EXPECTED_RESULTS[case_id]
    assert result.status is expected_status
    assert result.error_code is expected_error

    if order_id is None:
        assert gateway.calls == []
    else:
        assert gateway.calls == [(current_user_id, order_id)]

    public_text = f"{result.message} {result.model_dump_json()}"
    if case_id in {"AC-FR04-E-002", "AC-FR04-E-003"}:
        assert "无法访问该订单" in public_text
    else:
        for required_text in case["expected_terminal_state"]["must_include"]:
            assert required_text in public_text
    for forbidden_text in case["expected_terminal_state"]["must_not_include"]:
        assert forbidden_text not in public_text


def test_authorized_public_service_result_has_exact_field_whitelist() -> None:
    with TestClient(create_app(manifest_path=DATA_ROOT / "manifest.json")) as client:
        result = OrderQueryService(HttpOrderGateway(client)).query(
            OrderQuery(order_id="ORD-QUALITY-001"),
            access_context=OrderAccessContext(current_user_id="USR-DEMO-001"),
        )

    assert result.status is OrderQueryStatus.FOUND
    assert result.order is not None
    payload = result.order.model_dump(mode="json")
    assert set(payload) == {
        "order_id",
        "status",
        "placed_at",
        "delivered_at",
        "currency",
        "total_amount",
        "items",
    }
    serialized = result.model_dump_json()
    for forbidden in (
        "user_id",
        "scenario_tags",
        "business_purpose",
        "expected_behavior",
        "synthetic_issue",
        "AUDIO_LEFT_CHANNEL_SILENT",
    ):
        assert forbidden not in serialized


@pytest.mark.parametrize(
    ("current_user_id", "order_id"),
    [
        ("USR-DEMO-001", "ORD-NOT-FOUND-001"),
        ("USR-DEMO-001", "ORD-OTHER-USER-001"),
    ],
)
def test_mock_business_error_payloads_do_not_contain_order_details(
    current_user_id: str,
    order_id: str,
) -> None:
    with TestClient(create_app(manifest_path=DATA_ROOT / "manifest.json")) as client:
        response = client.get(
            f"/orders/{order_id}",
            params={"current_user_id": current_user_id},
        )

    assert response.status_code == 404
    assert set(response.json()) == {"error_code", "message"}
    assert response.json() == {
        "error_code": "ORDER_UNAVAILABLE",
        "message": "无法访问该订单。",
    }
    serialized = response.text
    for forbidden in (
        "演示旅行杯",
        "89.00",
        "USR-DEMO-002",
        "delivered_at",
        "total_amount",
    ):
        assert forbidden not in serialized


def test_t002_order_cases_are_selected_by_semantics_not_exact_utterance() -> None:
    assert set(ORDER_CASES) == set(EXPECTED_RESULTS)
    for case in ORDER_CASES.values():
        assert case["user_input"]["acceptance_basis"] == "semantic_match"
        assert len(case["user_input"]["utterance_examples"]) >= 2
