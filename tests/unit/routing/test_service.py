import pytest
from pydantic import ValidationError

from customer_service.routing.schemas import (
    RoutingAction,
    RoutingContext,
    RoutingIntent,
    RoutingRequest,
    RoutingStage,
)
from customer_service.routing.service import IntentRoutingService


def router() -> IntentRoutingService:
    return IntentRoutingService()


@pytest.mark.parametrize(
    ("message", "intent", "action"),
    [
        ("退货政策是什么？", RoutingIntent.POLICY_QUESTION, RoutingAction.POLICY_QA),
        (
            "帮我查询 ORD-NORMAL-001 的订单状态",
            RoutingIntent.ORDER_QUERY,
            RoutingAction.ORDER_QUERY,
        ),
        (
            "我想退掉 ORD-NORMAL-001",
            RoutingIntent.RETURN_REQUEST,
            RoutingAction.COLLECT_RETURN_INFORMATION,
        ),
    ],
)
def test_known_intents_have_deterministic_routes(
    message: str, intent: RoutingIntent, action: RoutingAction
) -> None:
    result = router().route(RoutingRequest(message=message), context=RoutingContext())

    assert result.intent is intent
    assert result.next_action is action
    assert result.business_operation_requested is False
    assert result.escalated_to_human is False


def test_return_without_order_only_requests_the_order_id() -> None:
    result = router().route(
        RoutingRequest(message="我想退掉刚买的商品。"), context=RoutingContext()
    )

    assert result.intent is RoutingIntent.RETURN_REQUEST
    assert result.stage is RoutingStage.NEEDS_CLARIFICATION
    assert result.next_action is RoutingAction.COLLECT_RETURN_INFORMATION
    assert "订单号" in result.message
    assert result.business_operation_requested is False


@pytest.mark.parametrize(
    ("message", "intent", "action"),
    [
        (
            "我想退货，订单是 ORD-NORMAL-001，能不能退？",
            RoutingIntent.RETURN_REQUEST,
            RoutingAction.COLLECT_RETURN_INFORMATION,
        ),
        (
            "退货政策需要订单号吗？",
            RoutingIntent.POLICY_QUESTION,
            RoutingAction.POLICY_QA,
        ),
        (
            "我想知道 ORD-NORMAL-001 的订单状态，退货前先查一下。",
            RoutingIntent.ORDER_QUERY,
            RoutingAction.ORDER_QUERY,
        ),
    ],
)
def test_mixed_intents_follow_the_documented_priority(
    message: str, intent: RoutingIntent, action: RoutingAction
) -> None:
    result = router().route(RoutingRequest(message=message), context=RoutingContext())

    assert result.intent is intent
    assert result.next_action is action
    assert result.business_operation_requested is False


@pytest.mark.parametrize(
    "message",
    (
        "我想了解一下退货政策",
        "我要查询退货规则",
        "我想知道订单退货规则",
    ),
)
def test_policy_consultation_is_not_misclassified_as_a_return_request(message: str) -> None:
    result = router().route(RoutingRequest(message=message), context=RoutingContext())

    assert result.intent is RoutingIntent.POLICY_QUESTION
    assert result.next_action is RoutingAction.POLICY_QA
    assert result.business_operation_requested is False


def test_mixed_intent_result_is_repeatable() -> None:
    request = RoutingRequest(message="我想退货，订单是 ORD-NORMAL-001，能不能退？")

    first = router().route(request, context=RoutingContext())
    second = router().route(request, context=RoutingContext())

    assert first == second


def test_active_return_is_continued_before_message_reclassification() -> None:
    result = router().route(
        RoutingRequest(message="帮我查询 ORD-NORMAL-001 的订单状态"),
        context=RoutingContext(
            stage=RoutingStage.COLLECTING_INFORMATION,
            has_active_return_task=True,
            clarification_count=1,
        ),
    )

    assert result.intent is RoutingIntent.CONTINUE_RETURN
    assert result.next_action is RoutingAction.CONTINUE_RETURN
    assert result.stage is RoutingStage.COLLECTING_INFORMATION
    assert result.clarification_count == 1


def test_unknown_first_turn_clarifies_and_second_turn_escalates_without_business_operation() -> (
    None
):
    first = router().route(RoutingRequest(message="你看着办"), context=RoutingContext())
    second = router().route(
        RoutingRequest(message="还是那个事情"),
        context=RoutingContext(
            stage=first.stage,
            clarification_count=first.clarification_count,
        ),
    )

    assert first.intent is RoutingIntent.UNKNOWN
    assert first.stage is RoutingStage.NEEDS_CLARIFICATION
    assert first.clarification_count == 1
    assert first.escalated_to_human is False
    assert second.intent is RoutingIntent.UNKNOWN
    assert second.stage is RoutingStage.ESCALATED
    assert second.clarification_count == 2
    assert second.escalated_to_human is True
    assert second.business_operation_requested is False


def test_public_request_rejects_context_and_route_overrides() -> None:
    with pytest.raises(ValidationError):
        RoutingRequest.model_validate(
            {
                "message": "我要退货",
                "intent": "order_query",
                "requires_human_handoff": False,
            }
        )


def test_blank_message_is_rejected() -> None:
    with pytest.raises(ValidationError):
        RoutingRequest(message="   ")
