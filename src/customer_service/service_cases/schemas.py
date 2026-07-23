from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from customer_service.eligibility.schemas import (
    EligibilityConclusion,
    EligibilityResult,
    EligibilityStatus,
)
from customer_service.tools.schemas import AuthorizedOrderFacts


class ServiceCaseStatus(StrEnum):
    CREATED = "created"
    EXISTING = "existing"
    BLOCKED = "blocked"
    FAILED_SAFE = "failed_safe"


class ServiceCaseErrorCode(StrEnum):
    ELIGIBILITY_NOT_CREATABLE = "ELIGIBILITY_NOT_CREATABLE"
    ORDER_ITEM_NOT_AUTHORIZED = "ORDER_ITEM_NOT_AUTHORIZED"
    SERVICE_CASE_WRITE_FAILED = "SERVICE_CASE_WRITE_FAILED"
    ELIGIBILITY_CONTEXT_MISMATCH = "ELIGIBILITY_CONTEXT_MISMATCH"


class ServiceCaseAccessContext(BaseModel):
    """Server-injected identity kept separate from the creation payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    current_user_id: str = Field(min_length=1)

    @field_validator("current_user_id")
    @classmethod
    def current_user_id_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("current_user_id must not be blank")
        return normalized


class ServiceCaseCreateRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    order: AuthorizedOrderFacts
    order_item_id: str = Field(min_length=1)

    @field_validator("order_item_id")
    @classmethod
    def identifiers_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("identifier must not be blank")
        return normalized


class ServiceCaseEligibilityContext(BaseModel):
    """Server-injected eligibility evidence, never part of the public payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    eligibility: EligibilityResult


class ServiceCaseSummary(BaseModel):
    """Whitelist of simulated case facts that may be returned publicly."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    service_case_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    order_id: str = Field(min_length=1)
    order_item_id: str = Field(min_length=1)

    @field_validator("service_case_id")
    @classmethod
    def service_case_id_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("service_case_id must not be blank")
        return value


class ServiceCaseResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: ServiceCaseStatus
    error_code: ServiceCaseErrorCode | None
    message: str = Field(min_length=1)
    service_case: ServiceCaseSummary | None

    @model_validator(mode="after")
    def validate_result_contract(self) -> Self:
        if self.status in (ServiceCaseStatus.CREATED, ServiceCaseStatus.EXISTING):
            if self.error_code is not None or self.service_case is None:
                raise ValueError("successful result requires a persisted service case")
        elif self.error_code is None or self.service_case is not None:
            raise ValueError("non-success result requires an error and no service case")
        return self


def eligibility_is_creatable(result: EligibilityResult) -> bool:
    return (
        result.status is EligibilityStatus.ELIGIBLE
        and result.eligibility is EligibilityConclusion.ELIGIBLE
        and not result.requires_human_approval
    )
