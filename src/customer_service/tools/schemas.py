from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MONEY_PATTERN = r"^(0|[1-9][0-9]*)\.[0-9]{2}$"


class OrderQueryStatus(StrEnum):
    FOUND = "found"
    MISSING_ORDER_ID = "missing_order_id"
    ORDER_UNAVAILABLE = "order_unavailable"
    DEPENDENCY_FAILURE = "dependency_failure"


class OrderErrorCode(StrEnum):
    MISSING_ORDER_ID = "MISSING_ORDER_ID"
    ORDER_UNAVAILABLE = "ORDER_UNAVAILABLE"
    ORDER_LOOKUP_UNAVAILABLE = "ORDER_LOOKUP_UNAVAILABLE"


class AuthorizedOrderItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    order_item_id: str = Field(min_length=1)
    product_id: str = Field(min_length=1)
    quantity: int = Field(gt=0)
    unit_price: str = Field(pattern=MONEY_PATTERN)
    line_total: str = Field(pattern=MONEY_PATTERN)


class AuthorizedOrderFacts(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    order_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    placed_at: datetime
    delivered_at: datetime | None
    currency: str = Field(min_length=3, max_length=3)
    total_amount: str = Field(pattern=MONEY_PATTERN)
    items: tuple[AuthorizedOrderItem, ...] = Field(min_length=1)


class OrderQuery(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    order_id: str | None = None


class OrderAccessContext(BaseModel):
    """Server-injected identity context, kept separate from user query payloads."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    current_user_id: str = Field(min_length=1)

    @field_validator("current_user_id")
    @classmethod
    def current_user_id_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("current_user_id must not be blank")
        return value


class OrderQueryResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: OrderQueryStatus
    error_code: OrderErrorCode | None
    message: str = Field(min_length=1)
    order: AuthorizedOrderFacts | None

    @model_validator(mode="after")
    def validate_result_contract(self) -> Self:
        expected_codes = {
            OrderQueryStatus.FOUND: None,
            OrderQueryStatus.MISSING_ORDER_ID: OrderErrorCode.MISSING_ORDER_ID,
            OrderQueryStatus.ORDER_UNAVAILABLE: OrderErrorCode.ORDER_UNAVAILABLE,
            OrderQueryStatus.DEPENDENCY_FAILURE: OrderErrorCode.ORDER_LOOKUP_UNAVAILABLE,
        }
        if self.error_code is not expected_codes[self.status]:
            raise ValueError("order query status and error_code do not match")
        if self.status is OrderQueryStatus.FOUND:
            if self.order is None:
                raise ValueError("found order result requires authorized order facts")
        elif self.order is not None:
            raise ValueError("failed order result cannot contain order facts")
        return self
