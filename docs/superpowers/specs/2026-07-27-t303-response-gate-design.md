# T-303 最终回复质量门禁

T-303 新增独立、确定性的 `ResponseGateService`。它接收不可信 `ResponseDraft` 与服务端注入的 `ResponseEvidenceContext`；两者严格分离，草稿中的政策引用、订单、资格、申请和审批摘要不会自动成为事实。

草稿对政策结论、订单事实、资格结论和完成声明显式建模。门禁逐项验证：政策引用的 policy/evidence/version/source 来自本次可信证据；订单和资格与已授权结果完全一致；“已创建/已完成”有状态为 `created` 的绑定申请；高风险资格有终态 `approved/approve` 审批，且草稿审批摘要等于可信审批。

验证失败不会修改订单、资格、审批或申请等业务事实。普通证据不足返回 `CLARIFY`，缺少或伪造高风险审批返回 `ESCALATE`，敏感内部文本仅安全改写为无事实的通用提示。该模块不创建申请、不恢复工作流、不接入 API/UI/Agent，也不实现 T-304 编排。
