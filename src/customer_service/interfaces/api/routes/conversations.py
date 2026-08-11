from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException

from customer_service.agent_http.composition import AgentApplication, get_agent_application
from customer_service.agent_http.schemas import (
    AgentConversationResponse,
    AgentMessageRequest,
    AgentMode,
    CreateConversationRequest,
)
from customer_service.agent_http.service import AgentModeNotConfiguredError, IdempotencyError

router = APIRouter(prefix="/api/v1/conversations", tags=["consumer-conversations"])


@router.post("", response_model=AgentConversationResponse)
def create_conversation(
    application: Annotated[AgentApplication, Depends(get_agent_application)],
    request: CreateConversationRequest | None = None,
) -> AgentConversationResponse:
    try:
        return application.conversations.create(AgentMode.FAKE if request is None else request.mode)
    except AgentModeNotConfiguredError as error:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "AGENT_MODE_NOT_CONFIGURED",
                "message": "DeepSeek 模式尚未在后端完成配置。",
                "can_retry": False,
            },
        ) from error


@router.get("/{conversation_id}", response_model=AgentConversationResponse)
def get_conversation(
    conversation_id: str,
    application: Annotated[AgentApplication, Depends(get_agent_application)],
) -> AgentConversationResponse:
    try:
        return application.conversations.get(conversation_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="conversation unavailable") from error


@router.post("/{conversation_id}/messages", response_model=AgentConversationResponse)
def send_message(
    conversation_id: str,
    request: AgentMessageRequest,
    application: Annotated[AgentApplication, Depends(get_agent_application)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> AgentConversationResponse:
    try:
        return application.conversations.send(conversation_id, request.message, idempotency_key)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="conversation unavailable") from error
    except IdempotencyError as error:
        status = 400 if error.code == "IDEMPOTENCY_KEY_INVALID" else 409
        raise HTTPException(
            status_code=status,
            detail={"code": error.code, "message": "请求无法安全重放。", "can_retry": False},
        ) from error
