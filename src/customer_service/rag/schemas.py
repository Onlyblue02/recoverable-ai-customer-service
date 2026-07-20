from datetime import date
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PolicyAnswerStatus(StrEnum):
    ANSWERED = "answered"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    CONFLICT = "conflict"


class RecommendedAction(StrEnum):
    ANSWER = "answer"
    CLARIFY = "clarify"
    ESCALATE = "escalate"


class PolicyAnswerReason(StrEnum):
    CURRENT_POLICY = "current_policy"
    EXPIRED_ONLY = "expired_only"
    NO_RESULT = "no_result"
    NO_CURRENT_POLICY = "no_current_policy"
    MISSING_RETURN_REASON = "missing_return_reason"
    CONFLICTING_POLICIES = "conflicting_policies"
    AMBIGUOUS_SOURCES = "ambiguous_sources"
    UNGROUNDED_CITATION = "UNGROUNDED_CITATION"


class PolicyDocument(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    policy_id: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    title: str = Field(min_length=1)
    source: str = Field(min_length=1)
    status: str = Field(min_length=1)
    effective_from: date
    effective_to: date
    applicable_categories: tuple[str, ...] = Field(min_length=1)
    return_reason: str = Field(min_length=1)
    decision: str = Field(min_length=1)
    content: str = Field(min_length=1)
    conflict_group: str | None = None

    @model_validator(mode="after")
    def validate_effective_window(self) -> Self:
        if self.effective_from > self.effective_to:
            raise ValueError("policy effective_from must not be after effective_to")
        return self

    def is_current(self, as_of: date) -> bool:
        return (
            self.status == "published"
            and self.effective_from <= as_of
            and self.effective_to >= as_of
        )

    @property
    def evidence_id(self) -> str:
        return f"policy:{self.policy_id}:{self.policy_version}"


class PolicyQuery(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    category: str = Field(min_length=1)
    return_reason: str | None = Field(default=None, min_length=1)
    as_of: date | None = None


class PolicyCitation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_id: str
    evidence_id: str
    policy_version: str
    title: str
    source: str
    effective_from: date
    effective_to: date
    excerpt: str


class PolicyAnswerResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: PolicyAnswerStatus
    action: RecommendedAction
    reason: PolicyAnswerReason
    message: str = Field(min_length=1)
    answer: str | None
    citations: tuple[PolicyCitation, ...]
    candidate_policy_ids: tuple[str, ...]

    @model_validator(mode="after")
    def validate_grounding_contract(self) -> Self:
        if self.status is PolicyAnswerStatus.ANSWERED:
            if self.action is not RecommendedAction.ANSWER:
                raise ValueError("answered result must recommend answer")
            if self.reason is not PolicyAnswerReason.CURRENT_POLICY:
                raise ValueError("answered result must use current policy reason")
            if not self.answer or not self.citations:
                raise ValueError("answered result requires an answer and citations")
            citation_ids = tuple(citation.policy_id for citation in self.citations)
            if citation_ids != self.candidate_policy_ids:
                raise ValueError("citations must exactly match policies used for the answer")
            return self

        if self.answer is not None or self.citations:
            raise ValueError("non-answered result cannot contain an answer or citations")
        if self.status is PolicyAnswerStatus.CONFLICT:
            if self.action is not RecommendedAction.ESCALATE:
                raise ValueError("conflict result must escalate")
            if self.reason is not PolicyAnswerReason.CONFLICTING_POLICIES:
                raise ValueError("conflict result requires conflicting policies reason")
        elif self.action is not RecommendedAction.CLARIFY:
            raise ValueError("insufficient evidence result must clarify")
        return self
