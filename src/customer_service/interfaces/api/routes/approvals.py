import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.testclient import TestClient

from customer_service.approvals.repository import InMemoryApprovalTaskRepository
from customer_service.approvals.schemas import (
    ApprovalActorContext,
    ApprovalDecisionRequest,
    ApprovalStatus,
    ApprovalTaskSummary,
)
from customer_service.approvals.service import ApprovalTaskService
from customer_service.eligibility.config import EligibilityRuleConfig
from customer_service.eligibility.engine import EligibilityEngine
from customer_service.infrastructure.clients.mock_business import HttpOrderGateway
from customer_service.orchestration.high_risk_schemas import (
    HighRiskContext,
    HighRiskDecisionInput,
    HighRiskStartRequest,
    HighRiskWorkflowResult,
)
from customer_service.orchestration.high_risk_service import HighRiskReturnWorkflowService
from customer_service.rag.catalog import PolicyCatalog
from customer_service.rag.service import PolicyAnswerService
from customer_service.recovery.repository import InMemoryRecoveryCheckpointRepository
from customer_service.recovery.service import ApprovalRecoveryService
from customer_service.response_gate.service import ResponseGateService
from customer_service.service_cases.repository import InMemoryServiceCaseRepository
from customer_service.service_cases.service import ServiceCaseService
from customer_service.tools.order_tool import OrderQueryService
from mock_business.main import create_app as create_mock_business_app

router = APIRouter(prefix="/api/v1/approvals", tags=["approvals"])
ROOT = Path(__file__).parents[5]


class ApprovalConsole:
    def __init__(self) -> None:
        data = ROOT / "data"
        products = json.loads((data / "seed/products/products.v1.json").read_text(encoding="utf-8"))
        categories = {str(row["product_id"]): str(row["category"]) for row in products["products"]}
        catalog = PolicyCatalog.from_manifest(data / "manifest.json")
        self.repository = InMemoryApprovalTaskRepository()
        approvals = ApprovalTaskService(self.repository)
        cases = ServiceCaseService(InMemoryServiceCaseRepository())
        checkpoints = InMemoryRecoveryCheckpointRepository()
        self.workflow = HighRiskReturnWorkflowService(
            orders=OrderQueryService(
                HttpOrderGateway(
                    TestClient(create_mock_business_app(manifest_path=data / "manifest.json"))
                )
            ),
            policies=PolicyAnswerService(catalog),
            policy_catalog=catalog,
            product_categories=categories,
            eligibility=EligibilityEngine(
                EligibilityRuleConfig.from_json(ROOT / "config/return-eligibility-rules.v1.json")
            ),
            approvals=approvals,
            recovery=ApprovalRecoveryService(
                checkpoints, approvals=self.repository, service_cases=cases
            ),
            checkpoints=checkpoints,
            gate=ResponseGateService(),
        )
        self.service = approvals
        self._contexts: dict[str, HighRiskContext] = {}
        self._conversation_by_approval: dict[str, str] = {}
        self._results: dict[str, HighRiskWorkflowResult] = {}

    def reset_for_test(self) -> None:
        fresh = ApprovalConsole()
        self.__dict__.clear()
        self.__dict__.update(fresh.__dict__)

    def start(
        self, conversation_id: str, context: HighRiskContext, message: str
    ) -> HighRiskWorkflowResult:
        result = self.workflow.start(HighRiskStartRequest(message=message), context=context)
        if result.approval is not None:
            self._contexts[result.approval.approval_id] = context
            self._conversation_by_approval[result.approval.approval_id] = conversation_id
        self._results[conversation_id] = result
        return result

    def list(self) -> tuple[ApprovalTaskSummary, ...]:
        return tuple(self.service._summary(task) for task in self.repository.list_tasks())

    def decide(self, approval_id: str, request: ApprovalDecisionRequest) -> HighRiskWorkflowResult:
        context = self._contexts.get(approval_id)
        task = self.repository.find_by_id(approval_id)
        if context is None or task is None or task.status is not ApprovalStatus.PENDING:
            raise ValueError("approval unavailable")
        result = self.workflow.decide_and_resume(
            HighRiskDecisionInput(**request.model_dump()),
            context=context,
            actor_context=ApprovalActorContext(actor_id="USR-AGENT-001"),
        )
        if result.approval is None:
            raise ValueError(result.message)
        self._results[self._conversation_by_approval[approval_id]] = result
        return result

    def result_for(self, conversation_id: str) -> HighRiskWorkflowResult | None:
        return self._results.get(conversation_id)


console = ApprovalConsole()


@router.get("")
def list_approvals() -> tuple[ApprovalTaskSummary, ...]:
    return console.list()


@router.post("/{approval_id}/decisions")
def decide(approval_id: str, request: ApprovalDecisionRequest) -> ApprovalTaskSummary:
    try:
        result = console.decide(approval_id, request)
        assert result.approval is not None
        return result.approval
    except ValueError as error:
        raise HTTPException(status_code=409, detail="approval unavailable") from error
