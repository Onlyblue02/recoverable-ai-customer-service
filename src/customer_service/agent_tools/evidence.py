"""T-604 evidence issuance and verification contract; it never calls business tools."""

import hashlib
import json
import secrets
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from customer_service.agent_tools.schemas import (
    EvidenceBinding,
    EvidenceRecord,
    EvidenceScope,
    EvidenceStatus,
    ToolResultStatus,
    TrustedExecutionReceipt,
)


class EvidenceRejectReason(StrEnum):
    UNTRUSTED_ISSUER = "EVIDENCE_UNTRUSTED_ISSUER"
    BINDING_MISMATCH = "EVIDENCE_BINDING_MISMATCH"
    CONTRACT_MISMATCH = "EVIDENCE_CONTRACT_MISMATCH"
    EXPIRED = "EVIDENCE_EXPIRED"
    INVALIDATED = "EVIDENCE_INVALIDATED"
    NON_PUBLIC = "EVIDENCE_NON_PUBLIC"
    PAYLOAD_MISMATCH = "EVIDENCE_PAYLOAD_MISMATCH"


class EvidenceAuthority(Protocol):
    def issue_from_trusted_receipt(
        self, receipt: TrustedExecutionReceipt
    ) -> EvidenceRecord | None: ...

    def invalidate(self, record: EvidenceRecord, *, reason: str) -> EvidenceRecord: ...

    def verify(
        self, record: EvidenceRecord, binding: EvidenceBinding, *, now: datetime
    ) -> EvidenceRejectReason | None: ...


class EvidenceVerifier:
    """Public verification facade; it intentionally cannot create or register receipts."""

    def __init__(self, authority: EvidenceAuthority) -> None:
        self._authority = authority

    def invalidate(self, record: EvidenceRecord, *, reason: str) -> EvidenceRecord:
        return self._authority.invalidate(record, reason=reason)

    def verify(
        self, record: EvidenceRecord, binding: EvidenceBinding, *, now: datetime
    ) -> EvidenceRejectReason | None:
        return self._authority.verify(record, binding, now=now)


class InMemoryEvidenceAuthority:
    """T-604 test authority. T-605 may supply actual successful tool results to it."""

    def __init__(self) -> None:
        self._receipt_proofs: dict[str, str] = {}
        self._records_by_receipt: dict[str, EvidenceRecord] = {}
        self._revoked_ids: set[str] = set()

    def issue_from_trusted_receipt(self, receipt: TrustedExecutionReceipt) -> EvidenceRecord | None:
        """Issue only from a receipt verified against this authority's private execution ledger."""
        if receipt.result_status is not ToolResultStatus.SUCCEEDED:
            return None
        if receipt.scope is EvidenceScope.WORKFLOW and receipt.workflow_id is None:
            return None
        receipt_key = self._receipt_key(receipt)
        if not secrets.compare_digest(self._receipt_proofs.get(receipt_key, ""), receipt.proof):
            return None
        existing = self._records_by_receipt.get(receipt_key)
        if existing is not None:
            return existing
        evidence_id = f"EVD-{secrets.token_urlsafe(18)}"
        draft = EvidenceRecord(
            evidence_id=evidence_id,
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
            payload_digest="pending",
            expires_at=receipt.expires_at,
            proof="pending",
        )
        digest = self._digest(draft)
        proof = secrets.token_urlsafe(24)
        record = draft.model_copy(update={"payload_digest": digest, "proof": proof})
        self._records_by_receipt[receipt_key] = record
        return record

    def invalidate(self, record: EvidenceRecord, *, reason: str) -> EvidenceRecord:
        """Immutable replacement, never an in-place alteration of an active record."""
        self._revoked_ids.add(record.evidence_id)
        return record.model_copy(
            update={"status": EvidenceStatus.INVALIDATED, "invalidation_reason": reason}
        )

    def verify(
        self, record: EvidenceRecord, binding: EvidenceBinding, *, now: datetime
    ) -> EvidenceRejectReason | None:
        if record.evidence_id in self._revoked_ids:
            return EvidenceRejectReason.INVALIDATED
        expected = next(
            (
                item
                for item in self._records_by_receipt.values()
                if item.evidence_id == record.evidence_id
            ),
            None,
        )
        if expected is None or not secrets.compare_digest(expected.proof, record.proof):
            return EvidenceRejectReason.UNTRUSTED_ISSUER
        if record.payload_digest != self._digest(record):
            return EvidenceRejectReason.PAYLOAD_MISMATCH
        if record.status is EvidenceStatus.INVALIDATED:
            return EvidenceRejectReason.INVALIDATED
        if record.status is EvidenceStatus.NON_PUBLIC:
            return EvidenceRejectReason.NON_PUBLIC
        if record.expires_at <= now:
            return EvidenceRejectReason.EXPIRED
        if not self._binding_matches(record, binding):
            return EvidenceRejectReason.BINDING_MISMATCH
        if (
            binding.expected_tool_id is not None and record.tool_id is not binding.expected_tool_id
        ) or (
            binding.expected_contract_version is not None
            and record.contract_version != binding.expected_contract_version
        ):
            return EvidenceRejectReason.CONTRACT_MISMATCH
        return None

    @staticmethod
    def _receipt_key(receipt: TrustedExecutionReceipt) -> str:
        payload = receipt.model_dump(exclude={"proof"}, mode="json")
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    @staticmethod
    def _binding_matches(record: EvidenceRecord, binding: EvidenceBinding) -> bool:
        if (record.conversation_id, record.turn_id, record.user_id) != (
            binding.conversation_id,
            binding.turn_id,
            binding.user_id,
        ):
            return False
        if binding.order_id is not None and record.order_id != binding.order_id:
            return False
        if binding.order_item_id is not None and record.order_item_id != binding.order_item_id:
            return False
        return not (
            record.scope is EvidenceScope.WORKFLOW and record.workflow_id != binding.workflow_id
        )

    @staticmethod
    def _digest(record: EvidenceRecord) -> str:
        payload = {
            "record_version": record.record_version,
            "execution_id": record.execution_id,
            "conversation_id": record.conversation_id,
            "turn_id": record.turn_id,
            "user_id": record.user_id,
            "tool_id": record.tool_id,
            "contract_version": record.contract_version,
            "scope": record.scope,
            "workflow_id": record.workflow_id,
            "order_id": record.order_id,
            "order_item_id": record.order_item_id,
            "public_fields": [field.model_dump() for field in record.public_fields],
            "expires_at": record.expires_at.isoformat(),
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
