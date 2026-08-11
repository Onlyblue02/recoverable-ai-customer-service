from typing import Annotated

from fastapi import APIRouter, Depends

from customer_service.agent_http.composition import AgentApplication, get_agent_application
from customer_service.agent_http.schemas import AgentModesResponse

router = APIRouter(prefix="/api/v1/agent", tags=["consumer-agent"])


@router.get("/modes", response_model=AgentModesResponse)
def get_modes(
    application: Annotated[AgentApplication, Depends(get_agent_application)],
) -> AgentModesResponse:
    return application.conversations.modes()
