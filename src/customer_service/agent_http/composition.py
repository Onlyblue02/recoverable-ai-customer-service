import json
from pathlib import Path

from fastapi import Request
from fastapi.testclient import TestClient

from customer_service.agent_http.gateway import DeterministicAgentGateway
from customer_service.agent_http.schemas import AgentMode
from customer_service.agent_http.service import AgentConversationService, InMemoryPolicyContexts
from customer_service.agent_workflow import AgentWorkflowService
from customer_service.approvals.repository import InMemoryApprovalTaskRepository
from customer_service.approvals.schemas import (
    ApprovalActorContext,
    ApprovalDecisionRequest,
    ApprovalTaskResultStatus,
    ApprovalTaskSummary,
)
from customer_service.approvals.service import ApprovalTaskService
from customer_service.eligibility.config import EligibilityRuleConfig
from customer_service.eligibility.engine import EligibilityEngine
from customer_service.infrastructure.clients.mock_business import HttpOrderGateway
from customer_service.infrastructure.config.settings import DeepSeekSettings
from customer_service.model_gateway.deepseek import DeepSeekModelGateway
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

ROOT = Path(__file__).parents[3]


class AgentApplication:
    """One process-local dependency graph shared by conversations and approvals."""

    def __init__(
        self,
        *,
        conversations: AgentConversationService,
        approvals: ApprovalTaskService,
        approval_repository: InMemoryApprovalTaskRepository,
    ) -> None:
        self.conversations = conversations
        self.approvals = approvals
        self.approval_repository = approval_repository

    def list_approvals(self) -> tuple[ApprovalTaskSummary, ...]:
        return tuple(
            self.approvals._summary(task) for task in self.approval_repository.list_tasks()
        )

    def decide_approval(
        self, approval_id: str, request: ApprovalDecisionRequest
    ) -> ApprovalTaskSummary:
        result = self.approvals.decide(
            approval_id,
            request,
            actor_context=ApprovalActorContext(actor_id="USR-AGENT-001"),
        )
        if result.status is not ApprovalTaskResultStatus.DECIDED or result.approval is None:
            raise ValueError("approval unavailable")
        self.conversations.resume_for_approval(result.approval.approval_id)
        return result.approval


def build_agent_application(
    *, deepseek_settings: DeepSeekSettings | None = None
) -> AgentApplication:
    data = ROOT / "data"
    settings = deepseek_settings or DeepSeekSettings()
    products = json.loads((data / "seed/products/products.v1.json").read_text(encoding="utf-8"))
    categories = {str(row["product_id"]): str(row["category"]) for row in products["products"]}
    catalog = PolicyCatalog.from_manifest(data / "manifest.json")
    orders = OrderQueryService(
        HttpOrderGateway(TestClient(create_mock_business_app(manifest_path=data / "manifest.json")))
    )
    policies = PolicyAnswerService(catalog)
    eligibility = EligibilityEngine(
        EligibilityRuleConfig.from_json(ROOT / "config/return-eligibility-rules.v1.json")
    )
    approval_repository = InMemoryApprovalTaskRepository()
    approvals = ApprovalTaskService(approval_repository)
    service_cases = ServiceCaseService(InMemoryServiceCaseRepository())
    checkpoints = InMemoryRecoveryCheckpointRepository()
    recovery = ApprovalRecoveryService(
        checkpoints, approvals=approval_repository, service_cases=service_cases
    )
    high_risk = HighRiskReturnWorkflowService(
        orders=orders,
        policies=policies,
        policy_catalog=catalog,
        product_categories=categories,
        eligibility=eligibility,
        approvals=approvals,
        recovery=recovery,
        checkpoints=checkpoints,
        gate=ResponseGateService(),
    )
    policy_contexts = InMemoryPolicyContexts()

    def workflow(model_gateway: object) -> AgentWorkflowService:
        return AgentWorkflowService(
            model_gateway=model_gateway,  # type: ignore[arg-type]
            orders=orders,
            policies=policies,
            catalog=catalog,
            product_categories=categories,
            eligibility=eligibility,
            high_risk=high_risk,
            recovery=recovery,
            approvals=approvals,
            service_cases=service_cases,
            policy_contexts=policy_contexts,
        )

    conversations = AgentConversationService(
        workflows={
            AgentMode.FAKE: workflow(DeterministicAgentGateway()),
            AgentMode.DEEPSEEK: workflow(DeepSeekModelGateway(settings)),
        },
        deepseek_configured=settings.is_configured,
        policy_contexts=policy_contexts,
        catalog=catalog,
    )
    return AgentApplication(
        conversations=conversations,
        approvals=approvals,
        approval_repository=approval_repository,
    )


def get_agent_application(request: Request) -> AgentApplication:
    return request.app.state.agent_application  # type: ignore[no-any-return]
