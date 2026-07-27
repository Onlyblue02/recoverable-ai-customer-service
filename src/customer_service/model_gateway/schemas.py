from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ModelTask(StrEnum):
    INTENT_CLASSIFICATION = "intent_classification"
    RETURN_FIELD_EXTRACTION = "return_field_extraction"
    CORRECTION_RECOGNITION = "correction_recognition"
    GROUNDED_RESPONSE_GENERATION = "grounded_response_generation"


class ModelResultStatus(StrEnum):
    SUCCEEDED = "succeeded"
    UNAVAILABLE = "unavailable"
    PROVIDER_FAILURE = "provider_failure"
    INVALID_OUTPUT = "invalid_output"


class EvidenceSnippet(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_id: str = Field(min_length=1)
    text: str = Field(min_length=1)


class ModelRequest(BaseModel):
    """A model may suggest only language-level facts, never business decisions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str = Field(min_length=1)
    task: ModelTask
    text: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    evidence: tuple[EvidenceSnippet, ...] = ()

    @model_validator(mode="after")
    def validate_evidence_scope(self) -> Self:
        if self.task is ModelTask.GROUNDED_RESPONSE_GENERATION and not self.evidence:
            raise ValueError("grounded response generation requires evidence")
        if self.task is not ModelTask.GROUNDED_RESPONSE_GENERATION and self.evidence:
            raise ValueError("only grounded response generation accepts evidence")
        return self


class IntentCandidate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    intent: Literal["policy_question", "order_query", "return_request", "unknown"]


class ReturnFieldCandidate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    order_id: str | None = None
    return_reason: Literal["changed_mind", "quality_issue"] | None = None
    item_condition: Literal["resalable", "not_resalable"] | None = None


class CorrectionCandidate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    corrected_slot: Literal["return_reason", "item_condition"] | None = None
    corrected_value: (
        Literal["changed_mind", "quality_issue", "resalable", "not_resalable"] | None
    ) = None

    @model_validator(mode="after")
    def validate_slot_value(self) -> Self:
        if (self.corrected_slot is None) != (self.corrected_value is None):
            raise ValueError("correction slot and value must be provided together")
        allowed = {
            "return_reason": {"changed_mind", "quality_issue"},
            "item_condition": {"resalable", "not_resalable"},
        }
        if self.corrected_slot and self.corrected_value not in allowed[self.corrected_slot]:
            raise ValueError("correction value does not belong to the corrected slot")
        return self


class GroundedResponseDraft(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = Field(min_length=1)
    evidence_ids: tuple[str, ...] = Field(min_length=1)


ModelOutput = Annotated[
    IntentCandidate | ReturnFieldCandidate | CorrectionCandidate | GroundedResponseDraft,
    Field(discriminator=None),
]


class ModelResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: ModelResultStatus
    task: ModelTask
    output: ModelOutput | None = None
    error_code: str | None = None
    message: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_response_contract(self) -> Self:
        if self.status is ModelResultStatus.SUCCEEDED:
            if self.output is None or self.error_code is not None:
                raise ValueError("successful model response requires only a structured output")
        elif self.output is not None or self.error_code is None:
            raise ValueError("failed model response cannot expose model output")
        return self
