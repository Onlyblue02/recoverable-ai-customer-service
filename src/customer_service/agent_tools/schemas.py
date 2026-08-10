"""Typed, static contracts for validating a T-603 candidate before any execution."""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from customer_service.agent_runtime.schemas import AgentStatus


class ToolEffect(StrEnum):
    READ_ONLY = "read_only"
    CONTROLLED_BUSINESS_REQUEST = "controlled_business_request"
    MODEL_FORBIDDEN_HIGH_RISK = "model_forbidden_high_risk"


class ParameterSource(StrEnum):
    USER_CANDIDATE = "user_candidate"
    CONFIRMED_FIELD = "confirmed_field"
    TRUSTED_TOOL_EVIDENCE = "trusted_tool_evidence"


class ToolId(StrEnum):
    POLICY_LOOKUP = "policy.lookup"
    ORDER_GET_AUTHORIZED = "order.get_authorized"
    RETURN_EVALUATE = "return.evaluate"
    SERVICE_CASE_CREATE = "service_case.create"
    HIGH_RISK_START_OR_GET = "high_risk.start_or_get"
    HIGH_RISK_RESUME = "high_risk.resume"
    APPROVAL_GET_STATUS = "approval.get_status"
    APPROVAL_DECIDE = "approval.decide"


class ToolContract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_id: ToolId
    version: Literal["tool-contract-v1"] = "tool-contract-v1"
    effect: ToolEffect
    allowed_states: tuple[AgentStatus, ...]
    model_parameter_names: tuple[Literal["order_id", "return_reason", "item_condition"], ...]
    required_parameter_names: tuple[Literal["order_id", "return_reason", "item_condition"], ...]
    allowed_sources: tuple[ParameterSource, ...]
    server_injected_fields: tuple[Literal["user_id", "workflow_id", "idempotency_key"], ...]
    budget_cost: int = Field(ge=1)
    callable_by_model_plan: bool


class TrustedParameter(BaseModel):
    """Server-owned context; callers cannot claim a source by modifying the model plan."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: Literal["order_id", "return_reason", "item_condition"]
    value: str
    source: ParameterSource


class PlanValidationContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_version: Literal["tool-policy-v1"] = "tool-policy-v1"
    trusted_parameters: tuple[TrustedParameter, ...] = ()
    executed_call_keys: tuple[str, ...] = ()
    authorized_user_id: str = Field(min_length=1)


class ValidatedToolStep(BaseModel):
    """Internal immutable result. It is deliberately not a callable or tool object."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_id: ToolId
    contract_version: Literal["tool-contract-v1"]
    parameters: tuple[TrustedParameter, ...]
    budget_cost: int
    call_key: str = Field(min_length=1)


class ExecutionPermit(BaseModel):
    """Opaque, validator-issued permission; a tool executor must verify it before dispatch."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    permit_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    turn_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    step: ValidatedToolStep
    proof: str = Field(min_length=1)


class EvidenceScope(StrEnum):
    TURN = "turn"
    WORKFLOW = "workflow"


class EvidenceStatus(StrEnum):
    ACTIVE = "active"
    INVALIDATED = "invalidated"
    NON_PUBLIC = "non_public"


class ToolResultStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    WRITE_STATUS_UNKNOWN = "write_status_unknown"


class EvidencePublicField(BaseModel):
    """Only these typed facts may later be considered for a public response."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: Literal[
        "policy_id",
        "policy_version",
        "order_id",
        "order_item_id",
        "eligibility_code",
        "approval_id",
        "service_case_id",
    ]
    value: str = Field(min_length=1)


class EvidenceIssue(BaseModel):
    """Internal post-tool input; it has no model, user, or raw-tool-response constructor."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    execution_id: str = Field(min_length=1)
    tool_id: ToolId
    contract_version: Literal["tool-contract-v1"]
    result_status: ToolResultStatus
    scope: EvidenceScope = EvidenceScope.TURN
    workflow_id: str | None = None
    order_id: str | None = None
    order_item_id: str | None = None
    public_fields: tuple[EvidencePublicField, ...] = ()
    expires_at: datetime


class TrustedExecutionReceipt(BaseModel):
    """Opaque-result envelope. A matching authority proof is required before issuance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    execution_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    turn_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    tool_id: ToolId
    contract_version: Literal["tool-contract-v1"]
    result_status: ToolResultStatus
    scope: EvidenceScope
    workflow_id: str | None = None
    order_id: str | None = None
    order_item_id: str | None = None
    public_fields: tuple[EvidencePublicField, ...] = ()
    expires_at: datetime
    proof: str = Field(min_length=1)


class EvidenceRecord(BaseModel):
    """Versioned internal evidence. Validity always requires authority verification."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    record_version: Literal["evidence-record-v1"] = "evidence-record-v1"
    evidence_id: str = Field(min_length=1)
    issuer: Literal["controlled_executor"] = "controlled_executor"
    execution_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    turn_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    tool_id: ToolId
    contract_version: Literal["tool-contract-v1"]
    scope: EvidenceScope
    workflow_id: str | None = None
    order_id: str | None = None
    order_item_id: str | None = None
    public_fields: tuple[EvidencePublicField, ...] = ()
    payload_digest: str = Field(min_length=1)
    expires_at: datetime
    status: EvidenceStatus = EvidenceStatus.ACTIVE
    invalidation_reason: str | None = None
    proof: str = Field(min_length=1)


class EvidenceBinding(BaseModel):
    """Trusted server context used to resolve an evidence ID in later tasks."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    conversation_id: str = Field(min_length=1)
    turn_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    order_id: str | None = None
    order_item_id: str | None = None
    workflow_id: str | None = None
    expected_tool_id: ToolId | None = None
    expected_contract_version: str | None = Field(default=None, min_length=1)
