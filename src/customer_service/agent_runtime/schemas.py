"""Typed, model-free contracts for the T-602 controlled execution skeleton."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class AgentStatus(StrEnum):
    RECEIVED = "RECEIVED"
    UNDERSTANDING = "UNDERSTANDING"
    PLANNING = "PLANNING"
    VALIDATING_PLAN = "VALIDATING_PLAN"
    EXECUTING = "EXECUTING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    DRAFTING = "DRAFTING"
    GATING = "GATING"
    CLARIFYING = "CLARIFYING"
    ESCALATING = "ESCALATING"
    FAILED_SAFE = "FAILED_SAFE"
    COMPLETED = "COMPLETED"


class AgentEventType(StrEnum):
    USER_MESSAGE = "user_message"
    MODEL_RESULT = "model_result"
    TOOL_RESULT = "tool_result"
    APPROVAL_DECIDED = "approval_decided"
    RESUME_REQUESTED = "resume_requested"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    CHECKPOINT_CONFLICT = "checkpoint_conflict"


class AgentReasonCode(StrEnum):
    TURN_ACCEPTED = "TURN_ACCEPTED"
    APPROVAL_STILL_PENDING = "APPROVAL_STILL_PENDING"
    MODEL_RESULT_ACCEPTED = "MODEL_RESULT_ACCEPTED"
    TOOL_RESULT_ACCEPTED = "TOOL_RESULT_ACCEPTED"
    APPROVAL_APPROVED = "APPROVAL_APPROVED"
    APPROVAL_ADJUSTED = "APPROVAL_ADJUSTED"
    APPROVAL_REJECTED = "APPROVAL_REJECTED"
    RESUME_APPROVED = "RESUME_APPROVED"
    RESUME_ADJUSTED = "RESUME_ADJUSTED"
    RESUME_REJECTED = "RESUME_REJECTED"
    MODEL_TIMEOUT = "MODEL_TIMEOUT"
    TOOL_TIMEOUT = "TOOL_TIMEOUT"
    TURN_CANCELLED = "TURN_CANCELLED"
    CANCELLATION_NOT_APPLICABLE = "CANCELLATION_NOT_APPLICABLE"
    CHECKPOINT_MISSING = "CHECKPOINT_MISSING"
    CHECKPOINT_CONFLICT = "CHECKPOINT_CONFLICT"
    CHECKPOINT_BINDING_MISMATCH = "CHECKPOINT_BINDING_MISMATCH"
    CHECKPOINT_VERSION_MISMATCH = "CHECKPOINT_VERSION_MISMATCH"
    UNTRUSTED_APPROVAL_EVENT = "UNTRUSTED_APPROVAL_EVENT"
    APPROVAL_ALREADY_DECIDED = "APPROVAL_ALREADY_DECIDED"
    ILLEGAL_TRANSITION = "ILLEGAL_TRANSITION"
    PLAN_LIMIT_EXCEEDED = "PLAN_LIMIT_EXCEEDED"
    TOOL_BUDGET_EXCEEDED = "TOOL_BUDGET_EXCEEDED"
    DUPLICATE_STEP = "DUPLICATE_STEP"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    PLAN_ACCEPTED = "PLAN_ACCEPTED"
    PLAN_NEEDS_CLARIFICATION = "PLAN_NEEDS_CLARIFICATION"
    PLAN_ESCALATED = "PLAN_ESCALATED"
    PLAN_MODEL_INVALID = "PLAN_MODEL_INVALID"
    PLAN_MODEL_UNAVAILABLE = "PLAN_MODEL_UNAVAILABLE"
    PLAN_POLICY_VIOLATION = "PLAN_POLICY_VIOLATION"
    PLAN_VALIDATED = "PLAN_VALIDATED"
    PLAN_CLARIFICATION_REQUIRED = "PLAN_CLARIFICATION_REQUIRED"
    TOOL_NOT_REGISTERED = "TOOL_NOT_REGISTERED"
    TOOL_FORBIDDEN = "TOOL_FORBIDDEN"
    TOOL_STATE_NOT_ALLOWED = "TOOL_STATE_NOT_ALLOWED"
    TOOL_PARAMETER_INVALID = "TOOL_PARAMETER_INVALID"
    TOOL_PARAMETER_SOURCE_UNTRUSTED = "TOOL_PARAMETER_SOURCE_UNTRUSTED"
    TOOL_PERMISSION_DENIED = "TOOL_PERMISSION_DENIED"
    TOOL_DUPLICATE_CALL = "TOOL_DUPLICATE_CALL"


class DeterministicStep(StrEnum):
    """No-op placeholders; T-604 alone may introduce real tool registration."""

    READ_CONTEXT = "read_context"
    PREPARE_DRAFT = "prepare_draft"


class DeterministicFinalAction(StrEnum):
    DRAFT = "draft"
    CLARIFY = "clarify"
    ESCALATE = "escalate"
    WAIT_APPROVAL = "wait_approval"


class DeterministicPlan(BaseModel):
    """T-602's test-only plan substitute; it contains no tool IDs or arguments."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    steps: tuple[DeterministicStep, ...]
    final_action: DeterministicFinalAction


class AgentExecutionPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = Field(default="t602-v1", min_length=1)
    max_plan_rounds: int = Field(default=2, ge=1)
    max_budget_units: int = Field(default=6, ge=1)


class AgentAuditEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    event_type: AgentEventType
    from_status: AgentStatus
    to_status: AgentStatus
    reason_code: AgentReasonCode


class CheckpointFailureKind(StrEnum):
    MISSING = "missing"
    VERSION_MISMATCH = "version_mismatch"
    CAS_CONFLICT = "cas_conflict"
    BINDING_MISMATCH = "binding_mismatch"


class CheckpointFailure(BaseModel):
    """Failure-only signal; it cannot request resume, writes, or a successful state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: CheckpointFailureKind


class ApprovalBinding(BaseModel):
    """Server-generated approval/checkpoint identifiers; no proof is exposed in state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    approval_id: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    checkpoint_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    version: int = Field(ge=1)


class TrustedApprovalEvent(BaseModel):
    """Internal event envelope. Its opaque proof is verified outside public state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    binding: ApprovalBinding
    decision: str
    event_type: AgentEventType
    sequence: int = Field(ge=1)
    proof: str = Field(min_length=1)


class AgentState(BaseModel):
    """No hidden reasoning, model payload, business fact, or tool result is stored here."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    conversation_id: str = Field(min_length=1)
    turn_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    status: AgentStatus
    plan_rounds: int = Field(default=0, ge=0)
    budget_used: int = Field(default=0, ge=0)
    executed_steps: tuple[DeterministicStep, ...] = ()
    reason_code: AgentReasonCode
    audit_events: tuple[AgentAuditEvent, ...] = ()
    approval_binding: ApprovalBinding | None = None
    trusted_approval_decision: str | None = None
