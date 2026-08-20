import json
import re
from collections.abc import Mapping
from typing import Any

from customer_service.model_gateway.fake import FakeModelGateway
from customer_service.model_gateway.schemas import ModelRequest, ModelResponse, ModelTask


class DeterministicAgentGateway:
    """HTTP demo gateway: deterministic plans and grounded drafts, never network access."""

    _ORDER = re.compile(r"\bORD-[A-Z0-9-]+\b", re.IGNORECASE)

    def generate(self, request: ModelRequest) -> ModelResponse:
        payload = (
            self._plan(request.text)
            if request.task is ModelTask.AGENT_PLAN_GENERATION
            else self._draft(request)
        )
        return FakeModelGateway({request.case_id: payload}).generate(request)

    @classmethod
    def _plan(cls, text: str) -> Mapping[str, Any]:
        order = cls._ORDER.search(text)
        if "政策" in text:
            capability = "policy.lookup"
            intent = "policy_question"
            parameters: dict[str, str] = {}
        elif "查询订单" in text or "订单状态" in text:
            capability = "order.get_authorized"
            intent = "order_query"
            parameters = {"order_id": order.group(0).upper()} if order else {}
        else:
            capability = "return.evaluate"
            intent = "return_request"
            parameters = {}
            if order:
                parameters["order_id"] = order.group(0).upper()
            if "质量问题" in text:
                parameters["return_reason"] = "quality_issue"
            elif "不想要" in text:
                parameters["return_reason"] = "changed_mind"
            if "不可再次销售" in text:
                parameters["item_condition"] = "not_resalable"
            elif "未使用" in text:
                parameters["item_condition"] = "resalable"
        missing = [
            name
            for name in ("order_id", "return_reason", "item_condition")
            if capability == "return.evaluate" and name not in parameters
        ]
        return {
            "schema_version": "agent-plan-v1",
            "intent": intent,
            "requested_capability": capability if not missing else "clarify",
            "extracted_parameters": parameters,
            "clarification_fields": missing,
            "uncertainty_reason": "missing_information" if missing else None,
        }

    @staticmethod
    def _draft(request: ModelRequest) -> Mapping[str, Any]:
        evidence = {
            json.loads(item.text)["tool_id"]: (item.evidence_id, json.loads(item.text))
            for item in request.evidence
        }
        claims: list[dict[str, object]] = []
        fragments: list[str] = []
        if "policy.lookup" in evidence:
            evidence_id, _ = evidence["policy.lookup"]
            fragments.append("已找到与本次问题相关的当前政策证据。")
            claims.append({"claim_type": "policy", "evidence_ids": [evidence_id]})
        if "order.get_authorized" in evidence:
            evidence_id, payload = evidence["order.get_authorized"]
            fields = {item["name"]: item["value"] for item in payload["public_fields"]}
            fragments.append(
                f"依据已授权订单查询结果，订单 {fields['order_id']} 当前状态为 delivered。"
            )
            claims.append({"claim_type": "order", "evidence_ids": [evidence_id]})
        if "return.evaluate" in evidence:
            evidence_id, payload = evidence["return.evaluate"]
            fields = {item["name"]: item["value"] for item in payload["public_fields"]}
            messages = {
                "eligible": "该商品符合当前退货资格要求。",
                "ineligible": "该商品不符合当前退货资格要求。",
                "requires_approval": "该退货申请需要人工审批。",
                "needs_information": "当前信息不足以确认退货资格。",
                "verification_required": "当前退货资格需要进一步核验。",
            }
            fragments.append(messages[fields["eligibility_code"]])
            claims.append({"claim_type": "eligibility", "evidence_ids": [evidence_id]})
        approval_tool = next(
            (item for item in ("high_risk.resume", "approval.get_status") if item in evidence),
            None,
        )
        if approval_tool:
            evidence_id, payload = evidence[approval_tool]
            fields = {item["name"]: item["value"] for item in payload["public_fields"]}
            approval_messages = {
                "approved": "人工审批已批准。",
                "rejected": "人工审批已拒绝。",
                "adjusted": "人工审批要求补充或调整信息。",
                "pending": "人工审批仍在等待处理。",
            }
            status = fields.get("approval_status")
            if approval_tool == "high_risk.resume" and "service_case_id" in fields:
                status = "approved"
            if status in approval_messages:
                fragments.append(approval_messages[status])
                claims.append({"claim_type": "approval", "evidence_ids": [evidence_id]})
        completion_tool = next(
            (item for item in ("service_case.create", "high_risk.resume") if item in evidence),
            None,
        )
        if completion_tool:
            evidence_id, payload = evidence[completion_tool]
            case_id = next(
                (
                    item["value"]
                    for item in payload["public_fields"]
                    if item["name"] == "service_case_id"
                ),
                None,
            )
            if case_id:
                fragments.append(f"售后申请已创建，编号为 {case_id}。")
                claims.append({"claim_type": "completion", "evidence_ids": [evidence_id]})
        return {
            "schema_version": "agent-response-draft-v1",
            "text": "".join(fragments),
            "claims": claims,
        }
