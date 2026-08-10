from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ModelTask(StrEnum):
    INTENT_CLASSIFICATION = "intent_classification"
    RETURN_FIELD_EXTRACTION = "return_field_extraction"
    CORRECTION_RECOGNITION = "correction_recognition"
    GROUNDED_RESPONSE_GENERATION = "grounded_response_generation"
    AGENT_PLAN_GENERATION = "agent_plan_generation"
    AGENT_RESPONSE_DRAFT_GENERATION = "agent_response_draft_generation"


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
        evidence_tasks = {
            ModelTask.GROUNDED_RESPONSE_GENERATION,
            ModelTask.AGENT_RESPONSE_DRAFT_GENERATION,
        }
        if self.task in evidence_tasks and not self.evidence:
            raise ValueError("evidence-grounded generation requires evidence")
        if self.task not in evidence_tasks and self.evidence:
            raise ValueError("only evidence-grounded generation accepts evidence")
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


class AgentResponseClaim(BaseModel):
    """A language-level claim request; evidence remains server-authoritative."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_type: Literal["policy", "order", "eligibility", "approval", "completion"]
    evidence_ids: tuple[str, ...] = Field(min_length=1)


class AgentResponseDraftCandidate(BaseModel):
    """T-606 model draft. It contains no business objects or decision fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-response-draft-v1"]
    text: str = Field(min_length=1, max_length=2000)
    claims: tuple[AgentResponseClaim, ...] = ()


class AgentPlanCandidate(BaseModel):
    """Model suggestion only; it is not a tool invocation or business decision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-plan-v1"]
    intent: Literal["policy_question", "order_query", "return_request", "unknown"]
    requested_capability: Literal[
        "policy.lookup",
        "order.get_authorized",
        "return.evaluate",
        "clarify",
        "escalate",
    ]
    extracted_parameters: ReturnFieldCandidate = Field(default_factory=ReturnFieldCandidate)
    clarification_fields: tuple[Literal["order_id", "return_reason", "item_condition"], ...] = ()
    uncertainty_reason: (
        Literal["ambiguous_intent", "missing_information", "unsupported_request", "low_confidence"]
        | None
    ) = None


ModelOutput = Annotated[
    IntentCandidate
    | ReturnFieldCandidate
    | CorrectionCandidate
    | GroundedResponseDraft
    | AgentPlanCandidate
    | AgentResponseDraftCandidate,
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
