import re

from customer_service.collection.schemas import (
    CollectionContext,
    CollectionRequest,
    CollectionResult,
    CollectionSlot,
    CollectionStage,
    ItemCondition,
    SlotRevision,
)
from customer_service.eligibility.schemas import ReturnReason


class ReturnInformationCollectionService:
    """Deterministic, side-effect-free T-202 slot collection and correction."""

    _ORDER_ID_PATTERN = re.compile(r"\bORD-[A-Z0-9-]+\b", re.IGNORECASE)
    _REASON_CORRECTION_PATTERN = re.compile(
        r"不是(?P<old>质量问题|坏了|没有声音|故障|不想要|不需要|改变主意|买错)"
        r".{0,12}是(?P<new>质量问题|坏了|没有声音|故障|不想要|不需要|改变主意|买错)"
    )
    _ITEM_CONDITION_CORRECTION_PATTERN = re.compile(
        r"不是(?P<old>没用过|未使用|完好|再次销售|包装[^，。；]{0,8}完整|已使用|破损|损坏|包装[^，。；]{0,8}破)"
        r".{0,12}是(?P<new>没用过|未使用|完好|再次销售|包装[^，。；]{0,8}完整|已使用|破损|损坏|包装[^，。；]{0,8}破)"
    )
    _QUALITY_ISSUE_PATTERN = re.compile(r"质量问题|坏了|没有声音|故障")
    _CHANGED_MIND_PATTERN = re.compile(r"不想要|不需要|改变主意|买错")
    _RESALABLE_PATTERN = re.compile(r"没用过|未使用|完好|包装.*完整|再次销售")
    _NOT_RESALABLE_PATTERN = re.compile(r"已使用|破损|损坏|包装.*破")

    def collect(
        self, request: CollectionRequest, *, context: CollectionContext
    ) -> CollectionResult:
        order_id = self._order_id(request.message) or context.order_id
        return_reason = self._return_reason(request.message) or context.return_reason
        item_condition = self._item_condition(request.message) or context.item_condition
        updated_slots = self._updated_slots(context, order_id, return_reason, item_condition)
        revisions = self._revisions(context, order_id, return_reason, item_condition)
        missing_slot = self._missing_slot(order_id, return_reason, item_condition)

        if missing_slot is None:
            return CollectionResult(
                stage=CollectionStage.EVALUATING,
                order_id=order_id,
                return_reason=return_reason,
                item_condition=item_condition,
                missing_slot=None,
                updated_slots=updated_slots,
                revisions=revisions,
                business_operation_requested=False,
                message=self._ready_message(revisions),
            )
        return CollectionResult(
            stage=CollectionStage.COLLECTING_INFORMATION,
            order_id=order_id,
            return_reason=return_reason,
            item_condition=item_condition,
            missing_slot=missing_slot,
            updated_slots=updated_slots,
            revisions=revisions,
            business_operation_requested=False,
            message=self._question(missing_slot),
        )

    @classmethod
    def _order_id(cls, message: str) -> str | None:
        match = cls._ORDER_ID_PATTERN.search(message)
        return match.group(0).upper() if match else None

    @classmethod
    def _return_reason(cls, message: str) -> ReturnReason | None:
        correction = cls._REASON_CORRECTION_PATTERN.search(message)
        if correction:
            return cls._reason_from_phrase(correction.group("new"))
        if cls._QUALITY_ISSUE_PATTERN.search(message):
            return ReturnReason.QUALITY_ISSUE
        if cls._CHANGED_MIND_PATTERN.search(message):
            return ReturnReason.CHANGED_MIND
        return None

    @staticmethod
    def _reason_from_phrase(phrase: str) -> ReturnReason:
        if ReturnInformationCollectionService._QUALITY_ISSUE_PATTERN.search(phrase):
            return ReturnReason.QUALITY_ISSUE
        return ReturnReason.CHANGED_MIND

    @classmethod
    def _item_condition(cls, message: str) -> ItemCondition | None:
        correction = cls._ITEM_CONDITION_CORRECTION_PATTERN.search(message)
        if correction:
            return cls._item_condition_from_phrase(correction.group("new"))
        if cls._NOT_RESALABLE_PATTERN.search(message):
            return ItemCondition.NOT_RESALABLE
        if cls._RESALABLE_PATTERN.search(message):
            return ItemCondition.RESALABLE
        return None

    @staticmethod
    def _item_condition_from_phrase(phrase: str) -> ItemCondition:
        if ReturnInformationCollectionService._NOT_RESALABLE_PATTERN.search(phrase):
            return ItemCondition.NOT_RESALABLE
        return ItemCondition.RESALABLE

    @staticmethod
    def _missing_slot(
        order_id: str | None,
        return_reason: ReturnReason | None,
        item_condition: ItemCondition | None,
    ) -> CollectionSlot | None:
        if order_id is None:
            return CollectionSlot.ORDER_ID
        if return_reason is None:
            return CollectionSlot.RETURN_REASON
        if item_condition is None:
            return CollectionSlot.ITEM_CONDITION
        return None

    @staticmethod
    def _updated_slots(
        context: CollectionContext,
        order_id: str | None,
        return_reason: ReturnReason | None,
        item_condition: ItemCondition | None,
    ) -> tuple[CollectionSlot, ...]:
        values = (
            (CollectionSlot.ORDER_ID, context.order_id, order_id),
            (CollectionSlot.RETURN_REASON, context.return_reason, return_reason),
            (CollectionSlot.ITEM_CONDITION, context.item_condition, item_condition),
        )
        return tuple(
            slot
            for slot, previous, current in values
            if current is not None and previous != current
        )

    @staticmethod
    def _revisions(
        context: CollectionContext,
        order_id: str | None,
        return_reason: ReturnReason | None,
        item_condition: ItemCondition | None,
    ) -> tuple[SlotRevision, ...]:
        revisions = list(context.revisions)
        values = (
            (CollectionSlot.ORDER_ID, context.order_id, order_id),
            (CollectionSlot.RETURN_REASON, context.return_reason, return_reason),
            (CollectionSlot.ITEM_CONDITION, context.item_condition, item_condition),
        )
        for slot, previous, current in values:
            if previous is not None and current is not None and previous != current:
                revisions.append(
                    SlotRevision(
                        slot=slot,
                        previous_value=str(previous),
                        new_value=str(current),
                        sequence=len(revisions) + 1,
                    )
                )
        return tuple(revisions)

    @staticmethod
    def _question(slot: CollectionSlot) -> str:
        questions = {
            CollectionSlot.ORDER_ID: "请提供订单号。",
            CollectionSlot.RETURN_REASON: "请说明退货原因。",
            CollectionSlot.ITEM_CONDITION: "请说明商品是否未使用且包装完整。",
        }
        return questions[slot]

    @staticmethod
    def _ready_message(revisions: tuple[SlotRevision, ...]) -> str:
        if revisions and revisions[-1].slot is CollectionSlot.RETURN_REASON:
            return "退货原因已更正，信息已完整，可进入资格判断。"
        return "退货信息已完整，可进入资格判断。"
