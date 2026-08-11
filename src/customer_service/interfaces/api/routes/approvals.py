from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from customer_service.agent_http.composition import AgentApplication, get_agent_application
from customer_service.approvals.schemas import ApprovalDecisionRequest, ApprovalTaskSummary

router = APIRouter(prefix="/api/v1/approvals", tags=["approvals"])


@router.get("", response_model=tuple[ApprovalTaskSummary, ...])
def list_approvals(
    application: Annotated[AgentApplication, Depends(get_agent_application)],
) -> tuple[ApprovalTaskSummary, ...]:
    return application.list_approvals()


@router.post("/{approval_id}/decisions", response_model=ApprovalTaskSummary)
def decide(
    approval_id: str,
    request: ApprovalDecisionRequest,
    application: Annotated[AgentApplication, Depends(get_agent_application)],
) -> ApprovalTaskSummary:
    try:
        return application.decide_approval(approval_id, request)
    except ValueError as error:
        raise HTTPException(status_code=409, detail="approval unavailable") from error
