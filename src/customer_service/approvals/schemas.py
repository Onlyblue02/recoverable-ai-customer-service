from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from customer_service.eligibility.schemas import EligibilityResult
from customer_service.rag.schemas import PolicyCitation
from customer_service.tools.schemas import AuthorizedOrderFacts


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    ADJUSTED = "adjusted"
    REJECTED = "rejected"


class ApprovalDecision(StrEnum):
    APPROVE = "approve"
    ADJUST = "adjust"
    REJECT = "reject"


class ApprovalTaskResultStatus(StrEnum):
    CREATED = "created"
    EXISTING = "existing"
    DECIDED = "decided"
    BLOCKED = "blocked"
    CONFLICT = "conflict"
    FAILED_SAFE = "failed_safe"


class ApprovalErrorCode(StrEnum):
    APPROVAL_NOT_REQUIRED = "APPROVAL_NOT_REQUIRED"
    APPROVAL_CONTEXT_MISMATCH = "APPROVAL_CONTEXT_MISMATCH"
    APPROVAL_NOT_FOUND = "APPROVAL_NOT_FOUND"
    APPROVAL_ALREADY_DECIDED = "APPROVAL_ALREADY_DECIDED"
    APPROVAL_VERSION_CONFLICT = "APPROVAL_VERSION_CONFLICT"
    APPROVAL_WRITE_FAILED = "APPROVAL_WRITE_FAILED"


class ApprovalTaskCreateRequest(BaseModel):
    """Only a server-generated concise conversation summary is accepted here."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    conversation_summary: str = Field(min_length=1, max_length=500)

    @field_validator("conversation_summary")
    @classmethod
    def normalize_summary(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("conversation_summary must not be blank")
        return normalized


class ApprovalTaskContext(BaseModel):
    """Trusted evidence injected by the application, never supplied by a decision payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    current_user_id: str = Field(min_length=1)
    order: AuthorizedOrderFacts
    order_item_id: str = Field(min_length=1)
    eligibility: EligibilityResult
    policy_citations: tuple[PolicyCitation, ...] = Field(min_length=1)

    @field_validator("current_user_id", "order_item_id")
    @classmethod
    def normalize_identifier(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("identifier must not be blank")
        return normalized


class ApprovalActorContext(BaseModel):
    """Trusted human-agent identity, separate from the public decision payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    actor_id: str = Field(min_length=1)

    @field_validator("actor_id")
    @classmethod
    def normalize_actor_id(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("actor_id must not be blank")
        return normalized


class ApprovalDecisionRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: ApprovalDecision
    note: str = Field(min_length=1, max_length=500)
    recommendation: str | None = Field(default=None, max_length=500)
    expected_version: int = Field(ge=1)

    @field_validator("note", "recommendation")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("text must not be blank")
        return normalized

    @model_validator(mode="after")
    def validate_adjustment(self) -> Self:
        if self.decision is ApprovalDecision.ADJUST and self.recommendation is None:
            raise ValueError("adjust decision requires a recommendation")
        if self.decision is not ApprovalDecision.ADJUST and self.recommendation is not None:
            raise ValueError("only adjust decision may include a recommendation")
        return self


class ApprovalTaskSummary(BaseModel):
    """Whitelisted approval facts required for a human to make one decision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    approval_id: str = Field(min_length=1)
    status: ApprovalStatus
    version: int = Field(ge=1)
    conversation_summary: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    order: AuthorizedOrderFacts
    order_item_id: str = Field(min_length=1)
    policy_citations: tuple[PolicyCitation, ...] = Field(min_length=1)
    eligibility: EligibilityResult
    risk_reasons: tuple[str, ...] = Field(min_length=1)
    decision: ApprovalDecision | None
    note: str | None
    recommendation: str | None
    decided_by: str | None
    decided_at: datetime | None

    @model_validator(mode="after")
    def validate_decision_fields(self) -> Self:
        decided = self.status is not ApprovalStatus.PENDING
        fields = (self.decision, self.note, self.decided_by, self.decided_at)
        if decided and any(value is None for value in fields):
            raise ValueError("terminal approval requires a recorded decision")
        if not decided and any(value is not None for value in fields):
            raise ValueError("pending approval cannot contain a decision")
        return self


class ApprovalTaskResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: ApprovalTaskResultStatus
    error_code: ApprovalErrorCode | None
    message: str = Field(min_length=1)
    approval: ApprovalTaskSummary | None

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        successful = {
            ApprovalTaskResultStatus.CREATED,
            ApprovalTaskResultStatus.EXISTING,
            ApprovalTaskResultStatus.DECIDED,
        }
        if self.status in successful:
            if self.error_code is not None or self.approval is None:
                raise ValueError("successful approval result requires a task")
        elif self.error_code is None or self.approval is not None:
            raise ValueError("non-success approval result requires error and no task")
        return self
