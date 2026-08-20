from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AgentMode(StrEnum):
    FAKE = "fake"
    DEEPSEEK = "deepseek"


class PublicAgentStatus(StrEnum):
    COMPLETED = "completed"
    CLARIFY = "clarify"
    WAITING_APPROVAL = "waiting_approval"
    ESCALATE = "escalate"
    FAILED_SAFE = "failed_safe"


class PublicModelStatus(StrEnum):
    NOT_USED = "not_used"
    SUCCEEDED = "succeeded"
    NOT_CONFIGURED = "not_configured"
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    INVALID_OUTPUT = "invalid_output"


class AgentModeOption(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: AgentMode
    configured: bool
    selectable: bool
    reason_code: str | None = None


class AgentModesResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-modes-v1"] = "agent-modes-v1"
    default_mode: AgentMode = AgentMode.FAKE
    modes: tuple[AgentModeOption, ...]


class CreateConversationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: AgentMode = AgentMode.FAKE


class AgentMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=500)


class PublicCitation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_id: str
    title: str
    source: str


class PublicOrderEvidence(BaseModel):
    """Minimal order provenance derived only from a Gate-approved order fact."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    order_id: str
    confirmed_status: str
    source: Literal["controlled_authorized_order_record"] = "controlled_authorized_order_record"


class PublicMessage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    role: Literal["user", "assistant"]
    content: str
    citations: tuple[PublicCitation, ...] = ()


class AgentConversationResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-conversation-v1"] = "agent-conversation-v1"
    conversation_id: str
    requested_mode: AgentMode
    effective_mode: AgentMode
    agent_status: PublicAgentStatus
    model_status: PublicModelStatus
    reason_code: str
    can_retry: bool
    can_start_fake_conversation: bool
    message: str
    action_hint: str
    citations: tuple[PublicCitation, ...] = ()
    order_evidence: PublicOrderEvidence | None = None
    service_case_id: str | None = None
    messages: tuple[PublicMessage, ...] = ()


class PublicApiError(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    message: str
    can_retry: bool = False
