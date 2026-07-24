from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from customer_service.eligibility.schemas import ReturnReason


class ItemCondition(StrEnum):
    RESALABLE = "resalable"
    NOT_RESALABLE = "not_resalable"


class CollectionSlot(StrEnum):
    ORDER_ID = "order_id"
    RETURN_REASON = "return_reason"
    ITEM_CONDITION = "item_condition"


class CollectionStage(StrEnum):
    COLLECTING_INFORMATION = "COLLECTING_INFORMATION"
    EVALUATING = "EVALUATING"


class CollectionRequest(BaseModel):
    """Public message input; confirmed slots come only from trusted context."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    message: str = Field(min_length=1)

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("message must not be blank")
        return normalized


class SlotRevision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    slot: CollectionSlot
    previous_value: str
    new_value: str
    sequence: int = Field(ge=1)


class CollectionContext(BaseModel):
    """Server-injected confirmed slots and immutable revision history."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    order_id: str | None = None
    return_reason: ReturnReason | None = None
    item_condition: ItemCondition | None = None
    revisions: tuple[SlotRevision, ...] = ()

    @field_validator("order_id")
    @classmethod
    def normalize_order_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        return normalized or None


class CollectionResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: CollectionStage
    order_id: str | None
    return_reason: ReturnReason | None
    item_condition: ItemCondition | None
    missing_slot: CollectionSlot | None
    updated_slots: tuple[CollectionSlot, ...]
    revisions: tuple[SlotRevision, ...]
    business_operation_requested: bool
    message: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_collection_contract(self) -> Self:
        complete = all((self.order_id, self.return_reason, self.item_condition))
        if self.business_operation_requested:
            raise ValueError("collection cannot request a business operation")
        if self.stage is CollectionStage.EVALUATING:
            if not complete or self.missing_slot is not None:
                raise ValueError("ready collection result must have complete slots")
        elif complete or self.missing_slot is None:
            raise ValueError("collecting result must identify one missing slot")
        return self
