"""Deterministic return eligibility and risk rules."""

from customer_service.eligibility.config import EligibilityRuleConfig
from customer_service.eligibility.engine import EligibilityEngine
from customer_service.eligibility.schemas import EligibilityRequest, EligibilityResult

__all__ = [
    "EligibilityEngine",
    "EligibilityRequest",
    "EligibilityResult",
    "EligibilityRuleConfig",
]
