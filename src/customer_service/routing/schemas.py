from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RoutingStage(StrEnum):
    NEW = "NEW"
    ROUTED = "ROUTED"
    COLLECTING_INFORMATION = "COLLECTING_INFORMATION"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    ESCALATED = "ESCALATED"


class RoutingIntent(StrEnum):
    POLICY_QUESTION = "policy_question"
    ORDER_QUERY = "order_query"
    RETURN_REQUEST = "return_request"
    CONTINUE_RETURN = "continue_return"
    UNKNOWN = "unknown"


class RoutingAction(StrEnum):
    POLICY_QA = "policy_qa"
    ORDER_QUERY = "order_query"
    COLLECT_RETURN_INFORMATION = "collect_return_information"
    CONTINUE_RETURN = "continue_return"
    CLARIFY_INTENT = "clarify_intent"
    ESCALATE_HUMAN = "escalate_human"


class RoutingErrorCode(StrEnum):
    ORDER_ID_REQUIRED = "ORDER_ID_REQUIRED"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    CLARIFICATION_LIMIT_REACHED = "CLARIFICATION_LIMIT_REACHED"


class RoutingRequest(BaseModel):
    """Public user input; it cannot select an intent or business action."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    message: str = Field(min_length=1)

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("message must not be blank")
        return normalized


class RoutingContext(BaseModel):
    """Server-injected state used only for deterministic routing decisions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: RoutingStage = RoutingStage.NEW
    clarification_count: int = Field(default=0, ge=0, le=2)
    has_active_return_task: bool = False


class RoutingResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    intent: RoutingIntent
    next_action: RoutingAction
    stage: RoutingStage
    clarification_count: int = Field(ge=0, le=2)
    escalated_to_human: bool
    business_operation_requested: bool
    error_code: RoutingErrorCode | None
    message: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_result_contract(self) -> Self:
        expected = {
            RoutingIntent.POLICY_QUESTION: (
                RoutingAction.POLICY_QA,
                RoutingStage.ROUTED,
                False,
                None,
            ),
            RoutingIntent.ORDER_QUERY: (
                RoutingAction.ORDER_QUERY,
                RoutingStage.ROUTED,
                False,
                None,
            ),
            RoutingIntent.RETURN_REQUEST: None,
            RoutingIntent.UNKNOWN: None,
        }
        if self.business_operation_requested:
            raise ValueError("routing result cannot request a business operation")
        if self.intent is RoutingIntent.CONTINUE_RETURN:
            if (
                self.next_action is not RoutingAction.CONTINUE_RETURN
                or self.escalated_to_human
                or self.error_code is not None
            ):
                raise ValueError("continue-return result has an invalid contract")
            return self
        if self.intent is RoutingIntent.UNKNOWN:
            if self.next_action is RoutingAction.CLARIFY_INTENT:
                if (
                    self.stage is not RoutingStage.NEEDS_CLARIFICATION
                    or self.clarification_count != 1
                    or self.escalated_to_human
                    or self.error_code is not RoutingErrorCode.CLARIFICATION_REQUIRED
                ):
                    raise ValueError("clarification result has an invalid contract")
            elif self.next_action is RoutingAction.ESCALATE_HUMAN:
                if (
                    self.stage is not RoutingStage.ESCALATED
                    or self.clarification_count != 2
                    or not self.escalated_to_human
                    or self.error_code is not RoutingErrorCode.CLARIFICATION_LIMIT_REACHED
                ):
                    raise ValueError("escalation result has an invalid contract")
            else:
                raise ValueError("unknown intent must clarify or escalate")
            return self
        if self.intent is RoutingIntent.RETURN_REQUEST:
            if (
                self.next_action is not RoutingAction.COLLECT_RETURN_INFORMATION
                or self.escalated_to_human
            ):
                raise ValueError("return-request result has an invalid contract")
            if self.stage is RoutingStage.COLLECTING_INFORMATION and self.error_code is None:
                return self
            if (
                self.stage is RoutingStage.NEEDS_CLARIFICATION
                and self.error_code is RoutingErrorCode.ORDER_ID_REQUIRED
            ):
                return self
            raise ValueError("return-request result has an invalid contract")
        expected_result = expected[self.intent]
        assert expected_result is not None
        action, stage, escalated, error_code = expected_result
        if (
            self.next_action is not action
            or self.stage is not stage
            or self.escalated_to_human is not escalated
            or self.error_code is not error_code
        ):
            raise ValueError("recognized intent has an invalid contract")
        return self
