from dataclasses import dataclass, replace
from enum import StrEnum
from threading import Lock

from customer_service.approvals.schemas import ApprovalTaskSummary
from customer_service.service_cases.schemas import ServiceCaseSummary


class RecoveryOperationState(StrEnum):
    NOT_STARTED = "not_started"
    COMPLETED = "completed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class StoredRecoveryCheckpoint:
    workflow_id: str
    approval: ApprovalTaskSummary
    workflow_version: str | None = None
    checkpoint_schema_version: int | None = None
    revision: int = 1
    operation_state: RecoveryOperationState = RecoveryOperationState.NOT_STARTED
    service_case: ServiceCaseSummary | None = None


class InMemoryRecoveryCheckpointRepository:
    def __init__(self, records: tuple[StoredRecoveryCheckpoint, ...] = ()) -> None:
        self._records = {record.workflow_id: record for record in records}
        self._lock = Lock()

    def save_if_absent(self, record: StoredRecoveryCheckpoint) -> StoredRecoveryCheckpoint:
        with self._lock:
            return self._records.setdefault(record.workflow_id, record)

    def find(self, workflow_id: str) -> StoredRecoveryCheckpoint | None:
        return self._records.get(workflow_id)

    def mark_unknown(self, workflow_id: str, *, expected_revision: int) -> bool:
        with self._lock:
            record = self._records.get(workflow_id)
            if record is not None and record.revision == expected_revision:
                self._records[workflow_id] = replace(
                    record,
                    revision=record.revision + 1,
                    operation_state=RecoveryOperationState.UNKNOWN,
                    service_case=None,
                )
                return True
            return False

    def mark_completed(
        self, workflow_id: str, service_case: ServiceCaseSummary, *, expected_revision: int
    ) -> bool:
        with self._lock:
            record = self._records.get(workflow_id)
            if record is not None and record.revision == expected_revision:
                self._records[workflow_id] = replace(
                    record,
                    revision=record.revision + 1,
                    operation_state=RecoveryOperationState.COMPLETED,
                    service_case=service_case,
                )
                return True
            return False

    def export(self) -> tuple[StoredRecoveryCheckpoint, ...]:
        return tuple(self._records.values())
