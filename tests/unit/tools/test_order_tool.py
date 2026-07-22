from datetime import datetime

import pytest
from pydantic import ValidationError

from customer_service.tools.order_tool import (
    OrderGatewayOutcome,
    OrderGatewayStatus,
    OrderQueryService,
)
from customer_service.tools.schemas import (
    AuthorizedOrderFacts,
    AuthorizedOrderItem,
    OrderAccessContext,
    OrderErrorCode,
    OrderQuery,
    OrderQueryResult,
    OrderQueryStatus,
)


def authorized_order() -> AuthorizedOrderFacts:
    return AuthorizedOrderFacts(
        order_id="ORD-NORMAL-001",
        status="delivered",
        placed_at=datetime.fromisoformat("2026-07-15T09:00:00+00:00"),
        delivered_at=datetime.fromisoformat("2026-07-18T10:00:00+00:00"),
        currency="CNY",
        total_amount="129.00",
        items=(
            AuthorizedOrderItem(
                order_item_id="ITEM-NORMAL-001",
                product_id="PROD-GENERAL-001",
                quantity=1,
                unit_price="129.00",
                line_total="129.00",
            ),
        ),
    )


class RecordingGateway:
    def __init__(self, outcome: OrderGatewayOutcome) -> None:
        self.outcome = outcome
        self.calls: list[tuple[str, str]] = []

    def lookup(self, *, current_user_id: str, order_id: str) -> OrderGatewayOutcome:
        self.calls.append((current_user_id, order_id))
        return self.outcome


@pytest.mark.parametrize("order_id", [None, "", "   "])
def test_missing_order_id_does_not_call_gateway(order_id: str | None) -> None:
    gateway = RecordingGateway(OrderGatewayOutcome(status=OrderGatewayStatus.NOT_FOUND))
    service = OrderQueryService(gateway)

    result = service.query(
        OrderQuery(order_id=order_id),
        access_context=OrderAccessContext(current_user_id="USR-DEMO-001"),
    )

    assert result.status is OrderQueryStatus.MISSING_ORDER_ID
    assert result.error_code is OrderErrorCode.MISSING_ORDER_ID
    assert result.order is None
    assert gateway.calls == []


def test_query_forwards_current_user_and_order_id_and_returns_whitelisted_facts() -> None:
    order = authorized_order()
    gateway = RecordingGateway(OrderGatewayOutcome(status=OrderGatewayStatus.FOUND, order=order))
    service = OrderQueryService(gateway)

    result = service.query(
        OrderQuery(order_id="ORD-NORMAL-001"),
        access_context=OrderAccessContext(current_user_id="USR-DEMO-001"),
    )

    assert gateway.calls == [("USR-DEMO-001", "ORD-NORMAL-001")]
    assert result.status is OrderQueryStatus.FOUND
    assert result.error_code is None
    assert result.order == order
    assert "ORD-NORMAL-001" in result.message
    assert "129.00 CNY" in result.message


@pytest.mark.parametrize(
    ("gateway_status", "expected_status", "expected_error"),
    [
        (
            OrderGatewayStatus.NOT_FOUND,
            OrderQueryStatus.ORDER_UNAVAILABLE,
            OrderErrorCode.ORDER_UNAVAILABLE,
        ),
        (
            OrderGatewayStatus.UNAUTHORIZED,
            OrderQueryStatus.ORDER_UNAVAILABLE,
            OrderErrorCode.ORDER_UNAVAILABLE,
        ),
    ],
)
def test_non_success_gateway_results_never_return_order_facts(
    gateway_status: OrderGatewayStatus,
    expected_status: OrderQueryStatus,
    expected_error: OrderErrorCode,
) -> None:
    gateway = RecordingGateway(OrderGatewayOutcome(status=gateway_status))
    service = OrderQueryService(gateway)

    result = service.query(
        OrderQuery(order_id="ORD-SOME-ID"),
        access_context=OrderAccessContext(current_user_id="USR-DEMO-001"),
    )

    assert result.status is expected_status
    assert result.error_code is expected_error
    assert result.order is None


def test_result_schema_rejects_failure_with_order_facts() -> None:
    with pytest.raises(ValidationError):
        OrderQueryResult(
            status=OrderQueryStatus.ORDER_UNAVAILABLE,
            error_code=OrderErrorCode.ORDER_UNAVAILABLE,
            message="无权查看该订单。",
            order=authorized_order(),
        )


@pytest.mark.parametrize("field", ["current_user_id", "owner_id", "authorized"])
def test_public_query_payload_rejects_identity_and_authorization_fields(field: str) -> None:
    with pytest.raises(ValidationError):
        OrderQuery.model_validate({"order_id": "ORD-NORMAL-001", field: "forged"})


def test_dependency_failure_is_stable_and_never_exposes_exception_details() -> None:
    class FailingGateway:
        def lookup(self, *, current_user_id: str, order_id: str) -> OrderGatewayOutcome:
            raise RuntimeError(
                "postgres password=secret host=db.internal "
                "url=http://internal/orders owner=USR-DEMO-002"
            )

    service = OrderQueryService(FailingGateway())
    access_context = OrderAccessContext(current_user_id="USR-DEMO-001")

    first = service.query(OrderQuery(order_id="ORD-NORMAL-001"), access_context=access_context)
    second = service.query(OrderQuery(order_id="ORD-NORMAL-001"), access_context=access_context)

    assert first == second
    assert first.status is OrderQueryStatus.DEPENDENCY_FAILURE
    assert first.error_code is OrderErrorCode.ORDER_LOOKUP_UNAVAILABLE
    assert first.order is None
    public_result = first.model_dump_json()
    for secret in (
        "password",
        "secret",
        "db.internal",
        "http://internal",
        "USR-DEMO-002",
    ):
        assert secret not in public_result


def test_result_schema_rejects_mismatched_dependency_failure_code() -> None:
    with pytest.raises(ValidationError):
        OrderQueryResult(
            status=OrderQueryStatus.DEPENDENCY_FAILURE,
            error_code=OrderErrorCode.ORDER_UNAVAILABLE,
            message="订单查询服务暂时不可用，请稍后重试。",
            order=None,
        )


def test_authorized_snapshot_exposes_only_explicit_whitelist() -> None:
    payload = authorized_order().model_dump(mode="json")

    assert set(payload) == {
        "order_id",
        "status",
        "placed_at",
        "delivered_at",
        "currency",
        "total_amount",
        "items",
    }
    assert set(payload["items"][0]) == {
        "order_item_id",
        "product_id",
        "quantity",
        "unit_price",
        "line_total",
    }
    serialized = authorized_order().model_dump_json()
    for forbidden in (
        "user_id",
        "scenario_tags",
        "business_purpose",
        "expected_behavior",
        "synthetic_issue",
    ):
        assert forbidden not in serialized
