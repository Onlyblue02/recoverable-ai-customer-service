from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

MONEY_PATTERN = r"^(0|[1-9][0-9]*)\.[0-9]{2}$"


class StoredUser(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    user_id: str = Field(min_length=1)


class StoredOrderItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    order_item_id: str = Field(min_length=1)
    product_id: str = Field(min_length=1)
    quantity: int = Field(gt=0)
    unit_price: str = Field(pattern=MONEY_PATTERN)
    line_total: str = Field(pattern=MONEY_PATTERN)


class StoredOrder(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    order_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    placed_at: datetime
    delivered_at: datetime | None
    currency: str = Field(min_length=3, max_length=3)
    total_amount: str = Field(pattern=MONEY_PATTERN)
    items: tuple[StoredOrderItem, ...] = Field(min_length=1)


class OrderItemResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    order_item_id: str
    product_id: str
    quantity: int
    unit_price: str
    line_total: str


class OrderResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    order_id: str
    status: str
    placed_at: datetime
    delivered_at: datetime | None
    currency: str
    total_amount: str
    items: tuple[OrderItemResponse, ...]

    @classmethod
    def from_stored(cls, order: StoredOrder) -> "OrderResponse":
        return cls(
            order_id=order.order_id,
            status=order.status,
            placed_at=order.placed_at,
            delivered_at=order.delivered_at,
            currency=order.currency,
            total_amount=order.total_amount,
            items=tuple(
                OrderItemResponse(
                    order_item_id=item.order_item_id,
                    product_id=item.product_id,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    line_total=item.line_total,
                )
                for item in order.items
            ),
        )


class OrderBoundaryErrorCode(StrEnum):
    ORDER_UNAVAILABLE = "ORDER_UNAVAILABLE"


class OrderErrorResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    error_code: OrderBoundaryErrorCode
    message: str = Field(min_length=1)
