from customer_service.collection.schemas import CollectionRequest, CollectionResult, CollectionStage
from customer_service.collection.service import ReturnInformationCollectionService
from customer_service.eligibility.engine import EligibilityEngine
from customer_service.eligibility.schemas import (
    EligibilityItemFacts,
    EligibilityRequest,
    EligibilityResult,
    EligibilityStatus,
)
from customer_service.orchestration.schemas import (
    StandardReturnContext,
    StandardReturnRequest,
    StandardReturnResult,
    StandardReturnStatus,
)
from customer_service.rag.catalog import PolicyCatalog
from customer_service.rag.schemas import PolicyAnswerStatus, PolicyCitation, PolicyQuery
from customer_service.rag.service import PolicyAnswerService
from customer_service.routing.schemas import RoutingContext, RoutingRequest, RoutingStage
from customer_service.routing.service import IntentRoutingService
from customer_service.service_cases.schemas import (
    ServiceCaseAccessContext,
    ServiceCaseCreateRequest,
    ServiceCaseEligibilityContext,
    ServiceCaseStatus,
)
from customer_service.service_cases.service import ServiceCaseService
from customer_service.tools.order_tool import OrderQueryService
from customer_service.tools.schemas import (
    AuthorizedOrderFacts,
    OrderAccessContext,
    OrderQuery,
    OrderQueryStatus,
)


class StandardReturnWorkflowService:
    """Sequential T-203 composition for the one low-risk standard-return path."""

    def __init__(
        self,
        *,
        router: IntentRoutingService,
        collector: ReturnInformationCollectionService,
        orders: OrderQueryService,
        policies: PolicyAnswerService,
        policy_catalog: PolicyCatalog,
        product_categories: dict[str, str],
        eligibility: EligibilityEngine,
        service_cases: ServiceCaseService,
    ) -> None:
        self._router = router
        self._collector = collector
        self._orders = orders
        self._policies = policies
        self._policy_catalog = policy_catalog
        self._product_categories = product_categories
        self._eligibility = eligibility
        self._service_cases = service_cases

    def advance(
        self, request: StandardReturnRequest, *, context: StandardReturnContext
    ) -> StandardReturnResult:
        routed = self._router.route(
            RoutingRequest(message=request.message),
            context=RoutingContext(
                stage=RoutingStage.COLLECTING_INFORMATION,
                has_active_return_task=self._has_active_return(context),
            ),
        )
        if routed.intent.value not in {"return_request", "continue_return"}:
            return self._collecting(
                collection=self._collector.collect(
                    request=CollectionRequest(message=request.message), context=context.collection
                ),
                message="请先说明是否需要申请退货。",
            )

        collection = self._collector.collect(
            request=CollectionRequest(message=request.message), context=context.collection
        )
        if collection.stage is not CollectionStage.EVALUATING:
            return self._collecting(collection=collection, message=collection.message)

        assert collection.order_id is not None
        assert collection.return_reason is not None
        assert collection.item_condition is not None
        order_result = self._orders.query(
            OrderQuery(order_id=collection.order_id),
            access_context=OrderAccessContext(current_user_id=context.current_user_id),
        )
        if order_result.status is not OrderQueryStatus.FOUND or order_result.order is None:
            return self._result(
                status=StandardReturnStatus.ORDER_UNAVAILABLE,
                message="无法访问该订单，未创建模拟售后申请。",
                collection=None,
            )
        order = order_result.order
        if len(order.items) != 1:
            return self._result(
                status=StandardReturnStatus.REQUIRES_APPROVAL,
                message="当前订单需要人工确认目标商品，未创建模拟售后申请。",
                collection=collection,
                order=order,
            )
        item = order.items[0]
        category = self._product_categories.get(item.product_id)
        if category is None:
            return self._result(
                status=StandardReturnStatus.POLICY_UNAVAILABLE,
                message="缺少商品类别对应的政策依据，未创建模拟售后申请。",
                collection=collection,
                order=order,
            )
        policy_result = self._policies.answer(
            PolicyQuery(category=category, return_reason=collection.return_reason.value)
        )
        if policy_result.status is not PolicyAnswerStatus.ANSWERED:
            return self._result(
                status=StandardReturnStatus.POLICY_UNAVAILABLE,
                message="当前政策依据不足或冲突，未创建模拟售后申请。",
                collection=collection,
                order=order,
            )
        used_policies = tuple(
            policy
            for policy in self._policy_catalog.policies
            if policy.policy_id in policy_result.candidate_policy_ids
        )
        eligibility = self._eligibility.evaluate(
            EligibilityRequest(
                order=order,
                item=EligibilityItemFacts(
                    order_item_id=item.order_item_id,
                    product_id=item.product_id,
                    category=category,
                ),
                return_reason=collection.return_reason,
                item_condition=collection.item_condition.value,
                policies=used_policies,
            )
        )
        if eligibility.status is EligibilityStatus.REQUIRES_APPROVAL:
            return self._result(
                status=StandardReturnStatus.REQUIRES_APPROVAL,
                message="当前退货需要人工审批，未创建模拟售后申请。",
                collection=collection,
                order=order,
                citations=policy_result.citations,
                eligibility=eligibility,
            )
        if eligibility.status is not EligibilityStatus.ELIGIBLE:
            return self._result(
                status=StandardReturnStatus.INELIGIBLE,
                message="当前退货不满足自动创建条件，未创建模拟售后申请。",
                collection=collection,
                order=order,
                citations=policy_result.citations,
                eligibility=eligibility,
            )
        case_result = self._service_cases.create(
            ServiceCaseCreateRequest(order=order, order_item_id=item.order_item_id),
            access_context=ServiceCaseAccessContext(current_user_id=context.current_user_id),
            eligibility_context=ServiceCaseEligibilityContext(eligibility=eligibility),
        )
        if case_result.status not in (ServiceCaseStatus.CREATED, ServiceCaseStatus.EXISTING):
            return self._result(
                status=StandardReturnStatus.CASE_CREATION_FAILED,
                message="模拟售后申请未创建成功。",
                collection=collection,
                order=order,
                citations=policy_result.citations,
                eligibility=eligibility,
            )
        assert case_result.service_case is not None
        return StandardReturnResult(
            status=StandardReturnStatus.COMPLETED,
            message="标准退货已完成，模拟售后申请已确认。",
            collection=collection,
            order=order,
            policy_citations=policy_result.citations,
            eligibility=eligibility,
            service_case=case_result.service_case,
            business_operation_requested=True,
        )

    @staticmethod
    def _has_active_return(context: StandardReturnContext) -> bool:
        collection = context.collection
        return any((collection.order_id, collection.return_reason, collection.item_condition))

    @staticmethod
    def _collecting(*, collection: CollectionResult, message: str) -> StandardReturnResult:
        return StandardReturnResult(
            status=StandardReturnStatus.COLLECTING_INFORMATION,
            message=message,
            collection=collection,
            order=None,
            policy_citations=(),
            eligibility=None,
            service_case=None,
            business_operation_requested=False,
        )

    @staticmethod
    def _result(
        *,
        status: StandardReturnStatus,
        message: str,
        collection: CollectionResult | None,
        order: AuthorizedOrderFacts | None = None,
        citations: tuple[PolicyCitation, ...] = (),
        eligibility: EligibilityResult | None = None,
    ) -> StandardReturnResult:
        return StandardReturnResult(
            status=status,
            message=message,
            collection=collection,
            order=order,
            policy_citations=citations,
            eligibility=eligibility,
            service_case=None,
            business_operation_requested=False,
        )
