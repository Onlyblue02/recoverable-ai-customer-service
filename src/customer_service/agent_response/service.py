"""T-606: resolve trusted evidence, draft through a model, then gate deterministically."""

import hashlib
import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import TypeVar, cast

from customer_service.agent_response.schemas import (
    AgentResponseAudit,
    AgentResponseOutcome,
    AgentResponseResult,
    ResolvedEvidence,
    TrustedEvidenceSnapshot,
)
from customer_service.agent_runtime.executor import ControlledAgentExecutor
from customer_service.agent_runtime.schemas import (
    AgentEventType,
    AgentReasonCode,
    AgentState,
    AgentStatus,
)
from customer_service.agent_tools.evidence import EvidenceVerifier
from customer_service.agent_tools.schemas import EvidenceBinding, EvidenceRecord, ToolId
from customer_service.approvals.schemas import ApprovalTaskSummary
from customer_service.eligibility.schemas import EligibilityResult
from customer_service.model_gateway.gateway import ModelGateway
from customer_service.model_gateway.schemas import (
    AgentResponseDraftCandidate,
    EvidenceSnippet,
    ModelRequest,
    ModelResultStatus,
    ModelTask,
)
from customer_service.response_gate.schemas import (
    ResponseDraft,
    ResponseEvidenceContext,
    ResponseGateAction,
)
from customer_service.response_gate.service import ResponseGateService
from customer_service.service_cases.schemas import ServiceCaseSummary
from customer_service.tools.schemas import AuthorizedOrderFacts

T = TypeVar("T")
_CONFLICT = object()


class EvidenceContextResolver:
    """Resolve only authority-verified records and their executor-retained snapshots."""

    def __init__(self, verifier: EvidenceVerifier) -> None:
        self._verifier = verifier

    def resolve(
        self, state: AgentState, records: tuple[EvidenceRecord, ...], *, now: datetime
    ) -> tuple[ResolvedEvidence, ...] | None:
        if len(records) != len({record.evidence_id for record in records}):
            return None
        resolved: list[ResolvedEvidence] = []
        for record in records:
            binding = EvidenceBinding(
                conversation_id=state.conversation_id,
                turn_id=state.turn_id,
                user_id=state.user_id,
                order_id=record.order_id,
                order_item_id=record.order_item_id,
                workflow_id=record.workflow_id,
                expected_tool_id=record.tool_id,
                expected_contract_version="tool-contract-v1",
            )
            payload = self._verifier.resolve_payload(record, binding, now=now)
            if not isinstance(payload, TrustedEvidenceSnapshot):
                return None
            item = ResolvedEvidence(record=record, snapshot=payload)
            if not self._snapshot_matches(item):
                return None
            resolved.append(item)
        return tuple(resolved)

    @staticmethod
    def _snapshot_matches(item: ResolvedEvidence) -> bool:
        record, snapshot = item.record, item.snapshot
        fields = {(field.name, field.value) for field in record.public_fields}
        if snapshot.order is not None and snapshot.order.order_id != record.order_id:
            return False
        if snapshot.eligibility is not None:
            binding = snapshot.eligibility.input_binding
            if (
                binding is None
                or binding.order_id != record.order_id
                or binding.order_item_id != record.order_item_id
            ):
                return False
            if (
                record.tool_id is ToolId.RETURN_EVALUATE
                and (
                    "eligibility_code",
                    snapshot.eligibility.status.value,
                )
                not in fields
            ):
                return False
        if snapshot.service_case is not None and (
            snapshot.service_case.order_id != record.order_id
            or snapshot.service_case.order_item_id != record.order_item_id
            or ("service_case_id", snapshot.service_case.service_case_id) not in fields
        ):
            return False
        if snapshot.approval is not None and (
            snapshot.approval.order.order_id != record.order_id
            or snapshot.approval.order_item_id != record.order_item_id
        ):
            return False
        if (
            snapshot.approval is not None
            and record.tool_id in {ToolId.APPROVAL_GET_STATUS, ToolId.HIGH_RISK_START_OR_GET}
            and ("approval_id", snapshot.approval.approval_id) not in fields
        ):
            return False
        citation_pairs = {
            (item.policy_id, item.policy_version) for item in snapshot.policy_citations
        }
        recorded_ids = {value for name, value in fields if name == "policy_id"}
        recorded_versions = {value for name, value in fields if name == "policy_version"}
        if (
            record.tool_id in {ToolId.POLICY_LOOKUP, ToolId.RETURN_EVALUATE}
            and citation_pairs
            and (
                {policy_id for policy_id, _ in citation_pairs} != recorded_ids
                or {version for _, version in citation_pairs} != recorded_versions
            )
        ):
            return False
        expected = {
            ToolId.POLICY_LOOKUP: bool(snapshot.policy_citations),
            ToolId.ORDER_GET_AUTHORIZED: snapshot.order is not None,
            ToolId.RETURN_EVALUATE: snapshot.eligibility is not None,
            ToolId.SERVICE_CASE_CREATE: snapshot.service_case is not None,
            ToolId.APPROVAL_GET_STATUS: snapshot.approval is not None,
            ToolId.HIGH_RISK_START_OR_GET: snapshot.approval is not None,
            ToolId.HIGH_RISK_RESUME: snapshot.approval is not None
            or snapshot.service_case is not None,
        }
        return expected.get(record.tool_id, False)


class AgentResponseService:
    def __init__(
        self,
        *,
        executor: ControlledAgentExecutor,
        model_gateway: ModelGateway,
        evidence_verifier: EvidenceVerifier,
        gate: ResponseGateService | None = None,
    ) -> None:
        self._executor = executor
        self._model = model_gateway
        self._resolver = EvidenceContextResolver(evidence_verifier)
        self._gate = gate or ResponseGateService()

    def generate(
        self,
        state: AgentState,
        *,
        text: str,
        evidence: tuple[EvidenceRecord, ...],
        prompt_version: str,
        now: datetime | None = None,
    ) -> AgentResponseResult:
        current_time = now or datetime.now(UTC)
        input_digest = hashlib.sha256(text.encode()).hexdigest()
        evidence_ids = tuple(record.evidence_id for record in evidence)
        resolved = self._resolver.resolve(state, evidence, now=current_time)
        if state.status is not AgentStatus.DRAFTING or not evidence or resolved is None:
            return self._failed(
                state,
                prompt_version=prompt_version,
                input_digest=input_digest,
                evidence_ids=evidence_ids,
                model_status=ModelResultStatus.INVALID_OUTPUT,
                code=AgentReasonCode.RESPONSE_EVIDENCE_INVALID,
            )
        snippets = tuple(self._snippet(item) for item in resolved)
        response = self._model.generate(
            ModelRequest(
                case_id=state.turn_id,
                task=ModelTask.AGENT_RESPONSE_DRAFT_GENERATION,
                text=text,
                prompt_version=prompt_version,
                evidence=snippets,
            )
        )
        if response.status is not ModelResultStatus.SUCCEEDED or not isinstance(
            response.output, AgentResponseDraftCandidate
        ):
            code = (
                AgentReasonCode.RESPONSE_MODEL_INVALID
                if response.status is ModelResultStatus.INVALID_OUTPUT
                else AgentReasonCode.RESPONSE_MODEL_UNAVAILABLE
            )
            return self._failed(
                state,
                prompt_version=prompt_version,
                input_digest=input_digest,
                evidence_ids=evidence_ids,
                model_status=response.status,
                code=code,
            )
        selected = self._select(response.output, resolved)
        if selected is None:
            return self._failed(
                state,
                prompt_version=prompt_version,
                input_digest=input_digest,
                evidence_ids=evidence_ids,
                model_status=response.status,
                code=AgentReasonCode.RESPONSE_EVIDENCE_INVALID,
            )
        draft, context = selected
        gating = self._executor.apply_event(state, AgentEventType.MODEL_RESULT)
        gate_result = self._gate.evaluate(draft, evidence=context)
        targets = {
            ResponseGateAction.ALLOW: (
                AgentStatus.COMPLETED,
                AgentReasonCode.RESPONSE_GATE_ALLOWED,
                AgentResponseOutcome.ALLOWED,
            ),
            ResponseGateAction.SAFE_REWRITE: (
                AgentStatus.COMPLETED,
                AgentReasonCode.RESPONSE_GATE_REWRITTEN,
                AgentResponseOutcome.SAFE_REWRITE,
            ),
            ResponseGateAction.CLARIFY: (
                AgentStatus.CLARIFYING,
                AgentReasonCode.RESPONSE_GATE_CLARIFY,
                AgentResponseOutcome.CLARIFY,
            ),
            ResponseGateAction.ESCALATE: (
                AgentStatus.ESCALATING,
                AgentReasonCode.RESPONSE_GATE_ESCALATE,
                AgentResponseOutcome.ESCALATE,
            ),
        }
        target, code, outcome = targets[gate_result.action]
        final_state = self._executor.route_response_gate(gating, target=target, code=code)
        public = gate_result.message if gate_result.response is not None else None
        return AgentResponseResult(
            state=final_state,
            outcome=outcome,
            public_response=public,
            gate=gate_result,
            audit=AgentResponseAudit(
                schema_version=response.output.schema_version,
                prompt_version=prompt_version,
                input_digest=input_digest,
                evidence_ids=tuple(
                    dict.fromkeys(
                        evidence_id
                        for claim in response.output.claims
                        for evidence_id in claim.evidence_ids
                    )
                ),
                model_status=response.status,
                evidence_valid=True,
                gate_action=gate_result.action,
                reason_code=code,
            ),
        )

    @staticmethod
    def _snippet(item: ResolvedEvidence) -> EvidenceSnippet:
        payload = {
            "tool_id": item.record.tool_id.value,
            "public_fields": [field.model_dump() for field in item.record.public_fields],
        }
        return EvidenceSnippet(
            evidence_id=item.record.evidence_id,
            text=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        )

    @staticmethod
    def _select(
        candidate: AgentResponseDraftCandidate, resolved: tuple[ResolvedEvidence, ...]
    ) -> tuple[ResponseDraft, ResponseEvidenceContext] | None:
        by_id = {item.record.evidence_id: item for item in resolved}
        cited: list[ResolvedEvidence] = []
        claim_types = {claim.claim_type for claim in candidate.claims}
        for claim in candidate.claims:
            items = [by_id.get(evidence_id) for evidence_id in claim.evidence_ids]
            if any(item is None for item in items):
                return None
            typed_items = [item for item in items if item is not None]
            if not all(
                AgentResponseService._supports(claim.claim_type, item) for item in typed_items
            ):
                return None
            cited.extend(typed_items)
        snapshots = [item.snapshot for item in dict.fromkeys(cited)]
        policies = tuple(
            dict.fromkeys(
                citation for snapshot in snapshots for citation in snapshot.policy_citations
            )
        )
        order = AgentResponseService._unique(snapshot.order for snapshot in snapshots)
        eligibility = AgentResponseService._unique(snapshot.eligibility for snapshot in snapshots)
        service_case = AgentResponseService._unique(snapshot.service_case for snapshot in snapshots)
        approval = AgentResponseService._unique(snapshot.approval for snapshot in snapshots)
        if any(value is _CONFLICT for value in (order, eligibility, service_case, approval)):
            return None
        order_value = cast("AuthorizedOrderFacts | None", order)
        eligibility_value = cast("EligibilityResult | None", eligibility)
        service_case_value = cast("ServiceCaseSummary | None", service_case)
        approval_value = cast("ApprovalTaskSummary | None", approval)
        draft = ResponseDraft(
            message=candidate.text,
            policy_citations=policies if "policy" in claim_types else (),
            order=order_value if "order" in claim_types else None,
            eligibility=eligibility_value if "eligibility" in claim_types else None,
            service_case=service_case_value if "completion" in claim_types else None,
            approval=approval_value if "approval" in claim_types else None,
            claims_policy_conclusion="policy" in claim_types,
            claims_order_facts="order" in claim_types,
            claims_eligibility="eligibility" in claim_types,
            claims_completion="completion" in claim_types,
        )
        context = ResponseEvidenceContext(
            policy_citations=policies,
            current_user_id=(cited[0].record.user_id if cited else None),
            order=order_value,
            eligibility=eligibility_value,
            service_case=service_case_value,
            approval=approval_value,
        )
        return draft, context

    @staticmethod
    def _supports(claim_type: str, item: ResolvedEvidence) -> bool:
        snapshot = item.snapshot
        return {
            "policy": bool(snapshot.policy_citations),
            "order": snapshot.order is not None,
            "eligibility": snapshot.eligibility is not None,
            "approval": snapshot.approval is not None,
            "completion": snapshot.service_case is not None,
        }[claim_type]

    @staticmethod
    def _unique(values: Iterable[T | None]) -> T | object | None:
        present = tuple(dict.fromkeys(value for value in values if value is not None))
        if len(present) > 1:
            return _CONFLICT
        return present[0] if present else None

    def _failed(
        self,
        state: AgentState,
        *,
        prompt_version: str,
        input_digest: str,
        evidence_ids: tuple[str, ...],
        model_status: ModelResultStatus,
        code: AgentReasonCode,
    ) -> AgentResponseResult:
        failed = self._executor.fail_response_model(state, code)
        return AgentResponseResult(
            state=failed,
            outcome=AgentResponseOutcome.FAILED_SAFE,
            audit=AgentResponseAudit(
                schema_version="agent-response-draft-v1",
                prompt_version=prompt_version,
                input_digest=input_digest,
                evidence_ids=evidence_ids,
                model_status=model_status,
                evidence_valid=code is not AgentReasonCode.RESPONSE_EVIDENCE_INVALID,
                reason_code=code,
            ),
        )
