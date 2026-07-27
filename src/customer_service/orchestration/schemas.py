from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from customer_service.collection.schemas import CollectionContext, CollectionResult
from customer_service.eligibility.schemas import EligibilityResult
from customer_service.rag.schemas import PolicyCitation
from customer_service.service_cases.schemas import ServiceCaseSummary
from customer_service.tools.schemas import AuthorizedOrderFacts


class StandardReturnStatus(StrEnum):
    COLLECTING_INFORMATION = "COLLECTING_INFORMATION"
    ORDER_UNAVAILABLE = "ORDER_UNAVAILABLE"
    POLICY_UNAVAILABLE = "POLICY_UNAVAILABLE"
    REQUIRES_APPROVAL = "REQUIRES_APPROVAL"
    INELIGIBLE = "INELIGIBLE"
    CASE_CREATION_FAILED = "CASE_CREATION_FAILED"
    COMPLETED = "COMPLETED"


class StandardReturnRequest(BaseModel):
    """Public message only; identity, slots and target selection are trusted context."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    message: str = Field(min_length=1)

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("message must not be blank")
        return normalized


class StandardReturnContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    current_user_id: str = Field(min_length=1)
    collection: CollectionContext = Field(default_factory=CollectionContext)

    @field_validator("current_user_id")
    @classmethod
    def normalize_user_id(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("current_user_id must not be blank")
        return normalized


class StandardReturnResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: StandardReturnStatus
    message: str = Field(min_length=1)
    collection: CollectionResult | None
    order: AuthorizedOrderFacts | None
    policy_citations: tuple[PolicyCitation, ...]
    eligibility: EligibilityResult | None
    service_case: ServiceCaseSummary | None
    business_operation_requested: bool

    @model_validator(mode="after")
    def validate_contract(self) -> Self:
        if self.status is StandardReturnStatus.COMPLETED:
            if (
                self.order is None
                or self.collection is None
                or not self.policy_citations
                or self.eligibility is None
                or self.service_case is None
                or not self.business_operation_requested
            ):
                raise ValueError("completed result requires grounded successful facts")
        elif self.service_case is not None or self.business_operation_requested:
            raise ValueError("non-completed result cannot claim a service-case operation")
        return self
