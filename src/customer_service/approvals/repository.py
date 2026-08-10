from dataclasses import dataclass, replace
from datetime import datetime
from threading import Lock
from typing import Protocol

from customer_service.approvals.schemas import ApprovalDecision, ApprovalStatus
from customer_service.eligibility.schemas import EligibilityResult
from customer_service.rag.schemas import PolicyCitation
from customer_service.tools.schemas import AuthorizedOrderFacts


@dataclass(frozen=True)
class StoredApprovalTask:
    approval_id: str
    idempotency_key: str
    user_id: str
    order: AuthorizedOrderFacts
    order_item_id: str
    conversation_summary: str
    policy_citations: tuple[PolicyCitation, ...]
    eligibility: EligibilityResult
    status: ApprovalStatus
    version: int
    decision: ApprovalDecision | None = None
    note: str | None = None
    recommendation: str | None = None
    decided_by: str | None = None
    decided_at: datetime | None = None


@dataclass(frozen=True)
class ApprovalTaskDraft:
    idempotency_key: str
    user_id: str
    order: AuthorizedOrderFacts
    order_item_id: str
    conversation_summary: str
    policy_citations: tuple[PolicyCitation, ...]
    eligibility: EligibilityResult


@dataclass(frozen=True)
class ApprovalDecisionWriteResult:
    """The repository-level compare-and-set outcome for one decision attempt."""

    task: StoredApprovalTask | None
    applied: bool


class ApprovalTaskRepository(Protocol):
    def list_tasks(self) -> tuple[StoredApprovalTask, ...]: ...

    def find_by_key(self, key: str) -> StoredApprovalTask | None: ...

    def create(self, *, draft: ApprovalTaskDraft) -> StoredApprovalTask | None: ...

    def find_by_id(self, approval_id: str) -> StoredApprovalTask | None: ...

    def delete_pending(self, *, approval_id: str, idempotency_key: str) -> bool: ...

    def decide(
        self,
        *,
        approval_id: str,
        expected_version: int,
        decision: ApprovalDecision,
        note: str,
        recommendation: str | None,
        actor_id: str,
        decided_at: datetime,
    ) -> ApprovalDecisionWriteResult: ...


class InMemoryApprovalTaskRepository:
    """Process-local deterministic repository; persistence and recovery are T-302."""

    def __init__(self) -> None:
        self._by_key: dict[str, StoredApprovalTask] = {}
        self._by_id: dict[str, StoredApprovalTask] = {}
        self._lock = Lock()
        self._next_sequence = 1

    @property
    def task_count(self) -> int:
        return len(self._by_id)

    def find_by_key(self, key: str) -> StoredApprovalTask | None:
        return self._by_key.get(key)

    def list_tasks(self) -> tuple[StoredApprovalTask, ...]:
        return tuple(self._by_id.values())

    def create(self, *, draft: ApprovalTaskDraft) -> StoredApprovalTask | None:
        with self._lock:
            existing = self._by_key.get(draft.idempotency_key)
            if existing is not None:
                return existing
            task = StoredApprovalTask(
                approval_id=f"APR-SIM-{self._next_sequence:03d}",
                idempotency_key=draft.idempotency_key,
                user_id=draft.user_id,
                order=draft.order,
                order_item_id=draft.order_item_id,
                conversation_summary=draft.conversation_summary,
                policy_citations=draft.policy_citations,
                eligibility=draft.eligibility,
                status=ApprovalStatus.PENDING,
                version=1,
            )
            self._next_sequence += 1
            self._by_key[task.idempotency_key] = task
            self._by_id[task.approval_id] = task
            return task

    def find_by_id(self, approval_id: str) -> StoredApprovalTask | None:
        return self._by_id.get(approval_id)

    def delete_pending(self, *, approval_id: str, idempotency_key: str) -> bool:
        """Compensate only a just-created, still-pending task after checkpoint failure."""
        with self._lock:
            task = self._by_id.get(approval_id)
            if (
                task is None
                or task.idempotency_key != idempotency_key
                or task.status is not ApprovalStatus.PENDING
            ):
                return False
            self._by_id.pop(approval_id, None)
            self._by_key.pop(idempotency_key, None)
            return True

    def decide(
        self,
        *,
        approval_id: str,
        expected_version: int,
        decision: ApprovalDecision,
        note: str,
        recommendation: str | None,
        actor_id: str,
        decided_at: datetime,
    ) -> ApprovalDecisionWriteResult:
        with self._lock:
            task = self._by_id.get(approval_id)
            if task is None or task.status is not ApprovalStatus.PENDING:
                return ApprovalDecisionWriteResult(task=task, applied=False)
            if task.version != expected_version:
                return ApprovalDecisionWriteResult(task=task, applied=False)
            status = {
                ApprovalDecision.APPROVE: ApprovalStatus.APPROVED,
                ApprovalDecision.ADJUST: ApprovalStatus.ADJUSTED,
                ApprovalDecision.REJECT: ApprovalStatus.REJECTED,
            }[decision]
            decided = replace(
                task,
                status=status,
                version=task.version + 1,
                decision=decision,
                note=note,
                recommendation=recommendation,
                decided_by=actor_id,
                decided_at=decided_at,
            )
            self._by_id[approval_id] = decided
            self._by_key[task.idempotency_key] = decided
            return ApprovalDecisionWriteResult(task=decided, applied=True)
