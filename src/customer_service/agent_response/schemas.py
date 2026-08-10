from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from customer_service.agent_runtime.schemas import AgentReasonCode, AgentState
from customer_service.agent_tools.schemas import EvidenceRecord
from customer_service.approvals.schemas import ApprovalTaskSummary
from customer_service.eligibility.schemas import EligibilityResult
from customer_service.model_gateway.schemas import ModelResultStatus
from customer_service.rag.schemas import PolicyCitation
from customer_service.response_gate.schemas import ResponseGateAction, ResponseGateResult
from customer_service.service_cases.schemas import ServiceCaseSummary
from customer_service.tools.schemas import AuthorizedOrderFacts


class TrustedEvidenceSnapshot(BaseModel):
    """Server-retained typed payload; never accepted from a model response."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_citations: tuple[PolicyCitation, ...] = ()
    order: AuthorizedOrderFacts | None = None
    eligibility: EligibilityResult | None = None
    service_case: ServiceCaseSummary | None = None
    approval: ApprovalTaskSummary | None = None


class ResolvedEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    record: EvidenceRecord
    snapshot: TrustedEvidenceSnapshot


class AgentResponseOutcome(StrEnum):
    ALLOWED = "allowed"
    SAFE_REWRITE = "safe_rewrite"
    CLARIFY = "clarify"
    ESCALATE = "escalate"
    FAILED_SAFE = "failed_safe"


class AgentResponseAudit(BaseModel):
    """No user text, raw model output, prompt body, or hidden reasoning."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str
    prompt_version: str
    input_digest: str
    evidence_ids: tuple[str, ...]
    model_status: ModelResultStatus
    evidence_valid: bool
    gate_action: ResponseGateAction | None = None
    reason_code: AgentReasonCode


class AgentResponseResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    state: AgentState
    outcome: AgentResponseOutcome
    public_response: str | None = None
    gate: ResponseGateResult | None = None
    audit: AgentResponseAudit
