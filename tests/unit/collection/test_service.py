import pytest
from pydantic import ValidationError

from customer_service.collection.schemas import (
    CollectionContext,
    CollectionRequest,
    CollectionSlot,
    CollectionStage,
    ItemCondition,
)
from customer_service.collection.service import ReturnInformationCollectionService
from customer_service.eligibility.schemas import ReturnReason


def collector() -> ReturnInformationCollectionService:
    return ReturnInformationCollectionService()


def test_collects_slots_across_turns_with_one_priority_question() -> None:
    first = collector().collect(CollectionRequest(message="我要退货"), context=CollectionContext())
    second = collector().collect(
        CollectionRequest(message="订单是 ord-normal-001"),
        context=CollectionContext(),
    )
    third = collector().collect(
        CollectionRequest(message="不想要了"),
        context=CollectionContext(order_id=second.order_id),
    )
    complete = collector().collect(
        CollectionRequest(message="商品没用过，包装也完整"),
        context=CollectionContext(order_id=third.order_id, return_reason=third.return_reason),
    )

    assert first.missing_slot is CollectionSlot.ORDER_ID
    assert second.missing_slot is CollectionSlot.RETURN_REASON
    assert third.missing_slot is CollectionSlot.ITEM_CONDITION
    assert complete.stage is CollectionStage.EVALUATING
    assert complete.item_condition is ItemCondition.RESALABLE
    assert complete.business_operation_requested is False


def test_latest_correction_replaces_value_and_records_revision() -> None:
    result = collector().collect(
        CollectionRequest(message="更正一下，不是不想要，是质量问题，没有声音"),
        context=CollectionContext(
            order_id="ORD-QUALITY-001",
            return_reason=ReturnReason.CHANGED_MIND,
            item_condition=ItemCondition.RESALABLE,
        ),
    )

    assert result.stage is CollectionStage.EVALUATING
    assert result.return_reason is ReturnReason.QUALITY_ISSUE
    assert result.updated_slots == (CollectionSlot.RETURN_REASON,)
    assert result.revisions[-1].previous_value == ReturnReason.CHANGED_MIND
    assert result.revisions[-1].new_value == ReturnReason.QUALITY_ISSUE
    assert result.business_operation_requested is False


@pytest.mark.parametrize(
    ("previous_reason", "message", "expected_reason"),
    (
        (
            ReturnReason.QUALITY_ISSUE,
            "更正一下，不是质量问题，是买错了",
            ReturnReason.CHANGED_MIND,
        ),
        (
            ReturnReason.CHANGED_MIND,
            "更正一下，不是不想要，是质量问题",
            ReturnReason.QUALITY_ISSUE,
        ),
    ),
)
def test_bidirectional_reason_corrections_use_the_latest_value(
    previous_reason: ReturnReason, message: str, expected_reason: ReturnReason
) -> None:
    result = collector().collect(
        CollectionRequest(message=message),
        context=CollectionContext(
            order_id="ORD-1",
            return_reason=previous_reason,
            item_condition=ItemCondition.RESALABLE,
        ),
    )

    assert result.return_reason is expected_reason
    assert result.updated_slots == (CollectionSlot.RETURN_REASON,)
    assert result.revisions[-1].previous_value == previous_reason
    assert result.revisions[-1].new_value == expected_reason


def test_correction_result_remains_latest_when_used_as_next_trusted_context() -> None:
    corrected = collector().collect(
        CollectionRequest(message="不是质量问题，是买错了"),
        context=CollectionContext(
            order_id="ORD-1",
            return_reason=ReturnReason.QUALITY_ISSUE,
            item_condition=ItemCondition.RESALABLE,
        ),
    )
    next_turn = collector().collect(
        CollectionRequest(message="好的"),
        context=CollectionContext(
            order_id=corrected.order_id,
            return_reason=corrected.return_reason,
            item_condition=corrected.item_condition,
            revisions=corrected.revisions,
        ),
    )

    assert next_turn.return_reason is ReturnReason.CHANGED_MIND
    assert next_turn.revisions == corrected.revisions
    assert next_turn.updated_slots == ()


def test_same_reason_correction_is_deterministic() -> None:
    context = CollectionContext(
        order_id="ORD-1",
        return_reason=ReturnReason.QUALITY_ISSUE,
        item_condition=ItemCondition.RESALABLE,
    )
    request = CollectionRequest(message="不是质量问题，是买错了")

    assert collector().collect(request, context=context) == collector().collect(
        request, context=context
    )


@pytest.mark.parametrize(
    ("message", "expected_reason"),
    (
        ("更正，不是质量问题，是不需要了", ReturnReason.CHANGED_MIND),
        ("更正，不是故障，是改变主意", ReturnReason.CHANGED_MIND),
    ),
)
def test_reason_correction_covers_all_supported_reason_phrases(
    message: str, expected_reason: ReturnReason
) -> None:
    result = collector().collect(
        CollectionRequest(message=message),
        context=CollectionContext(
            order_id="ORD-1",
            return_reason=ReturnReason.QUALITY_ISSUE,
            item_condition=ItemCondition.RESALABLE,
        ),
    )

    assert result.return_reason is expected_reason
    assert result.updated_slots == (CollectionSlot.RETURN_REASON,)
    assert result.revisions[-1].previous_value == ReturnReason.QUALITY_ISSUE
    assert result.revisions[-1].new_value == expected_reason
    assert result.revisions[-1].sequence == 1


@pytest.mark.parametrize(
    ("previous_condition", "message", "expected_condition"),
    (
        (ItemCondition.NOT_RESALABLE, "更正，不是已使用，是未使用", ItemCondition.RESALABLE),
        (ItemCondition.NOT_RESALABLE, "更正，不是破损，是完好", ItemCondition.RESALABLE),
        (ItemCondition.RESALABLE, "更正，不是未使用，是已使用", ItemCondition.NOT_RESALABLE),
        (ItemCondition.RESALABLE, "更正，不是完好，是破损", ItemCondition.NOT_RESALABLE),
    ),
)
def test_item_condition_correction_uses_new_value_and_preserves_it_next_turn(
    previous_condition: ItemCondition, message: str, expected_condition: ItemCondition
) -> None:
    corrected = collector().collect(
        CollectionRequest(message=message),
        context=CollectionContext(
            order_id="ORD-1",
            return_reason=ReturnReason.CHANGED_MIND,
            item_condition=previous_condition,
        ),
    )
    next_turn = collector().collect(
        CollectionRequest(message="好的"),
        context=CollectionContext(
            order_id=corrected.order_id,
            return_reason=corrected.return_reason,
            item_condition=corrected.item_condition,
            revisions=corrected.revisions,
        ),
    )

    assert corrected.item_condition is expected_condition
    assert corrected.updated_slots == (CollectionSlot.ITEM_CONDITION,)
    assert corrected.revisions[-1].previous_value == previous_condition
    assert corrected.revisions[-1].new_value == expected_condition
    assert corrected.revisions[-1].sequence == 1
    assert next_turn.item_condition is expected_condition
    assert next_turn.revisions == corrected.revisions
    assert next_turn.updated_slots == ()


@pytest.mark.parametrize("order_id", ("", "   "))
def test_blank_trusted_order_id_is_normalized_to_missing(order_id: str) -> None:
    result = collector().collect(
        CollectionRequest(message="好的"),
        context=CollectionContext(
            order_id=order_id,
            return_reason=ReturnReason.CHANGED_MIND,
            item_condition=ItemCondition.RESALABLE,
        ),
    )

    assert result.stage is CollectionStage.COLLECTING_INFORMATION
    assert result.missing_slot is CollectionSlot.ORDER_ID
    assert result.order_id is None


def test_trusted_order_id_is_normalized_before_collection() -> None:
    result = collector().collect(
        CollectionRequest(message="好的"),
        context=CollectionContext(
            order_id=" ord-normal-001 ",
            return_reason=ReturnReason.CHANGED_MIND,
            item_condition=ItemCondition.RESALABLE,
        ),
    )

    assert result.stage is CollectionStage.EVALUATING
    assert result.order_id == "ORD-NORMAL-001"


def test_public_request_cannot_override_trusted_context() -> None:
    with pytest.raises(ValidationError):
        CollectionRequest.model_validate(
            {"message": "我要退货", "order_id": "ORD-OTHER-USER-001", "stage": "READY"}
        )


def test_blank_message_is_rejected() -> None:
    with pytest.raises(ValidationError):
        CollectionRequest(message="  ")
