from datetime import date
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from customer_service.rag.schemas import PolicyDocument
from customer_service.tools.schemas import AuthorizedOrderFacts


class ReturnReason(StrEnum):
    CHANGED_MIND = "changed_mind"
    QUALITY_ISSUE = "quality_issue"


class PolicyDecision(StrEnum):
    ALLOW_IF_RESALABLE = "allow_if_resalable"
    ALLOW_AFTER_ISSUE_VERIFICATION = "allow_after_issue_verification"
    DENY = "deny"


class EligibilityStatus(StrEnum):
    ELIGIBLE = "eligible"
    NEEDS_INFORMATION = "needs_information"
    VERIFICATION_REQUIRED = "verification_required"
    REQUIRES_APPROVAL = "requires_approval"
    INELIGIBLE = "ineligible"


class EligibilityConclusion(StrEnum):
    ELIGIBLE = "eligible"
    CONDITIONAL = "conditional"
    INDETERMINATE = "indeterminate"
    INELIGIBLE = "ineligible"


class MissingField(StrEnum):
    RETURN_REASON = "return_reason"
    ITEM_CONDITION = "item_condition"
    ISSUE_CODE = "issue_code"
    TARGET_ITEM = "target_item"
    DELIVERED_AT = "delivered_at"


class RiskReason(StrEnum):
    HIGH_VALUE_ORDER = "HIGH_VALUE_ORDER"
    OVERDUE_EXCEPTION = "OVERDUE_EXCEPTION"
    POLICY_CONFLICT = "POLICY_CONFLICT"
    POLICY_EVIDENCE_INSUFFICIENT = "POLICY_EVIDENCE_INSUFFICIENT"
    ISSUE_VERIFICATION_REQUIRED = "ISSUE_VERIFICATION_REQUIRED"
    EVIDENCE_MISMATCH = "EVIDENCE_MISMATCH"


class EligibilityItemFacts(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    order_item_id: str = Field(min_length=1)
    product_id: str = Field(min_length=1)
    category: str = Field(min_length=1)


class EligibilityRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    order: AuthorizedOrderFacts
    item: EligibilityItemFacts | None = None
    return_reason: ReturnReason | None = None
    item_condition: str | None = None
    issue_code: str | None = None
    policies: tuple[PolicyDocument, ...] = ()
    as_of: date | None = None


class EligibilityResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_version: str = Field(min_length=1)
    status: EligibilityStatus
    eligibility: EligibilityConclusion
    applicable_policy_ids: tuple[str, ...]
    matched_rule_ids: tuple[str, ...]
    missing_fields: tuple[MissingField, ...]
    risk_reasons: tuple[RiskReason, ...]
    requires_human_approval: bool
    days_since_delivery: int | None = Field(default=None, ge=0)
    message: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_result_contract(self) -> Self:
        if self.status is EligibilityStatus.ELIGIBLE:
            if (
                self.eligibility is not EligibilityConclusion.ELIGIBLE
                or self.missing_fields
                or self.risk_reasons
                or self.requires_human_approval
            ):
                raise ValueError("eligible result must be complete and low risk")
        elif self.status is EligibilityStatus.NEEDS_INFORMATION:
            if (
                self.eligibility is not EligibilityConclusion.INDETERMINATE
                or not self.missing_fields
                or self.requires_human_approval
            ):
                raise ValueError("needs-information result requires missing fields")
        elif self.status is EligibilityStatus.VERIFICATION_REQUIRED:
            if (
                self.eligibility is not EligibilityConclusion.CONDITIONAL
                or self.risk_reasons != (RiskReason.ISSUE_VERIFICATION_REQUIRED,)
                or self.requires_human_approval
            ):
                raise ValueError("verification result requires the verification risk")
        elif self.status is EligibilityStatus.REQUIRES_APPROVAL:
            if not self.risk_reasons or not self.requires_human_approval:
                raise ValueError("approval result requires a risk reason")
        elif (
            self.eligibility is not EligibilityConclusion.INELIGIBLE
            or self.missing_fields
            or self.requires_human_approval
        ):
            raise ValueError("ineligible result has an invalid contract")
        return self
