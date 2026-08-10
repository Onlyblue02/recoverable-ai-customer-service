from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from customer_service.approvals.schemas import ApprovalTaskSummary
from customer_service.eligibility.schemas import EligibilityResult
from customer_service.rag.schemas import PolicyCitation
from customer_service.service_cases.schemas import ServiceCaseSummary
from customer_service.tools.schemas import AuthorizedOrderFacts


class ResponseGateAction(StrEnum):
    ALLOW = "allow"
    SAFE_REWRITE = "safe_rewrite"
    CLARIFY = "clarify"
    ESCALATE = "escalate"


class ResponseGateReason(StrEnum):
    UNGROUNDED_POLICY = "UNGROUNDED_POLICY"
    UNAUTHORIZED_ORDER_FACT = "UNAUTHORIZED_ORDER_FACT"
    ELIGIBILITY_MISMATCH = "ELIGIBILITY_MISMATCH"
    UNCONFIRMED_COMPLETION = "UNCONFIRMED_COMPLETION"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    INVALID_APPROVAL = "INVALID_APPROVAL"
    UNSAFE_CONTENT = "UNSAFE_CONTENT"
    UNSUPPORTED_FREE_TEXT = "UNSUPPORTED_FREE_TEXT"


class ResponseDraft(BaseModel):
    """Untrusted candidate response with explicit, auditable factual claims."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    message: str = Field(min_length=1, max_length=2000)
    policy_citations: tuple[PolicyCitation, ...] = ()
    order: AuthorizedOrderFacts | None = None
    eligibility: EligibilityResult | None = None
    service_case: ServiceCaseSummary | None = None
    approval: ApprovalTaskSummary | None = None
    claims_policy_conclusion: bool = False
    claims_order_facts: bool = False
    claims_eligibility: bool = False
    claims_completion: bool = False

    @model_validator(mode="after")
    def validate_declared_claims(self) -> Self:
        if self.claims_policy_conclusion and not self.policy_citations:
            raise ValueError("policy conclusion requires citations")
        if self.claims_order_facts and self.order is None:
            raise ValueError("order claim requires order facts")
        if self.claims_eligibility and self.eligibility is None:
            raise ValueError("eligibility claim requires eligibility")
        if self.claims_completion and self.service_case is None:
            raise ValueError("completion claim requires a service case")
        return self


class ResponseEvidenceContext(BaseModel):
    """Server-injected trusted evidence; never part of a response draft payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_citations: tuple[PolicyCitation, ...] = ()
    current_user_id: str | None = None
    order: AuthorizedOrderFacts | None = None
    eligibility: EligibilityResult | None = None
    service_case: ServiceCaseSummary | None = None
    approval: ApprovalTaskSummary | None = None


class ResponseGateResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    action: ResponseGateAction
    reasons: tuple[ResponseGateReason, ...]
    message: str = Field(min_length=1)
    response: ResponseDraft | None

    @model_validator(mode="after")
    def validate_contract(self) -> Self:
        if self.action is ResponseGateAction.ALLOW:
            if self.reasons or self.response is None:
                raise ValueError("allowed response requires no reasons and the original draft")
        elif self.action is ResponseGateAction.SAFE_REWRITE:
            if self.response is None or not self.reasons:
                raise ValueError("safe rewrite requires a replacement draft and reason")
        elif self.response is not None or not self.reasons:
            raise ValueError("blocked response exposes no draft and requires a reason")
        return self
