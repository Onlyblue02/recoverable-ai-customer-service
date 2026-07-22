from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from customer_service.infrastructure.clients.mock_business import HttpOrderGateway
from customer_service.tools.order_tool import OrderQueryService
from customer_service.tools.schemas import (
    OrderAccessContext,
    OrderErrorCode,
    OrderQuery,
    OrderQueryStatus,
)
from mock_business.main import create_app

ROOT = Path(__file__).parents[3]
DATA_MANIFEST = ROOT / "data" / "manifest.json"


def test_forged_identity_cannot_override_trusted_access_context() -> None:
    with pytest.raises(ValidationError):
        OrderQuery.model_validate(
            {
                "order_id": "ORD-OTHER-USER-001",
                "current_user_id": "USR-DEMO-002",
            }
        )

    with TestClient(create_app(manifest_path=DATA_MANIFEST)) as client:
        result = OrderQueryService(HttpOrderGateway(client)).query(
            OrderQuery(order_id="ORD-OTHER-USER-001"),
            access_context=OrderAccessContext(current_user_id="USR-DEMO-001"),
        )

    assert result.status is OrderQueryStatus.ORDER_UNAVAILABLE
    assert result.error_code is OrderErrorCode.ORDER_UNAVAILABLE
    assert result.order is None


def test_same_order_only_succeeds_for_server_side_owner_context() -> None:
    with TestClient(create_app(manifest_path=DATA_MANIFEST)) as client:
        service = OrderQueryService(HttpOrderGateway(client))
        nonowner = service.query(
            OrderQuery(order_id="ORD-OTHER-USER-001"),
            access_context=OrderAccessContext(current_user_id="USR-DEMO-001"),
        )
        owner = service.query(
            OrderQuery(order_id="ORD-OTHER-USER-001"),
            access_context=OrderAccessContext(current_user_id="USR-DEMO-002"),
        )

    assert nonowner.status is OrderQueryStatus.ORDER_UNAVAILABLE
    assert nonowner.order is None
    assert owner.status is OrderQueryStatus.FOUND
    assert owner.order is not None


def test_missing_and_unauthorized_are_publicly_indistinguishable() -> None:
    with TestClient(create_app(manifest_path=DATA_MANIFEST)) as client:
        service = OrderQueryService(HttpOrderGateway(client))
        context = OrderAccessContext(current_user_id="USR-DEMO-001")
        results = [
            service.query(OrderQuery(order_id=order_id), access_context=context)
            for order_id in (
                "ORD-NOT-FOUND-001",
                "ORD-OTHER-USER-001",
                "ORD-DOES-NOT-EXIST-002",
            )
        ]

    public_payloads = [result.model_dump(mode="json") for result in results]
    assert public_payloads[0] == public_payloads[1] == public_payloads[2]
    assert set(public_payloads[0]) == {"status", "error_code", "message", "order"}
    serialized = " ".join(result.model_dump_json() for result in results)
    for forbidden in (
        "USR-DEMO-002",
        "89.00",
        "delivered",
        "placed_at",
        "total_amount",
        "存在",
        "无权",
    ):
        assert forbidden not in serialized


class BrokenTransport(httpx.BaseTransport):
    def __init__(self, failure: Exception | httpx.Response) -> None:
        self._failure = failure
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if isinstance(self._failure, Exception):
            raise self._failure
        return self._failure


def order_payload(
    *,
    order_id: str,
    total_amount: str = "129.00",
    product_id: str = "PROD-GENERAL-001",
) -> dict[str, object]:
    return {
        "order_id": order_id,
        "status": "delivered",
        "placed_at": "2026-07-15T09:00:00Z",
        "delivered_at": "2026-07-18T10:00:00Z",
        "currency": "CNY",
        "total_amount": total_amount,
        "items": [
            {
                "order_item_id": "ITEM-RESPONSE-001",
                "product_id": product_id,
                "quantity": 1,
                "unit_price": total_amount,
                "line_total": total_amount,
            }
        ],
    }


def test_mismatched_success_order_is_rejected_without_leaking_returned_facts() -> None:
    transport = BrokenTransport(
        httpx.Response(
            200,
            json=order_payload(
                order_id="ORD-OTHER-USER-001",
                total_amount="89.00",
                product_id="PROD-TRAVEL-MUG-001",
            ),
        )
    )
    with httpx.Client(transport=transport, base_url="http://mock-business") as client:
        result = OrderQueryService(HttpOrderGateway(client)).query(
            OrderQuery(order_id="ORD-NORMAL-001"),
            access_context=OrderAccessContext(current_user_id="USR-DEMO-001"),
        )

    assert result.status is OrderQueryStatus.DEPENDENCY_FAILURE
    assert result.error_code is OrderErrorCode.ORDER_LOOKUP_UNAVAILABLE
    assert result.order is None
    serialized = result.model_dump_json()
    for leaked_fact in (
        "ORD-OTHER-USER-001",
        "89.00",
        "PROD-TRAVEL-MUG-001",
        "delivered",
        "2026-07-15",
    ):
        assert leaked_fact not in serialized


def test_matching_success_order_uses_normalized_request_order_id() -> None:
    transport = BrokenTransport(httpx.Response(200, json=order_payload(order_id="ORD-NORMAL-001")))
    with httpx.Client(transport=transport, base_url="http://mock-business") as client:
        result = OrderQueryService(HttpOrderGateway(client)).query(
            OrderQuery(order_id="  ORD-NORMAL-001  "),
            access_context=OrderAccessContext(current_user_id="USR-DEMO-001"),
        )

    assert result.status is OrderQueryStatus.FOUND
    assert result.error_code is None
    assert result.order is not None
    assert result.order.order_id == "ORD-NORMAL-001"
    assert transport.requests[0].url.path == "/orders/ORD-NORMAL-001"


@pytest.mark.parametrize(
    "failure",
    [
        httpx.ConnectError("host=db.internal password=secret"),
        httpx.ReadTimeout("url=http://internal/orders owner=USR-DEMO-002"),
        httpx.Response(200, content=b"not-json"),
        httpx.Response(502, text="password=secret host=db.internal"),
        httpx.Response(
            404,
            json={"error_code": "ORDER_ACCESS_DENIED", "message": "owner=USR-DEMO-002"},
        ),
    ],
    ids=["connect", "timeout", "invalid-json", "unexpected-status", "wrong-error-code"],
)
def test_http_and_contract_failures_return_safe_stable_result(
    failure: Exception | httpx.Response,
) -> None:
    with httpx.Client(
        transport=BrokenTransport(failure), base_url="http://mock-business"
    ) as client:
        service = OrderQueryService(HttpOrderGateway(client))
        context = OrderAccessContext(current_user_id="USR-DEMO-001")
        result = service.query(OrderQuery(order_id="ORD-NORMAL-001"), access_context=context)

    assert result.status is OrderQueryStatus.DEPENDENCY_FAILURE
    assert result.error_code is OrderErrorCode.ORDER_LOOKUP_UNAVAILABLE
    assert result.order is None
    assert result.message == "订单查询服务暂时不可用，请稍后重试。"
    serialized = result.model_dump_json()
    for secret in (
        "password",
        "secret",
        "db.internal",
        "http://internal",
        "USR-DEMO-002",
        "owner",
    ):
        assert secret not in serialized
