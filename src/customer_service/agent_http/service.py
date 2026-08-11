import hashlib
import re
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from customer_service.agent_http.schemas import (
    AgentConversationResponse,
    AgentMode,
    AgentModeOption,
    AgentModesResponse,
    PublicAgentStatus,
    PublicCitation,
    PublicMessage,
    PublicModelStatus,
)
from customer_service.agent_workflow import (
    AgentWorkflowOutcome,
    AgentWorkflowRequest,
    AgentWorkflowResult,
    AgentWorkflowService,
    TrustedAgentContext,
)
from customer_service.collection.schemas import CollectionContext, CollectionRequest
from customer_service.collection.service import ReturnInformationCollectionService
from customer_service.rag.catalog import PolicyCatalog
from customer_service.rag.schemas import PolicyQuery
from customer_service.routing.schemas import RoutingContext, RoutingIntent, RoutingRequest
from customer_service.routing.service import IntentRoutingService


class AgentModeNotConfiguredError(ValueError):
    pass


class IdempotencyError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class InMemoryPolicyContexts:
    def __init__(self) -> None:
        self._queries: dict[tuple[str, str, str], PolicyQuery] = {}

    def put(self, context: TrustedAgentContext, query: PolicyQuery) -> None:
        self._queries[(context.conversation_id, context.turn_id, context.user_id)] = query

    def get(self, *, conversation_id: str, turn_id: str, user_id: str) -> PolicyQuery | None:
        return self._queries.get((conversation_id, turn_id, user_id))


@dataclass
class _Session:
    conversation_id: str
    user_id: str
    mode: AgentMode
    collection: CollectionContext
    next_turn: int
    history: list[PublicMessage]
    snapshot: AgentConversationResponse
    pending_turn_id: str | None = None


@dataclass
class _IdempotencyRecord:
    user_id: str
    conversation_id: str
    mode: AgentMode
    method: str
    path: str
    digest: str
    turn_id: str
    status: str
    response: AgentConversationResponse | None
    expires_at: datetime


class AgentConversationService:
    """In-process HTTP session boundary over the only controlled Agent entry."""

    _CASE_ID = re.compile(r"编号为 ([^。]+)。")
    _ORDER_ID = re.compile(r"\bORD-[A-Z0-9-]+\b", re.IGNORECASE)

    def __init__(
        self,
        *,
        workflows: dict[AgentMode, AgentWorkflowService],
        deepseek_configured: bool,
        policy_contexts: InMemoryPolicyContexts,
        catalog: PolicyCatalog,
        user_id: str = "USR-DEMO-001",
        ttl: timedelta = timedelta(hours=24),
    ) -> None:
        self._workflows = workflows
        self._deepseek_configured = deepseek_configured
        self._policy_contexts = policy_contexts
        self._catalog = catalog
        self._user_id = user_id
        self._ttl = ttl
        self._router = IntentRoutingService()
        self._collector = ReturnInformationCollectionService()
        self._sessions: dict[str, _Session] = {}
        self._idempotency: dict[str, _IdempotencyRecord] = {}
        self._idempotency_lock = threading.Lock()
        self._conversation_by_approval: dict[str, str] = {}

    def modes(self) -> AgentModesResponse:
        return AgentModesResponse(
            modes=(
                AgentModeOption(id=AgentMode.FAKE, configured=True, selectable=True),
                AgentModeOption(
                    id=AgentMode.DEEPSEEK,
                    configured=self._deepseek_configured,
                    selectable=self._deepseek_configured,
                    reason_code=(
                        None if self._deepseek_configured else "AGENT_MODE_NOT_CONFIGURED"
                    ),
                ),
            )
        )

    def create(self, mode: AgentMode) -> AgentConversationResponse:
        if mode is AgentMode.DEEPSEEK and not self._deepseek_configured:
            raise AgentModeNotConfiguredError
        conversation_id = str(uuid4())
        welcome = PublicMessage(
            id="assistant-0",
            role="assistant",
            content="可以咨询退货政策、查询订单或申请退货。",
        )
        response = self._base_response(
            conversation_id=conversation_id,
            mode=mode,
            status=PublicAgentStatus.CLARIFY,
            model_status=PublicModelStatus.NOT_USED,
            reason_code="CONVERSATION_CREATED",
            message=welcome.content,
            action_hint="请输入政策问题、订单号或退货诉求。",
            messages=(welcome,),
        )
        self._sessions[conversation_id] = _Session(
            conversation_id=conversation_id,
            user_id=self._user_id,
            mode=mode,
            collection=CollectionContext(),
            next_turn=1,
            history=[welcome],
            snapshot=response,
        )
        return response

    def get(self, conversation_id: str) -> AgentConversationResponse:
        return self._session(conversation_id).snapshot

    def send(
        self, conversation_id: str, message: str, idempotency_key: str | None
    ) -> AgentConversationResponse:
        session = self._session(conversation_id)
        self.validate_idempotency_key(idempotency_key)
        assert idempotency_key is not None
        normalized = message.strip()
        digest = hashlib.sha256(normalized.encode()).hexdigest()
        path = f"/api/v1/conversations/{conversation_id}/messages"
        now = datetime.now(UTC)
        with self._idempotency_lock:
            existing = self._idempotency.get(idempotency_key)
            if existing is not None:
                if existing.expires_at <= now:
                    raise IdempotencyError("IDEMPOTENCY_STATE_UNAVAILABLE")
                binding = (
                    session.user_id,
                    conversation_id,
                    session.mode,
                    "POST",
                    path,
                    digest,
                )
                if binding != (
                    existing.user_id,
                    existing.conversation_id,
                    existing.mode,
                    existing.method,
                    existing.path,
                    existing.digest,
                ):
                    raise IdempotencyError("IDEMPOTENCY_KEY_CONFLICT")
                if existing.status == "PROCESSING":
                    raise IdempotencyError("IDEMPOTENCY_REQUEST_IN_PROGRESS")
                if existing.response is None:
                    raise IdempotencyError("IDEMPOTENCY_STATE_UNAVAILABLE")
                return existing.response
            turn_id = f"TURN-{session.next_turn}"
            session.next_turn += 1
            self._idempotency[idempotency_key] = _IdempotencyRecord(
                user_id=session.user_id,
                conversation_id=conversation_id,
                mode=session.mode,
                method="POST",
                path=path,
                digest=digest,
                turn_id=turn_id,
                status="PROCESSING",
                response=None,
                expires_at=now + self._ttl,
            )
        try:
            response = self._execute(session, turn_id=turn_id, message=normalized)
        except Exception:
            response = self._store_public(
                session,
                original_message=normalized,
                assistant_message="当前请求的处理结果无法安全确认，请勿重复提交并联系人工客服。",
                status=PublicAgentStatus.FAILED_SAFE,
                model_status=PublicModelStatus.NOT_USED,
                reason_code="WRITE_OUTCOME_UNKNOWN",
                action_hint="请通过人工渠道查询当前状态。",
            )
        with self._idempotency_lock:
            record = self._idempotency[idempotency_key]
            record.status = "COMPLETED"
            record.response = response
        return response

    def resume_for_approval(self, approval_id: str) -> AgentConversationResponse | None:
        conversation_id = self._conversation_by_approval.get(approval_id)
        if conversation_id is None:
            return None
        session = self._session(conversation_id)
        if session.pending_turn_id is None:
            return session.snapshot
        context = self._trusted_context(session, session.pending_turn_id)
        result = self._workflows[session.mode].resume(context=context)
        response = self._project(session, result, original_message="")
        session.snapshot = response
        if result.outcome is not AgentWorkflowOutcome.WAITING_APPROVAL:
            session.pending_turn_id = None
        return response

    @staticmethod
    def validate_idempotency_key(value: str | None) -> None:
        if value is None:
            raise IdempotencyError("IDEMPOTENCY_KEY_INVALID")
        try:
            parsed = UUID(value)
        except ValueError as error:
            raise IdempotencyError("IDEMPOTENCY_KEY_INVALID") from error
        if len(value) != 36 or value != str(parsed) or parsed.version != 4:
            raise IdempotencyError("IDEMPOTENCY_KEY_INVALID")

    def _execute(
        self, session: _Session, *, turn_id: str, message: str
    ) -> AgentConversationResponse:
        route = self._router.route(
            RoutingRequest(message=message),
            context=RoutingContext(
                has_active_return_task=any(
                    (
                        session.collection.order_id,
                        session.collection.return_reason,
                        session.collection.item_condition,
                    )
                )
            ),
        )
        canonical = message
        if route.intent is RoutingIntent.ORDER_QUERY:
            order_id = self._ORDER_ID.search(message)
            if order_id is None:
                return self._store_public(
                    session,
                    original_message=message,
                    assistant_message="请提供需要查询的订单号。",
                    status=PublicAgentStatus.CLARIFY,
                    model_status=PublicModelStatus.NOT_USED,
                    reason_code="PLAN_CLARIFICATION_REQUIRED",
                    action_hint="请提供订单号。",
                )
            session.collection = CollectionContext(
                order_id=order_id.group(0).upper(),
                return_reason=session.collection.return_reason,
                item_condition=session.collection.item_condition,
                revisions=session.collection.revisions,
            )
        if route.intent in {RoutingIntent.RETURN_REQUEST, RoutingIntent.CONTINUE_RETURN}:
            collected = self._collector.collect(
                CollectionRequest(message=message), context=session.collection
            )
            session.collection = CollectionContext(
                order_id=collected.order_id,
                return_reason=collected.return_reason,
                item_condition=collected.item_condition,
                revisions=collected.revisions,
            )
            if collected.missing_slot is not None:
                return self._store_public(
                    session,
                    original_message=message,
                    assistant_message=collected.message,
                    status=PublicAgentStatus.CLARIFY,
                    model_status=PublicModelStatus.NOT_USED,
                    reason_code="PLAN_CLARIFICATION_REQUIRED",
                    action_hint=collected.message,
                )
            assert collected.order_id and collected.return_reason and collected.item_condition
            reason = "质量问题" if collected.return_reason.value == "quality_issue" else "不想要"
            condition = (
                "未使用" if collected.item_condition.value == "resalable" else "不可再次销售"
            )
            canonical = f"退货 订单号 {collected.order_id} {reason} {condition}"
        context = self._trusted_context(session, turn_id)
        if route.intent is RoutingIntent.POLICY_QUESTION:
            self._policy_contexts.put(
                context, PolicyQuery(category="general_merchandise", return_reason="changed_mind")
            )
        result = self._workflows[session.mode].handle(
            AgentWorkflowRequest(message=canonical), context=context
        )
        response = self._project(session, result, original_message=message)
        session.snapshot = response
        if result.outcome is AgentWorkflowOutcome.WAITING_APPROVAL:
            session.pending_turn_id = turn_id
            if result.approval_id is not None:
                self._conversation_by_approval[result.approval_id] = session.conversation_id
        return response

    def _project(
        self, session: _Session, result: AgentWorkflowResult, *, original_message: str
    ) -> AgentConversationResponse:
        statuses = {
            AgentWorkflowOutcome.ALLOWED: PublicAgentStatus.COMPLETED,
            AgentWorkflowOutcome.SAFE_REWRITE: PublicAgentStatus.COMPLETED,
            AgentWorkflowOutcome.CLARIFY: PublicAgentStatus.CLARIFY,
            AgentWorkflowOutcome.ESCALATE: PublicAgentStatus.ESCALATE,
            AgentWorkflowOutcome.WAITING_APPROVAL: PublicAgentStatus.WAITING_APPROVAL,
            AgentWorkflowOutcome.FAILED_SAFE: PublicAgentStatus.FAILED_SAFE,
        }
        model_status = self._model_status(session.mode, result)
        public_message = result.public_response or self._safe_message(result.outcome, model_status)
        citations = self._citations(result.policy_ids)
        if original_message:
            session.history.append(
                PublicMessage(
                    id=f"user-{len(session.history)}", role="user", content=original_message
                )
            )
        session.history.append(
            PublicMessage(
                id=f"assistant-{len(session.history)}",
                role="assistant",
                content=public_message,
                citations=citations,
            )
        )
        match = self._CASE_ID.search(public_message)
        return self._base_response(
            conversation_id=session.conversation_id,
            mode=session.mode,
            status=statuses[result.outcome],
            model_status=model_status,
            reason_code=result.reason_code,
            message=public_message,
            action_hint=self._action_hint(result.outcome, model_status),
            messages=tuple(session.history),
            citations=citations,
            service_case_id=match.group(1) if match else None,
        )

    def _store_public(
        self,
        session: _Session,
        *,
        original_message: str,
        assistant_message: str,
        status: PublicAgentStatus,
        model_status: PublicModelStatus,
        reason_code: str,
        action_hint: str,
    ) -> AgentConversationResponse:
        session.history.extend(
            (
                PublicMessage(
                    id=f"user-{len(session.history)}", role="user", content=original_message
                ),
                PublicMessage(
                    id=f"assistant-{len(session.history) + 1}",
                    role="assistant",
                    content=assistant_message,
                ),
            )
        )
        response = self._base_response(
            conversation_id=session.conversation_id,
            mode=session.mode,
            status=status,
            model_status=model_status,
            reason_code=reason_code,
            message=assistant_message,
            action_hint=action_hint,
            messages=tuple(session.history),
        )
        session.snapshot = response
        return response

    def _trusted_context(self, session: _Session, turn_id: str) -> TrustedAgentContext:
        return TrustedAgentContext(
            conversation_id=session.conversation_id,
            turn_id=turn_id,
            user_id=session.user_id,
            confirmed_order_id=session.collection.order_id,
            confirmed_return_reason=(
                None
                if session.collection.return_reason is None
                else session.collection.return_reason.value
            ),
            confirmed_item_condition=(
                None
                if session.collection.item_condition is None
                else session.collection.item_condition.value
            ),
        )

    def _citations(self, policy_ids: tuple[str, ...]) -> tuple[PublicCitation, ...]:
        current = tuple(
            policy
            for policy in self._catalog.policies
            if policy.policy_id in policy_ids and policy.is_current(self._catalog.reference_date)
        )
        return tuple(
            PublicCitation(policy_id=item.policy_id, title=item.title, source=item.source)
            for item in current[:1]
        )

    @staticmethod
    def _model_status(mode: AgentMode, result: AgentWorkflowResult) -> PublicModelStatus:
        if result.outcome is not AgentWorkflowOutcome.FAILED_SAFE:
            return PublicModelStatus.SUCCEEDED
        if result.reason_code == "RESPONSE_MODEL_INVALID":
            return PublicModelStatus.INVALID_OUTPUT
        return (
            PublicModelStatus.UNAVAILABLE
            if mode is AgentMode.DEEPSEEK
            else PublicModelStatus.NOT_USED
        )

    @staticmethod
    def _safe_message(outcome: AgentWorkflowOutcome, model_status: PublicModelStatus) -> str:
        if outcome is AgentWorkflowOutcome.WAITING_APPROVAL:
            return "该请求需要人工审批，目前尚未创建售后申请。"
        if model_status is PublicModelStatus.INVALID_OUTPUT:
            return "模型输出未通过结构校验，本轮已安全停止。"
        if model_status is PublicModelStatus.UNAVAILABLE:
            return "DeepSeek Agent 当前不可用，本轮没有生成可公开的模型回答。"
        return "当前无法安全确认处理结果，请补充信息或联系人工客服。"

    @staticmethod
    def _action_hint(outcome: AgentWorkflowOutcome, model_status: PublicModelStatus) -> str:
        if outcome is AgentWorkflowOutcome.WAITING_APPROVAL:
            return "请等待人工审批；刷新只会读取当前状态。"
        if model_status in {PublicModelStatus.UNAVAILABLE, PublicModelStatus.INVALID_OUTPUT}:
            return "可以稍后重试，或新建合成演示会话。"
        return "可继续发送新的售后问题。"

    @staticmethod
    def _base_response(
        *,
        conversation_id: str,
        mode: AgentMode,
        status: PublicAgentStatus,
        model_status: PublicModelStatus,
        reason_code: str,
        message: str,
        action_hint: str,
        messages: tuple[PublicMessage, ...],
        citations: tuple[PublicCitation, ...] = (),
        service_case_id: str | None = None,
    ) -> AgentConversationResponse:
        return AgentConversationResponse(
            conversation_id=conversation_id,
            requested_mode=mode,
            effective_mode=mode,
            agent_status=status,
            model_status=model_status,
            reason_code=reason_code,
            can_retry=model_status in {PublicModelStatus.UNAVAILABLE, PublicModelStatus.TIMEOUT},
            can_start_fake_conversation=mode is AgentMode.DEEPSEEK,
            message=message,
            action_hint=action_hint,
            citations=citations,
            service_case_id=service_case_id,
            messages=messages,
        )

    def _session(self, conversation_id: str) -> _Session:
        try:
            return self._sessions[conversation_id]
        except KeyError as error:
            raise KeyError("conversation unavailable") from error
