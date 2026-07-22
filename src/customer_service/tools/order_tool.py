from enum import StrEnum
from typing import Protocol, Self

from pydantic import BaseModel, ConfigDict, model_validator

from customer_service.tools.schemas import (
    AuthorizedOrderFacts,
    OrderAccessContext,
    OrderErrorCode,
    OrderQuery,
    OrderQueryResult,
    OrderQueryStatus,
)


class OrderGatewayStatus(StrEnum):
    FOUND = "found"
    NOT_FOUND = "not_found"
    UNAUTHORIZED = "unauthorized"


class OrderGatewayOutcome(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: OrderGatewayStatus
    order: AuthorizedOrderFacts | None = None

    @model_validator(mode="after")
    def validate_outcome_contract(self) -> Self:
        if self.status is OrderGatewayStatus.FOUND:
            if self.order is None:
                raise ValueError("found gateway outcome requires order facts")
        elif self.order is not None:
            raise ValueError("failed gateway outcome cannot contain order facts")
        return self


class OrderGateway(Protocol):
    def lookup(self, *, current_user_id: str, order_id: str) -> OrderGatewayOutcome: ...


class OrderQueryService:
    def __init__(self, gateway: OrderGateway) -> None:
        self._gateway = gateway

    def query(
        self,
        query: OrderQuery,
        *,
        access_context: OrderAccessContext,
    ) -> OrderQueryResult:
        if query.order_id is None or not query.order_id.strip():
            return OrderQueryResult(
                status=OrderQueryStatus.MISSING_ORDER_ID,
                error_code=OrderErrorCode.MISSING_ORDER_ID,
                message="请提供订单号。",
                order=None,
            )

        order_id = query.order_id.strip()
        try:
            outcome = self._gateway.lookup(
                current_user_id=access_context.current_user_id,
                order_id=order_id,
            )
        except Exception:
            return OrderQueryResult(
                status=OrderQueryStatus.DEPENDENCY_FAILURE,
                error_code=OrderErrorCode.ORDER_LOOKUP_UNAVAILABLE,
                message="订单查询服务暂时不可用，请稍后重试。",
                order=None,
            )
        if outcome.status is OrderGatewayStatus.FOUND:
            assert outcome.order is not None
            order = outcome.order
            return OrderQueryResult(
                status=OrderQueryStatus.FOUND,
                error_code=None,
                message=(
                    f"已找到订单 {order.order_id}：{order.status}，"
                    f"{order.total_amount} {order.currency}。"
                ),
                order=order,
            )
        return OrderQueryResult(
            status=OrderQueryStatus.ORDER_UNAVAILABLE,
            error_code=OrderErrorCode.ORDER_UNAVAILABLE,
            message="无法访问该订单。",
            order=None,
        )
