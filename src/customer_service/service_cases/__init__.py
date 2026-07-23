"""Simulated return service-case creation with deterministic duplicate protection."""

from customer_service.service_cases.repository import InMemoryServiceCaseRepository
from customer_service.service_cases.schemas import (
    ServiceCaseAccessContext,
    ServiceCaseCreateRequest,
    ServiceCaseResult,
)
from customer_service.service_cases.service import ServiceCaseService

__all__ = [
    "InMemoryServiceCaseRepository",
    "ServiceCaseAccessContext",
    "ServiceCaseCreateRequest",
    "ServiceCaseResult",
    "ServiceCaseService",
]
