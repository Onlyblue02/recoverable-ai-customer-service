from customer_service.approvals.schemas import ApprovalDecision, ApprovalStatus, ApprovalTaskSummary
from customer_service.service_cases.repository import (
    ServiceCaseDraft,
    ServiceCaseRepository,
    StoredServiceCase,
)
from customer_service.service_cases.schemas import (
    ServiceCaseAccessContext,
    ServiceCaseCreateRequest,
    ServiceCaseEligibilityContext,
    ServiceCaseErrorCode,
    ServiceCaseResult,
    ServiceCaseStatus,
    ServiceCaseSummary,
    eligibility_is_creatable,
)


class ServiceCaseService:
    def __init__(self, repository: ServiceCaseRepository) -> None:
        self._repository = repository

    def create(
        self,
        request: ServiceCaseCreateRequest,
        *,
        access_context: ServiceCaseAccessContext,
        eligibility_context: ServiceCaseEligibilityContext,
    ) -> ServiceCaseResult:
        if not any(
            self._same_identifier(item.order_item_id, request.order_item_id)
            for item in request.order.items
        ):
            return self._blocked(
                ServiceCaseErrorCode.ORDER_ITEM_NOT_AUTHORIZED,
                "目标商品不属于当前已授权订单，未创建模拟售后申请。",
            )
        if not self._eligibility_binds_to_request(
            eligibility_context=eligibility_context, request=request
        ):
            return self._blocked(
                ServiceCaseErrorCode.ELIGIBILITY_CONTEXT_MISMATCH,
                "当前资格依据无法用于该订单商品，未创建模拟售后申请。",
            )
        if not eligibility_is_creatable(eligibility_context.eligibility):
            return self._blocked(
                ServiceCaseErrorCode.ELIGIBILITY_NOT_CREATABLE,
                "当前资格结果不能直接创建模拟售后申请。",
            )

        key = self._idempotency_key(request, access_context=access_context)
        try:
            existing = self._repository.find_by_idempotency_key(key)
            if existing is not None:
                return self._existing(
                    existing,
                    request=request,
                    access_context=access_context,
                    idempotency_key=key,
                )
            created = self._repository.create(
                draft=ServiceCaseDraft(
                    user_id=access_context.current_user_id,
                    order_id=request.order.order_id,
                    order_item_id=request.order_item_id,
                    idempotency_key=key,
                )
            )
            if not self._confirmed_case_binds_to_request(
                created,
                request=request,
                access_context=access_context,
                idempotency_key=key,
            ):
                return self._safe_failure()
            assert created is not None
            return ServiceCaseResult(
                status=ServiceCaseStatus.CREATED,
                error_code=None,
                message="模拟售后申请已创建。",
                service_case=self._summary(created),
            )
        except Exception:
            return self._safe_failure()

    def create_after_approval(
        self, approval: ApprovalTaskSummary, *, access_context: ServiceCaseAccessContext
    ) -> ServiceCaseResult:
        """Controlled T-302 continuation; approval facts are server-read by recovery."""
        if (
            approval.status is not ApprovalStatus.APPROVED
            or approval.decision is not ApprovalDecision.APPROVE
            or approval.user_id != access_context.current_user_id
        ):
            return self._safe_failure()
        request = ServiceCaseCreateRequest(
            order=approval.order, order_item_id=approval.order_item_id
        )
        eligibility_context = ServiceCaseEligibilityContext(eligibility=approval.eligibility)
        if not self._eligibility_binds_to_request(
            eligibility_context=eligibility_context, request=request
        ):
            return self._safe_failure()
        return self._create_verified(request, access_context=access_context, allow_approved=True)

    def _create_verified(
        self,
        request: ServiceCaseCreateRequest,
        *,
        access_context: ServiceCaseAccessContext,
        allow_approved: bool = False,
    ) -> ServiceCaseResult:
        key = self._idempotency_key(request, access_context=access_context)
        try:
            existing = self._repository.find_by_idempotency_key(key)
            if existing is not None:
                return self._existing(
                    existing, request=request, access_context=access_context, idempotency_key=key
                )
            created = self._repository.create(
                draft=ServiceCaseDraft(
                    user_id=access_context.current_user_id,
                    order_id=request.order.order_id,
                    order_item_id=request.order_item_id,
                    idempotency_key=key,
                )
            )
            if not self._confirmed_case_binds_to_request(
                created, request=request, access_context=access_context, idempotency_key=key
            ):
                return self._safe_failure()
            assert created is not None
            return ServiceCaseResult(
                status=ServiceCaseStatus.CREATED,
                error_code=None,
                message="模拟售后申请已创建。",
                service_case=self._summary(created),
            )
        except Exception:
            return self._safe_failure()

    @staticmethod
    def _idempotency_key(
        request: ServiceCaseCreateRequest, *, access_context: ServiceCaseAccessContext
    ) -> str:
        return "|".join(
            (
                access_context.current_user_id.strip().upper(),
                request.order.order_id.strip().upper(),
                request.order_item_id.strip().upper(),
            )
        )

    @staticmethod
    def _summary(case: StoredServiceCase) -> ServiceCaseSummary:
        return ServiceCaseSummary(
            service_case_id=case.service_case_id,
            status=case.status,
            order_id=case.order_id,
            order_item_id=case.order_item_id,
        )

    def _existing(
        self,
        case: StoredServiceCase,
        *,
        request: ServiceCaseCreateRequest,
        access_context: ServiceCaseAccessContext,
        idempotency_key: str,
    ) -> ServiceCaseResult:
        if not self._confirmed_case_binds_to_request(
            case,
            request=request,
            access_context=access_context,
            idempotency_key=idempotency_key,
        ):
            return self._safe_failure()
        return ServiceCaseResult(
            status=ServiceCaseStatus.EXISTING,
            error_code=None,
            message="已返回已有模拟售后申请。",
            service_case=self._summary(case),
        )

    @staticmethod
    def _blocked(error_code: ServiceCaseErrorCode, message: str) -> ServiceCaseResult:
        return ServiceCaseResult(
            status=ServiceCaseStatus.BLOCKED,
            error_code=error_code,
            message=message,
            service_case=None,
        )

    @staticmethod
    def _eligibility_binds_to_request(
        *,
        eligibility_context: ServiceCaseEligibilityContext,
        request: ServiceCaseCreateRequest,
    ) -> bool:
        binding = eligibility_context.eligibility.input_binding
        if binding is None or binding.rule_version != eligibility_context.eligibility.rule_version:
            return False
        target_item = next(
            (
                item
                for item in request.order.items
                if ServiceCaseService._same_identifier(item.order_item_id, request.order_item_id)
            ),
            None,
        )
        return target_item is not None and (
            ServiceCaseService._same_identifier(binding.order_id, request.order.order_id)
            and ServiceCaseService._same_identifier(binding.order_item_id, request.order_item_id)
            and binding.product_id == target_item.product_id
        )

    @staticmethod
    def _confirmed_case_binds_to_request(
        case: StoredServiceCase | None,
        *,
        request: ServiceCaseCreateRequest,
        access_context: ServiceCaseAccessContext,
        idempotency_key: str,
    ) -> bool:
        return case is not None and (
            case.status == "created"
            and case.user_id == access_context.current_user_id
            and ServiceCaseService._same_identifier(case.order_id, request.order.order_id)
            and ServiceCaseService._same_identifier(case.order_item_id, request.order_item_id)
            and case.idempotency_key == idempotency_key
        )

    @staticmethod
    def _safe_failure() -> ServiceCaseResult:
        return ServiceCaseResult(
            status=ServiceCaseStatus.FAILED_SAFE,
            error_code=ServiceCaseErrorCode.SERVICE_CASE_WRITE_FAILED,
            message="模拟售后申请未创建成功，请稍后重试。",
            service_case=None,
        )

    @staticmethod
    def _same_identifier(left: str, right: str) -> bool:
        return left.strip().upper() == right.strip().upper()
