from datetime import date, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from customer_service.eligibility.config import EligibilityRuleConfig
from customer_service.eligibility.engine import EligibilityEngine
from customer_service.eligibility.schemas import (
    EligibilityConclusion,
    EligibilityItemFacts,
    EligibilityRequest,
    EligibilityResult,
    EligibilityStatus,
    MissingField,
    ReturnReason,
    RiskReason,
)
from customer_service.rag.schemas import PolicyDocument
from customer_service.tools.schemas import (
    AuthorizedOrderFacts,
    AuthorizedOrderItem,
)

ROOT = Path(__file__).parents[3]
CONFIG_PATH = ROOT / "config" / "return-eligibility-rules.v1.json"
DEFAULT_DELIVERED_AT = datetime.fromisoformat("2026-07-18T10:00:00+00:00")


def order(
    *,
    delivered_at: datetime | None = DEFAULT_DELIVERED_AT,
    total_amount: str = "129.00",
    status: str = "delivered",
) -> AuthorizedOrderFacts:
    return AuthorizedOrderFacts(
        order_id="ORD-TEST-001",
        status=status,
        placed_at=datetime.fromisoformat("2026-07-15T09:00:00+00:00"),
        delivered_at=delivered_at,
        currency="CNY",
        total_amount=total_amount,
        items=(
            AuthorizedOrderItem(
                order_item_id="ITEM-TEST-001",
                product_id="PROD-TEST-001",
                quantity=1,
                unit_price=total_amount,
                line_total=total_amount,
            ),
        ),
    )


def policy(
    *,
    reason: str = "changed_mind",
    decision: str = "allow_if_resalable",
    window: int = 7,
    policy_id: str = "POL-STANDARD-001",
) -> PolicyDocument:
    return PolicyDocument(
        policy_id=policy_id,
        policy_version="1.0.0",
        title="Synthetic policy",
        source="synthetic://policy",
        status="published",
        effective_from=date(2026, 1, 1),
        effective_to=date(2026, 12, 31),
        applicable_categories=("general_merchandise",),
        return_reason=reason,
        return_window_days=window,
        decision=decision,
        content="Synthetic policy content.",
    )


def item(*, product_id: str = "PROD-TEST-001") -> EligibilityItemFacts:
    return EligibilityItemFacts(
        order_item_id="ITEM-TEST-001",
        product_id=product_id,
        category="general_merchandise",
    )


def engine() -> EligibilityEngine:
    return EligibilityEngine(EligibilityRuleConfig.from_json(CONFIG_PATH))


def request(**overrides: object) -> EligibilityRequest:
    values: dict[str, object] = {
        "order": order(),
        "item": item(),
        "return_reason": ReturnReason.CHANGED_MIND,
        "item_condition": "resalable",
        "policies": (policy(),),
    }
    values.update(overrides)
    return EligibilityRequest.model_validate(values)


def test_standard_return_is_deterministic_and_eligible() -> None:
    eligibility_engine = engine()
    eligibility_request = request()

    first = eligibility_engine.evaluate(eligibility_request)
    second = eligibility_engine.evaluate(eligibility_request)

    assert first == second
    assert first.status is EligibilityStatus.ELIGIBLE
    assert first.eligibility is EligibilityConclusion.ELIGIBLE
    assert first.requires_human_approval is False
    assert first.days_since_delivery == 2
    assert first.applicable_policy_ids == ("POL-STANDARD-001",)


def test_result_binds_the_evaluated_order_item_and_rule_version() -> None:
    result = engine().evaluate(request())

    assert result.input_binding is not None
    assert result.input_binding.order_id == "ORD-TEST-001"
    assert result.input_binding.order_item_id == "ITEM-TEST-001"
    assert result.input_binding.product_id == "PROD-TEST-001"
    assert result.input_binding.rule_version == result.rule_version


def test_seventh_day_is_inclusive() -> None:
    result = engine().evaluate(
        request(order=order(delivered_at=datetime.fromisoformat("2026-07-13T12:00:00+00:00")))
    )

    assert result.status is EligibilityStatus.ELIGIBLE
    assert result.days_since_delivery == 7
    assert "STANDARD_WINDOW_INCLUSIVE" in result.matched_rule_ids


def test_quality_issue_uses_thirty_day_policy_and_requires_verification() -> None:
    result = engine().evaluate(
        request(
            order=order(delivered_at=datetime.fromisoformat("2026-07-02T14:00:00+00:00")),
            return_reason=ReturnReason.QUALITY_ISSUE,
            item_condition=None,
            issue_code="AUDIO_LEFT_CHANNEL_SILENT",
            policies=(
                policy(
                    reason="quality_issue",
                    decision="allow_after_issue_verification",
                    window=30,
                    policy_id="POL-QUALITY-001",
                ),
            ),
        )
    )

    assert result.status is EligibilityStatus.VERIFICATION_REQUIRED
    assert result.eligibility is EligibilityConclusion.CONDITIONAL
    assert result.days_since_delivery == 18
    assert result.risk_reasons == (RiskReason.ISSUE_VERIFICATION_REQUIRED,)
    assert result.requires_human_approval is False


def test_overdue_standard_return_requires_approval() -> None:
    result = engine().evaluate(
        request(order=order(delivered_at=datetime.fromisoformat("2026-07-12T12:00:00+00:00")))
    )

    assert result.status is EligibilityStatus.REQUIRES_APPROVAL
    assert result.risk_reasons == (RiskReason.OVERDUE_EXCEPTION,)
    assert result.requires_human_approval is True
    assert result.days_since_delivery == 8


@pytest.mark.parametrize(
    ("amount", "expected_status"),
    [
        ("4999.99", EligibilityStatus.ELIGIBLE),
        ("5000.00", EligibilityStatus.REQUIRES_APPROVAL),
        ("9999.00", EligibilityStatus.REQUIRES_APPROVAL),
    ],
)
def test_high_value_threshold_is_inclusive(
    amount: str,
    expected_status: EligibilityStatus,
) -> None:
    result = engine().evaluate(request(order=order(total_amount=amount)))

    assert result.status is expected_status
    if expected_status is EligibilityStatus.REQUIRES_APPROVAL:
        assert RiskReason.HIGH_VALUE_ORDER in result.risk_reasons
        assert result.requires_human_approval is True


@pytest.mark.parametrize(
    ("overrides", "missing"),
    [
        ({"return_reason": None}, MissingField.RETURN_REASON),
        ({"item_condition": None}, MissingField.ITEM_CONDITION),
        (
            {
                "return_reason": ReturnReason.QUALITY_ISSUE,
                "item_condition": None,
                "issue_code": None,
            },
            MissingField.ISSUE_CODE,
        ),
        ({"item": None}, MissingField.TARGET_ITEM),
        ({"order": order(delivered_at=None)}, MissingField.DELIVERED_AT),
    ],
)
def test_missing_information_never_guesses(
    overrides: dict[str, object],
    missing: MissingField,
) -> None:
    result = engine().evaluate(request(**overrides))

    assert result.status is EligibilityStatus.NEEDS_INFORMATION
    assert result.eligibility is EligibilityConclusion.INDETERMINATE
    assert missing in result.missing_fields
    assert result.requires_human_approval is False


def test_item_facts_must_bind_to_authorized_order() -> None:
    result = engine().evaluate(request(item=item(product_id="PROD-OTHER-001")))

    assert result.status is EligibilityStatus.REQUIRES_APPROVAL
    assert result.risk_reasons == (RiskReason.EVIDENCE_MISMATCH,)
    assert result.applicable_policy_ids == ()


def test_policy_conflict_requires_approval_without_deterministic_eligibility() -> None:
    result = engine().evaluate(
        request(
            policies=(
                policy(policy_id="POL-ALLOW-001"),
                policy(policy_id="POL-DENY-001", decision="deny"),
            )
        )
    )

    assert result.status is EligibilityStatus.REQUIRES_APPROVAL
    assert result.eligibility is EligibilityConclusion.INDETERMINATE
    assert result.risk_reasons == (RiskReason.POLICY_CONFLICT,)


def test_single_changed_mind_deny_policy_is_deterministically_ineligible() -> None:
    eligibility_engine = engine()
    eligibility_request = request(policies=(policy(policy_id="POL-DENY-ONLY", decision="deny"),))

    first = eligibility_engine.evaluate(eligibility_request)
    second = eligibility_engine.evaluate(eligibility_request)

    assert first == second
    assert first.status is EligibilityStatus.INELIGIBLE
    assert first.eligibility is EligibilityConclusion.INELIGIBLE
    assert first.requires_human_approval is False
    assert first.applicable_policy_ids == ("POL-DENY-ONLY",)
    assert first.matched_rule_ids == ("POLICY_DENIES_RETURN",)
    assert first.risk_reasons == ()


def test_single_changed_mind_allow_policy_remains_eligible() -> None:
    result = engine().evaluate(
        request(
            policies=(
                policy(
                    policy_id="POL-ALLOW-STANDARD",
                    decision="allow_if_resalable",
                ),
            )
        )
    )

    assert result.status is EligibilityStatus.ELIGIBLE
    assert result.applicable_policy_ids == ("POL-ALLOW-STANDARD",)
    assert result.matched_rule_ids == ("STANDARD_RETURN_ELIGIBLE",)
    assert result.risk_reasons == ()
    assert result.requires_human_approval is False


def test_single_quality_allow_policy_remains_verification_required() -> None:
    result = engine().evaluate(
        request(
            return_reason=ReturnReason.QUALITY_ISSUE,
            item_condition=None,
            issue_code="AUDIO_LEFT_CHANNEL_SILENT",
            policies=(
                policy(
                    reason="quality_issue",
                    decision="allow_after_issue_verification",
                    window=30,
                    policy_id="POL-ALLOW-QUALITY",
                ),
            ),
        )
    )

    assert result.status is EligibilityStatus.VERIFICATION_REQUIRED
    assert result.applicable_policy_ids == ("POL-ALLOW-QUALITY",)
    assert result.matched_rule_ids == ("QUALITY_RETURN_WINDOW", "ISSUE_VERIFICATION")
    assert result.risk_reasons == (RiskReason.ISSUE_VERIFICATION_REQUIRED,)
    assert result.requires_human_approval is False


def test_single_quality_deny_policy_never_requires_verification() -> None:
    result = engine().evaluate(
        request(
            return_reason=ReturnReason.QUALITY_ISSUE,
            item_condition=None,
            issue_code="AUDIO_LEFT_CHANNEL_SILENT",
            policies=(
                policy(
                    reason="quality_issue",
                    decision="deny",
                    window=30,
                    policy_id="POL-DENY-QUALITY",
                ),
            ),
        )
    )

    assert result.status is EligibilityStatus.INELIGIBLE
    assert result.eligibility is EligibilityConclusion.INELIGIBLE
    assert result.applicable_policy_ids == ("POL-DENY-QUALITY",)
    assert result.matched_rule_ids == ("POLICY_DENIES_RETURN",)
    assert result.risk_reasons == ()
    assert result.requires_human_approval is False


@pytest.mark.parametrize(
    ("reason", "decision"),
    [
        (ReturnReason.CHANGED_MIND, "allow_after_issue_verification"),
        (ReturnReason.QUALITY_ISSUE, "allow_if_resalable"),
    ],
)
def test_reason_and_allow_decision_mismatch_requires_safe_approval(
    reason: ReturnReason,
    decision: str,
) -> None:
    result = engine().evaluate(
        request(
            return_reason=reason,
            item_condition=("resalable" if reason is ReturnReason.CHANGED_MIND else None),
            issue_code=("ISSUE-001" if reason is ReturnReason.QUALITY_ISSUE else None),
            policies=(
                policy(
                    reason=reason.value,
                    decision=decision,
                    window=30 if reason is ReturnReason.QUALITY_ISSUE else 7,
                    policy_id="POL-MISMATCH-001",
                ),
            ),
        )
    )

    assert result.status is EligibilityStatus.REQUIRES_APPROVAL
    assert result.eligibility is EligibilityConclusion.INDETERMINATE
    assert result.applicable_policy_ids == ("POL-MISMATCH-001",)
    assert result.matched_rule_ids == ("POLICY_DECISION_MISMATCH",)
    assert result.risk_reasons == (RiskReason.POLICY_EVIDENCE_INSUFFICIENT,)
    assert result.requires_human_approval is True


def test_unknown_policy_decision_is_stable_safe_approval() -> None:
    eligibility_engine = engine()
    eligibility_request = request(
        policies=(
            policy(
                policy_id="POL-UNKNOWN-001",
                decision="allow_when_model_feels_confident",
            ),
        )
    )

    first = eligibility_engine.evaluate(eligibility_request)
    second = eligibility_engine.evaluate(eligibility_request)

    assert first == second
    assert first.status is EligibilityStatus.REQUIRES_APPROVAL
    assert first.eligibility is EligibilityConclusion.INDETERMINATE
    assert first.applicable_policy_ids == ("POL-UNKNOWN-001",)
    assert first.matched_rule_ids == ("UNSUPPORTED_POLICY_DECISION",)
    assert first.risk_reasons == (RiskReason.POLICY_EVIDENCE_INSUFFICIENT,)
    assert first.requires_human_approval is True


def test_high_value_changed_mind_deny_still_requires_approval() -> None:
    result = engine().evaluate(
        request(
            order=order(total_amount="9999.00"),
            policies=(policy(policy_id="POL-DENY-HIGH", decision="deny"),),
        )
    )

    assert result.status is EligibilityStatus.REQUIRES_APPROVAL
    assert result.eligibility is EligibilityConclusion.INDETERMINATE
    assert result.risk_reasons == (RiskReason.HIGH_VALUE_ORDER,)
    assert result.matched_rule_ids == ("HIGH_VALUE_THRESHOLD",)
    assert result.applicable_policy_ids == ("POL-DENY-HIGH",)
    assert result.requires_human_approval is True


def test_overdue_changed_mind_deny_still_requires_approval() -> None:
    result = engine().evaluate(
        request(
            order=order(delivered_at=datetime.fromisoformat("2026-07-12T12:00:00+00:00")),
            policies=(policy(policy_id="POL-DENY-OVERDUE", decision="deny"),),
        )
    )

    assert result.status is EligibilityStatus.REQUIRES_APPROVAL
    assert result.eligibility is EligibilityConclusion.INDETERMINATE
    assert result.risk_reasons == (RiskReason.OVERDUE_EXCEPTION,)
    assert result.matched_rule_ids == ("RETURN_WINDOW_EXCEEDED",)
    assert result.applicable_policy_ids == ("POL-DENY-OVERDUE",)
    assert result.requires_human_approval is True


def test_high_value_quality_deny_cannot_bypass_approval() -> None:
    result = engine().evaluate(
        request(
            order=order(total_amount="9999.00"),
            return_reason=ReturnReason.QUALITY_ISSUE,
            item_condition=None,
            issue_code="AUDIO_LEFT_CHANNEL_SILENT",
            policies=(
                policy(
                    reason="quality_issue",
                    decision="deny",
                    window=30,
                    policy_id="POL-DENY-QUALITY-HIGH",
                ),
            ),
        )
    )

    assert result.status is EligibilityStatus.REQUIRES_APPROVAL
    assert result.risk_reasons == (RiskReason.HIGH_VALUE_ORDER,)
    assert result.matched_rule_ids == ("HIGH_VALUE_THRESHOLD",)
    assert result.applicable_policy_ids == ("POL-DENY-QUALITY-HIGH",)
    assert result.requires_human_approval is True


@pytest.mark.parametrize(
    ("delivered_at", "amount", "decision", "expected_risk", "expected_rule"),
    [
        (
            DEFAULT_DELIVERED_AT,
            "9999.00",
            "unknown_decision",
            RiskReason.HIGH_VALUE_ORDER,
            "HIGH_VALUE_THRESHOLD",
        ),
        (
            datetime.fromisoformat("2026-07-12T12:00:00+00:00"),
            "129.00",
            "allow_after_issue_verification",
            RiskReason.OVERDUE_EXCEPTION,
            "RETURN_WINDOW_EXCEEDED",
        ),
    ],
)
def test_known_high_risk_is_not_overwritten_by_unsafe_decision(
    delivered_at: datetime,
    amount: str,
    decision: str,
    expected_risk: RiskReason,
    expected_rule: str,
) -> None:
    result = engine().evaluate(
        request(
            order=order(delivered_at=delivered_at, total_amount=amount),
            policies=(policy(policy_id="POL-RISK-FIRST", decision=decision),),
        )
    )

    assert result.status is EligibilityStatus.REQUIRES_APPROVAL
    assert result.eligibility is EligibilityConclusion.INDETERMINATE
    assert result.risk_reasons == (expected_risk,)
    assert result.matched_rule_ids == (expected_rule,)
    assert result.applicable_policy_ids == ("POL-RISK-FIRST",)
    assert result.requires_human_approval is True


def test_overdue_and_high_value_risks_have_stable_order() -> None:
    eligibility_engine = engine()
    eligibility_request = request(
        order=order(
            delivered_at=datetime.fromisoformat("2026-07-12T12:00:00+00:00"),
            total_amount="9999.00",
        ),
        policies=(policy(policy_id="POL-DENY-MULTI-RISK", decision="deny"),),
    )

    first = eligibility_engine.evaluate(eligibility_request)
    second = eligibility_engine.evaluate(eligibility_request)

    assert first == second
    assert first.status is EligibilityStatus.REQUIRES_APPROVAL
    assert first.eligibility is EligibilityConclusion.INDETERMINATE
    assert first.risk_reasons == (
        RiskReason.OVERDUE_EXCEPTION,
        RiskReason.HIGH_VALUE_ORDER,
    )
    assert first.matched_rule_ids == (
        "RETURN_WINDOW_EXCEEDED",
        "HIGH_VALUE_THRESHOLD",
    )
    assert first.applicable_policy_ids == ("POL-DENY-MULTI-RISK",)
    assert first.requires_human_approval is True


def test_missing_current_policy_requires_approval_without_guessing() -> None:
    result = engine().evaluate(request(policies=()))

    assert result.status is EligibilityStatus.REQUIRES_APPROVAL
    assert result.eligibility is EligibilityConclusion.INDETERMINATE
    assert result.risk_reasons == (RiskReason.POLICY_EVIDENCE_INSUFFICIENT,)
    assert result.applicable_policy_ids == ()


def test_order_not_delivered_is_ineligible() -> None:
    result = engine().evaluate(request(order=order(status="processing")))

    assert result.status is EligibilityStatus.INELIGIBLE
    assert result.eligibility is EligibilityConclusion.INELIGIBLE
    assert result.requires_human_approval is False


def test_non_resalable_standard_return_is_ineligible() -> None:
    result = engine().evaluate(request(item_condition="non_resalable"))

    assert result.status is EligibilityStatus.INELIGIBLE
    assert result.eligibility is EligibilityConclusion.INELIGIBLE
    assert result.requires_human_approval is False


def test_result_schema_rejects_approval_without_risk_reason() -> None:
    with pytest.raises(ValidationError):
        EligibilityResult(
            rule_version="1.0.0",
            status=EligibilityStatus.REQUIRES_APPROVAL,
            eligibility=EligibilityConclusion.INDETERMINATE,
            applicable_policy_ids=(),
            matched_rule_ids=("TEST",),
            missing_fields=(),
            risk_reasons=(),
            requires_human_approval=True,
            days_since_delivery=None,
            message="Approval required.",
        )
