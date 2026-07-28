import json
import re
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, Field

from customer_service.collection.schemas import CollectionContext
from customer_service.collection.service import ReturnInformationCollectionService
from customer_service.eligibility.config import EligibilityRuleConfig
from customer_service.eligibility.engine import EligibilityEngine
from customer_service.infrastructure.clients.mock_business import HttpOrderGateway
from customer_service.interfaces.api.routes.approvals import console
from customer_service.orchestration.high_risk_schemas import HighRiskContext, HighRiskWorkflowStatus
from customer_service.orchestration.schemas import StandardReturnContext, StandardReturnRequest
from customer_service.orchestration.service import StandardReturnWorkflowService
from customer_service.rag.catalog import PolicyCatalog
from customer_service.rag.schemas import PolicyAnswerStatus, PolicyQuery
from customer_service.rag.service import PolicyAnswerService
from customer_service.routing.schemas import RoutingContext, RoutingIntent, RoutingRequest
from customer_service.routing.service import IntentRoutingService
from customer_service.service_cases.repository import InMemoryServiceCaseRepository
from customer_service.service_cases.service import ServiceCaseService
from customer_service.tools.order_tool import OrderQueryService
from customer_service.tools.schemas import OrderAccessContext, OrderQuery, OrderQueryStatus
from mock_business.main import create_app as create_mock_business_app

router = APIRouter(prefix="/api/v1/conversations", tags=["consumer-conversations"])
ROOT = Path(__file__).parents[5]
_ORDER_ID_PATTERN = re.compile(r"\bORD-[A-Z0-9-]+\b", re.IGNORECASE)
_DEMO_USER_ID = "USR-DEMO-001"


class MessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=500)


class ConversationMessage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    role: Literal["user", "assistant"]
    content: str
    citations: tuple[dict[str, str], ...] = ()


class OrderSummary(BaseModel):
    """Consumer-safe subset of an already authorized order result."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    order_id: str
    status: str
    total_amount: str
    currency: str


class ConversationResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    conversation_id: str
    status: str
    message: str
    action_hint: str
    citations: tuple[dict[str, str], ...] = ()
    order: OrderSummary | None = None
    service_case_id: str | None = None
    messages: tuple[ConversationMessage, ...] = ()


def _components() -> tuple[
    IntentRoutingService,
    OrderQueryService,
    PolicyAnswerService,
    StandardReturnWorkflowService,
]:
    data = ROOT / "data"
    products = json.loads((data / "seed/products/products.v1.json").read_text(encoding="utf-8"))
    categories = {str(row["product_id"]): str(row["category"]) for row in products["products"]}
    catalog = PolicyCatalog.from_manifest(data / "manifest.json")
    intent_router = IntentRoutingService()
    orders = OrderQueryService(
        HttpOrderGateway(TestClient(create_mock_business_app(manifest_path=data / "manifest.json")))
    )
    policies = PolicyAnswerService(catalog)
    workflow = StandardReturnWorkflowService(
        router=intent_router,
        collector=ReturnInformationCollectionService(),
        orders=orders,
        policies=policies,
        policy_catalog=catalog,
        product_categories=categories,
        eligibility=EligibilityEngine(
            EligibilityRuleConfig.from_json(ROOT / "config/return-eligibility-rules.v1.json")
        ),
        service_cases=ServiceCaseService(InMemoryServiceCaseRepository()),
    )
    return intent_router, orders, policies, workflow


class ConsumerConversationService:
    """Minimal in-process consumer session over existing trusted public services."""

    def __init__(self) -> None:
        self._router, self._orders, self._policies, self._workflow = _components()
        self._contexts: dict[str, StandardReturnContext] = {}
        self._history: dict[str, list[ConversationMessage]] = {}
        self._snapshots: dict[str, ConversationResponse] = {}

    def create(self) -> ConversationResponse:
        conversation_id = str(uuid4())
        self._contexts[conversation_id] = StandardReturnContext(
            current_user_id=_DEMO_USER_ID,
            collection=CollectionContext(),
        )
        welcome = ConversationMessage(
            id="assistant-0",
            role="assistant",
            content="可以咨询退货政策、查询订单或申请退货。",
        )
        self._history[conversation_id] = [welcome]
        response = self._response(
            conversation_id=conversation_id,
            status="collecting_information",
            message=welcome.content,
            action_hint="请输入政策问题、订单号或退货诉求。",
        )
        self._snapshots[conversation_id] = response
        return response

    def get(self, conversation_id: str) -> ConversationResponse:
        if conversation_id not in self._contexts:
            raise KeyError(conversation_id)
        high_risk = console.result_for(conversation_id)
        if (
            high_risk is not None
            and high_risk.status is not HighRiskWorkflowStatus.WAITING_APPROVAL
        ):
            snapshot = self._snapshots[conversation_id].model_copy(
                update={
                    "status": high_risk.status.value.lower(),
                    "message": high_risk.message,
                    "action_hint": "人工审批已处理。",
                    "service_case_id": high_risk.service_case.service_case_id
                    if high_risk.service_case
                    else None,
                }
            )
            self._snapshots[conversation_id] = snapshot
        return self._snapshots[conversation_id].model_copy(
            update={"messages": tuple(self._history[conversation_id])}
        )

    def send(self, conversation_id: str, message: str) -> ConversationResponse:
        context = self._contexts.get(conversation_id)
        if context is None:
            raise KeyError(conversation_id)
        route = self._router.route(
            RoutingRequest(message=message),
            context=RoutingContext(has_active_return_task=self._has_active_return(context)),
        )
        if route.intent is RoutingIntent.POLICY_QUESTION:
            response = self._policy_answer(conversation_id)
        elif route.intent is RoutingIntent.ORDER_QUERY:
            response = self._order_answer(conversation_id, message)
        else:
            response = self._return_answer(conversation_id, message, context)
        self._history[conversation_id].extend(
            (
                ConversationMessage(
                    id=f"user-{len(self._history[conversation_id])}",
                    role="user",
                    content=message,
                ),
                ConversationMessage(
                    id=f"assistant-{len(self._history[conversation_id]) + 1}",
                    role="assistant",
                    content=response.message,
                    citations=response.citations,
                ),
            )
        )
        snapshot = response.model_copy(update={"messages": tuple(self._history[conversation_id])})
        self._snapshots[conversation_id] = snapshot
        return snapshot

    def _policy_answer(self, conversation_id: str) -> ConversationResponse:
        result = self._policies.answer(
            PolicyQuery(category="general_merchandise", return_reason="changed_mind")
        )
        if result.status is not PolicyAnswerStatus.ANSWERED:
            return self._response(
                conversation_id=conversation_id,
                status="policy_unavailable",
                message="当前无法给出有依据的政策结论。",
                action_hint="请补充商品类别或联系人工客服。",
            )
        return self._response(
            conversation_id=conversation_id,
            status="collecting_information",
            message=result.answer or result.message,
            action_hint="可继续查询订单或申请退货。",
            citations=tuple(
                {"policy_id": c.policy_id, "title": c.title, "source": c.source}
                for c in result.citations
            ),
        )

    def _order_answer(self, conversation_id: str, message: str) -> ConversationResponse:
        match = _ORDER_ID_PATTERN.search(message)
        result = self._orders.query(
            OrderQuery(order_id=match.group(0) if match else None),
            access_context=OrderAccessContext(current_user_id=_DEMO_USER_ID),
        )
        if result.status is not OrderQueryStatus.FOUND or result.order is None:
            return self._response(
                conversation_id=conversation_id,
                status=result.status.value,
                message=result.message,
                action_hint="请核对订单号或联系人工客服。",
            )
        order = result.order
        return self._response(
            conversation_id=conversation_id,
            status="collecting_information",
            message=result.message,
            action_hint="可继续申请退货或咨询政策。",
            order=OrderSummary(
                order_id=order.order_id,
                status=order.status,
                total_amount=order.total_amount,
                currency=order.currency,
            ),
        )

    def _return_answer(
        self,
        conversation_id: str,
        message: str,
        context: StandardReturnContext,
    ) -> ConversationResponse:
        result = self._workflow.advance(StandardReturnRequest(message=message), context=context)
        collection = result.collection
        if collection is not None:
            self._contexts[conversation_id] = context.model_copy(
                update={
                    "collection": CollectionContext(
                        order_id=collection.order_id,
                        return_reason=collection.return_reason,
                        item_condition=collection.item_condition,
                        revisions=collection.revisions,
                    )
                }
            )
        if result.status.value == "REQUIRES_APPROVAL" and collection is not None:
            assert collection.order_id and collection.return_reason and collection.item_condition
            high_risk = console.start(
                conversation_id,
                HighRiskContext(
                    workflow_id=f"WF-{conversation_id}",
                    current_user_id=_DEMO_USER_ID,
                    order_id=collection.order_id,
                    return_reason=collection.return_reason,
                    item_condition=collection.item_condition.value,
                ),
                message=message,
            )
            if high_risk.approval is not None:
                return self._response(
                    conversation_id=conversation_id,
                    status="requires_approval",
                    message=high_risk.message,
                    action_hint="已进入人工审批队列。",
                )
        return self._response(
            conversation_id=conversation_id,
            status=result.status.value.lower(),
            message=result.message,
            action_hint=collection.message if collection is not None else "请等待下一步处理。",
            citations=tuple(
                {"policy_id": c.policy_id, "title": c.title, "source": c.source}
                for c in result.policy_citations
            ),
            service_case_id=result.service_case.service_case_id if result.service_case else None,
        )

    def _response(
        self,
        *,
        conversation_id: str,
        status: str,
        message: str,
        action_hint: str,
        citations: tuple[dict[str, str], ...] = (),
        order: OrderSummary | None = None,
        service_case_id: str | None = None,
    ) -> ConversationResponse:
        return ConversationResponse(
            conversation_id=conversation_id,
            status=status,
            message=message,
            action_hint=action_hint,
            citations=citations,
            order=order,
            service_case_id=service_case_id,
            messages=tuple(self._history.get(conversation_id, ())),
        )

    @staticmethod
    def _has_active_return(context: StandardReturnContext) -> bool:
        collection = context.collection
        return any((collection.order_id, collection.return_reason, collection.item_condition))


service = ConsumerConversationService()


@router.post("", response_model=ConversationResponse)
def create_conversation() -> ConversationResponse:
    return service.create()


@router.get("/{conversation_id}", response_model=ConversationResponse)
def get_conversation(conversation_id: str) -> ConversationResponse:
    try:
        return service.get(conversation_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="conversation unavailable") from error


@router.post("/{conversation_id}/messages", response_model=ConversationResponse)
def send_message(conversation_id: str, request: MessageRequest) -> ConversationResponse:
    try:
        return service.send(conversation_id, request.message)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="conversation unavailable") from error
