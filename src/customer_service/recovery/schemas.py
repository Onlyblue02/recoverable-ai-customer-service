from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from customer_service.approvals.schemas import ApprovalTaskSummary
from customer_service.service_cases.schemas import ServiceCaseSummary


class RecoveryStage(StrEnum):
    WAITING_APPROVAL = "WAITING_APPROVAL"
    READY_TO_RESUME = "READY_TO_RESUME"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"
    FAILED_SAFE = "FAILED_SAFE"


class RecoveryErrorCode(StrEnum):
    CHECKPOINT_NOT_FOUND = "CHECKPOINT_NOT_FOUND"
    CHECKPOINT_CONTEXT_MISMATCH = "CHECKPOINT_CONTEXT_MISMATCH"
    APPROVAL_NOT_FOUND = "APPROVAL_NOT_FOUND"
    APPROVAL_CONTEXT_MISMATCH = "APPROVAL_CONTEXT_MISMATCH"
    OPERATION_STATE_UNKNOWN = "OPERATION_STATE_UNKNOWN"
    WORKFLOW_VERSION_MISMATCH = "WORKFLOW_VERSION_MISMATCH"
    CHECKPOINT_VERSION_CONFLICT = "CHECKPOINT_VERSION_CONFLICT"
    CHECKPOINT_UNAVAILABLE = "CHECKPOINT_UNAVAILABLE"


class RecoveryAccessContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    current_user_id: str = Field(min_length=1)

    @field_validator("current_user_id")
    @classmethod
    def normalize(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("current_user_id must not be blank")
        return normalized


class RecoveryCheckpointRequest(BaseModel):
    """Public recovery input contains references only, never mutable business facts."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    workflow_id: str = Field(min_length=1)
    approval_id: str = Field(min_length=1)

    @field_validator("workflow_id", "approval_id")
    @classmethod
    def normalize_identifier(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("identifier must not be blank")
        return normalized


class RecoveryResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    stage: RecoveryStage
    error_code: RecoveryErrorCode | None
    message: str = Field(min_length=1)
    workflow_id: str | None
    approval: ApprovalTaskSummary | None
    service_case: ServiceCaseSummary | None

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if self.stage is RecoveryStage.FAILED_SAFE:
            if self.error_code is None or any((self.workflow_id, self.approval, self.service_case)):
                raise ValueError("safe failure contains no business facts")
        elif self.error_code is not None or self.workflow_id is None or self.approval is None:
            raise ValueError("recovered result requires trusted checkpoint facts")
        return self
