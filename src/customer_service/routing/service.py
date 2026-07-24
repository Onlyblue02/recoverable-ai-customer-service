import re

from customer_service.routing.schemas import (
    RoutingAction,
    RoutingContext,
    RoutingErrorCode,
    RoutingIntent,
    RoutingRequest,
    RoutingResult,
    RoutingStage,
)


class IntentRoutingService:
    """Auditable, side-effect-free recognition for the T-201 routing boundary."""

    _POLICY_CONSULTATION_PATTERN = re.compile(
        r"(?:了解|咨询|查询|知道).{0,12}(?:政策|规则|条件)|(?:退货|退款).{0,4}(?:政策|规则|条件)"
    )
    _RETURN_REQUEST_PATTERN = re.compile(r"(?:我想|我要|申请|想要)\s*(?:退货|退款|退掉)")
    _RETURN_PATTERN = re.compile(r"退货|退款|退掉|售后")
    _ORDER_QUERY_PATTERN = re.compile(
        r"(?:查单|查询|查|看看).{0,12}(?:订单|ORD-[A-Z0-9-]+)|订单状态",
        re.IGNORECASE,
    )
    _POLICY_PATTERN = re.compile(r"政策|规则|能不能退|可以退吗")
    _ORDER_ID_PATTERN = re.compile(r"\bORD-[A-Z0-9-]+\b", re.IGNORECASE)

    def route(self, request: RoutingRequest, *, context: RoutingContext) -> RoutingResult:
        if context.has_active_return_task:
            return RoutingResult(
                intent=RoutingIntent.CONTINUE_RETURN,
                next_action=RoutingAction.CONTINUE_RETURN,
                stage=context.stage,
                clarification_count=context.clarification_count,
                escalated_to_human=False,
                business_operation_requested=False,
                error_code=None,
                message="退货任务已继续，请补充当前所需信息。",
            )

        intent = self._recognize(request.message)
        if intent is RoutingIntent.POLICY_QUESTION:
            return self._recognized(
                intent=intent,
                action=RoutingAction.POLICY_QA,
                stage=RoutingStage.ROUTED,
                message="已进入政策咨询流程。",
            )
        if intent is RoutingIntent.ORDER_QUERY:
            return self._recognized(
                intent=intent,
                action=RoutingAction.ORDER_QUERY,
                stage=RoutingStage.ROUTED,
                message="已进入订单查询流程。",
            )
        if intent is RoutingIntent.RETURN_REQUEST:
            if not self._ORDER_ID_PATTERN.search(request.message):
                return RoutingResult(
                    intent=intent,
                    next_action=RoutingAction.COLLECT_RETURN_INFORMATION,
                    stage=RoutingStage.NEEDS_CLARIFICATION,
                    clarification_count=0,
                    escalated_to_human=False,
                    business_operation_requested=False,
                    error_code=RoutingErrorCode.ORDER_ID_REQUIRED,
                    message="已进入退货信息收集，请提供订单号。",
                )
            return self._recognized(
                intent=intent,
                action=RoutingAction.COLLECT_RETURN_INFORMATION,
                stage=RoutingStage.COLLECTING_INFORMATION,
                message="已进入退货信息收集，请提供订单号。",
            )
        if context.clarification_count >= 1:
            return RoutingResult(
                intent=RoutingIntent.UNKNOWN,
                next_action=RoutingAction.ESCALATE_HUMAN,
                stage=RoutingStage.ESCALATED,
                clarification_count=2,
                escalated_to_human=True,
                business_operation_requested=False,
                error_code=RoutingErrorCode.CLARIFICATION_LIMIT_REACHED,
                message="暂时无法确认您的诉求，已转人工处理。",
            )
        return RoutingResult(
            intent=RoutingIntent.UNKNOWN,
            next_action=RoutingAction.CLARIFY_INTENT,
            stage=RoutingStage.NEEDS_CLARIFICATION,
            clarification_count=1,
            escalated_to_human=False,
            business_operation_requested=False,
            error_code=RoutingErrorCode.CLARIFICATION_REQUIRED,
            message="请说明您希望咨询政策、查询订单还是申请退货。",
        )

    def _recognize(self, message: str) -> RoutingIntent:
        if self._POLICY_CONSULTATION_PATTERN.search(message):
            return RoutingIntent.POLICY_QUESTION
        if self._RETURN_REQUEST_PATTERN.search(message):
            return RoutingIntent.RETURN_REQUEST
        if self._ORDER_QUERY_PATTERN.search(message):
            return RoutingIntent.ORDER_QUERY
        if self._POLICY_PATTERN.search(message):
            return RoutingIntent.POLICY_QUESTION
        if self._RETURN_PATTERN.search(message):
            return RoutingIntent.RETURN_REQUEST
        return RoutingIntent.UNKNOWN

    @staticmethod
    def _recognized(
        *,
        intent: RoutingIntent,
        action: RoutingAction,
        stage: RoutingStage,
        message: str,
    ) -> RoutingResult:
        return RoutingResult(
            intent=intent,
            next_action=action,
            stage=stage,
            clarification_count=0,
            escalated_to_human=False,
            business_operation_requested=False,
            error_code=None,
            message=message,
        )
