from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from customer_service.approvals.schemas import ApprovalDecision, ApprovalTaskSummary
from customer_service.eligibility.schemas import ReturnReason
from customer_service.response_gate.schemas import ResponseGateAction
from customer_service.service_cases.schemas import ServiceCaseSummary


class HighRiskWorkflowStatus(StrEnum):
    WAITING_APPROVAL = "WAITING_APPROVAL"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"
    FAILED_SAFE = "FAILED_SAFE"


class HighRiskStartRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    message: str = Field(min_length=1, max_length=500)


class HighRiskContext(BaseModel):
    """Server-provided facts required to begin one high-risk return."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    workflow_id: str = Field(min_length=1)
    current_user_id: str = Field(min_length=1)
    order_id: str = Field(min_length=1)
    return_reason: ReturnReason
    item_condition: str = Field(min_length=1)


class HighRiskDecisionInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    decision: ApprovalDecision
    note: str = Field(min_length=1, max_length=500)
    recommendation: str | None = None
    expected_version: int = Field(ge=1)


class HighRiskWorkflowResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    status: HighRiskWorkflowStatus
    message: str = Field(min_length=1)
    approval: ApprovalTaskSummary | None
    service_case: ServiceCaseSummary | None
    gate_action: ResponseGateAction | None
    business_operation_requested: bool
