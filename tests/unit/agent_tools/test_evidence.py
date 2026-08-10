from datetime import UTC, datetime, timedelta

from customer_service.agent_runtime.executor import ControlledAgentExecutor
from customer_service.agent_tools.evidence import EvidenceRejectReason, InMemoryEvidenceAuthority
from customer_service.agent_tools.schemas import (
    EvidenceBinding,
    EvidenceIssue,
    EvidencePublicField,
    EvidenceRecord,
    EvidenceScope,
    EvidenceStatus,
    ToolId,
    ToolResultStatus,
    TrustedExecutionReceipt,
)


class ControlledReceiptFixtureAuthority:
    """Test-only controlled receipt source; production authority has no receipt registration API."""

    def __init__(self) -> None:
        self._records: dict[str, EvidenceRecord] = {}
        self._revoked: set[str] = set()
        self._receipts: set[TrustedExecutionReceipt] = set()

    def create_receipt(self, issue: EvidenceIssue) -> TrustedExecutionReceipt:
        receipt = _receipt(issue)
        self._receipts.add(receipt)
        return receipt

    def issue_from_trusted_receipt(
        self, receipt: TrustedExecutionReceipt, *, payload: object | None = None
    ) -> EvidenceRecord | None:
        del payload
        if receipt not in self._receipts or receipt.result_status is not ToolResultStatus.SUCCEEDED:
            return None
        if receipt.scope is EvidenceScope.WORKFLOW and receipt.workflow_id is None:
            return None
        record = EvidenceRecord(
            evidence_id=f"EVD-FIXTURE-{receipt.execution_id}",
            execution_id=receipt.execution_id,
            conversation_id=receipt.conversation_id,
            turn_id=receipt.turn_id,
            user_id=receipt.user_id,
            tool_id=receipt.tool_id,
            contract_version=receipt.contract_version,
            scope=receipt.scope,
            workflow_id=receipt.workflow_id,
            order_id=receipt.order_id,
            order_item_id=receipt.order_item_id,
            public_fields=receipt.public_fields,
            payload_digest="fixture-payload",
            expires_at=receipt.expires_at,
            proof="fixture-record-proof",
        )
        self._records[record.evidence_id] = record
        return record

    def invalidate(self, record: EvidenceRecord, *, reason: str) -> EvidenceRecord:
        self._revoked.add(record.evidence_id)
        return record.model_copy(
            update={"status": EvidenceStatus.INVALIDATED, "invalidation_reason": reason}
        )

    def verify(
        self, record: EvidenceRecord, binding: EvidenceBinding, *, now: datetime
    ) -> EvidenceRejectReason | None:
        if record.evidence_id in self._revoked:
            return EvidenceRejectReason.INVALIDATED
        expected = self._records.get(record.evidence_id)
        if expected is None:
            return EvidenceRejectReason.UNTRUSTED_ISSUER
        if record != expected:
            return EvidenceRejectReason.PAYLOAD_MISMATCH
        if record.expires_at <= now:
            return EvidenceRejectReason.EXPIRED
        if (record.conversation_id, record.turn_id, record.user_id, record.order_id) != (
            binding.conversation_id,
            binding.turn_id,
            binding.user_id,
            binding.order_id,
        ):
            return EvidenceRejectReason.BINDING_MISMATCH
        if binding.expected_contract_version != record.contract_version:
            return EvidenceRejectReason.CONTRACT_MISMATCH
        if record.scope is EvidenceScope.WORKFLOW and record.workflow_id != binding.workflow_id:
            return EvidenceRejectReason.BINDING_MISMATCH
        return None

    def resolve_payload(
        self, record: EvidenceRecord, binding: EvidenceBinding, *, now: datetime
    ) -> object | None:
        del record, binding, now
        return None


def _issue(**updates: object) -> EvidenceIssue:
    return EvidenceIssue(
        execution_id="EXEC-1",
        tool_id=ToolId.ORDER_GET_AUTHORIZED,
        contract_version="tool-contract-v1",
        result_status=ToolResultStatus.SUCCEEDED,
        order_id="ORD-1",
        order_item_id="ITEM-1",
        public_fields=(EvidencePublicField(name="order_id", value="ORD-1"),),
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    ).model_copy(update=updates)


def _receipt(
    issue: EvidenceIssue, *, proof: str = "fixture-controlled-proof"
) -> TrustedExecutionReceipt:
    return TrustedExecutionReceipt(
        execution_id=issue.execution_id,
        conversation_id="CONV-1",
        turn_id="TURN-1",
        user_id="USER-1",
        tool_id=issue.tool_id,
        contract_version=issue.contract_version,
        result_status=issue.result_status,
        scope=issue.scope,
        workflow_id=issue.workflow_id,
        order_id=issue.order_id,
        order_item_id=issue.order_item_id,
        public_fields=issue.public_fields,
        expires_at=issue.expires_at,
        proof=proof,
    )


def _binding(**updates: object) -> EvidenceBinding:
    return EvidenceBinding(
        conversation_id="CONV-1",
        turn_id="TURN-1",
        user_id="USER-1",
        order_id="ORD-1",
        order_item_id="ITEM-1",
        expected_tool_id=ToolId.ORDER_GET_AUTHORIZED,
        expected_contract_version="tool-contract-v1",
    ).model_copy(update=updates)


def _fixture_executor(authority: ControlledReceiptFixtureAuthority) -> ControlledAgentExecutor:
    executor = ControlledAgentExecutor()
    executor._evidence_authority = authority
    return executor


def test_production_authority_exposes_no_receipt_registration_or_fixture_method() -> None:
    executor = ControlledAgentExecutor()
    verifier = executor.evidence_authority
    assert not hasattr(verifier, "issue_from_trusted_receipt")
    assert not hasattr(verifier, "register")
    assert not hasattr(verifier, "_issue_for_trusted_fixture")


def test_direct_success_issue_or_forged_receipt_cannot_issue_public_evidence() -> None:
    executor = ControlledAgentExecutor()
    assert not hasattr(executor, "issue_evidence")
    fake_issue = _issue(
        tool_id=ToolId.SERVICE_CASE_CREATE,
        order_id="ORD-VICTIM",
        order_item_id="ITEM-VICTIM",
        public_fields=(EvidencePublicField(name="service_case_id", value="CASE-FAKE"),),
    )
    assert executor.issue_evidence_from_trusted_receipt(_receipt(fake_issue)) is None


def test_direct_production_authority_cannot_sign_forged_business_facts() -> None:
    authority = InMemoryEvidenceAuthority()
    fake_receipt = _receipt(
        _issue(
            tool_id=ToolId.SERVICE_CASE_CREATE,
            order_id="ORD-VICTIM",
            order_item_id="ITEM-VICTIM",
            public_fields=(
                EvidencePublicField(name="service_case_id", value="CASE-FAKE"),
                EvidencePublicField(name="approval_id", value="APPROVAL-FAKE"),
                EvidencePublicField(name="eligibility_code", value="eligible"),
            ),
        ),
        proof="attacker-proof",
    )

    assert not hasattr(authority, "_issue_for_controlled_execution")
    assert not hasattr(authority, "register")
    assert authority.issue_from_trusted_receipt(fake_receipt) is None
    # Even the remaining digest helper is not a signing capability.
    assert authority._receipt_key(fake_receipt)
    assert authority.issue_from_trusted_receipt(fake_receipt) is None


def test_only_test_controlled_receipt_fixture_can_issue_and_verify() -> None:
    authority = ControlledReceiptFixtureAuthority()
    executor = _fixture_executor(authority)
    record = executor.issue_evidence_from_trusted_receipt(authority.create_receipt(_issue()))
    assert record is not None
    assert executor.evidence_authority.verify(record, _binding(), now=datetime.now(UTC)) is None
    forged = _receipt(_issue(), proof="attacker-proof")
    assert executor.issue_evidence_from_trusted_receipt(forged) is None


def test_receipt_drift_failure_unknown_and_lifecycle_are_rejected() -> None:
    authority = ControlledReceiptFixtureAuthority()
    executor = _fixture_executor(authority)
    receipt = authority.create_receipt(_issue())
    record = executor.issue_evidence_from_trusted_receipt(receipt)
    assert record is not None
    assert (
        executor.issue_evidence_from_trusted_receipt(
            receipt.model_copy(update={"execution_id": "EXEC-FAKE"})
        )
        is None
    )
    assert (
        executor.issue_evidence_from_trusted_receipt(
            authority.create_receipt(_issue(result_status=ToolResultStatus.FAILED))
        )
        is None
    )
    assert (
        executor.issue_evidence_from_trusted_receipt(
            authority.create_receipt(_issue(result_status=ToolResultStatus.WRITE_STATUS_UNKNOWN))
        )
        is None
    )
    authority.invalidate(record, reason="superseded")
    for candidate in (record, record.model_copy(update={"status": EvidenceStatus.ACTIVE})):
        assert executor.evidence_authority.verify(candidate, _binding(), now=datetime.now(UTC)) is (
            EvidenceRejectReason.INVALIDATED
        )
