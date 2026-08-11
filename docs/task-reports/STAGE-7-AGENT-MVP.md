# 阶段七出口修复｜完整 Agent MVP

## 状态

- 当前结论：2026-08-11 Reviewer 阶段出口审查 `PASS`。
- T-601～T-607 的既有单任务 Reviewer 结论保持不变；本修复只关闭“缺少单一受控 Agent 运行入口”和项目结构文档失真两项出口阻塞。
- 未修改业务规则、权限、资格、审批、Response Gate、Docker/Compose、项目版本或 T-701～T-706。

## 实现

- 新增进程内 `AgentWorkflowService`，内部固定组合 T-602 状态机、T-603 模型计划、T-604 校验及一次性 permit、T-605 受控工具与 EvidenceRecord、T-606 证据草稿和 T-303 Response Gate。
- `AgentWorkflowRequest` 只接受消息；`TrustedAgentContext` 只接受服务端会话、身份和已确认字段。公开 Schema 拒绝 identity、tool step、permit、资格、审批决定、证据、workflow 和 Gate 覆盖字段。
- 低风险资格只允许执行器签发的 continuation 创建一次模拟申请；最终公开回复只来自 Gate。
- 高风险资格只进入既有审批—检查点链路。入口内部保留状态与恢复 permit；审批 pending 时不消费恢复许可、不写申请。服务端读取并严格校验 approval/workflow/checkpoint/conversation/user/version 绑定后，依次通过 T-602 `approval_decided` 与 `resume_requested` 可信事件迁移并留下审计：批准才调用既有 `high_risk.resume`，调整进入澄清，拒绝进入受 Gate 约束的草稿路径，三者均保持既有幂等和零虚假写入边界。
- 入口按可信 conversation/turn/user 键缓存当前进程结果，重复同一 turn 不重复规划、申请或审批升级。
- T-607 固定集新增低风险入口、高风险批准/调整/拒绝入口、提示注入/未知工具、模型伪造证据和公开执行产物注入七项，固定用例总数为 38。

## 安全说明

- 模型仍只能输出受限计划与回复草稿；没有工具对象、permit、身份、资格裁决、审批决定或 Gate 裁决能力。
- 服务没有新建平行业务规则，全部业务结果来自原有订单、政策、资格、申请、审批、恢复和 Gate 服务。
- `AgentWorkflowService` 是进程内组合服务，不是通用 Agent、LangGraph、持久化会话或生产 API。

## 验证

实际执行：

```powershell
.venv\Scripts\python.exe -m customer_service.agent_acceptance.runner --mode fake --output reports/evaluations/stage7-agent-mvp-entry-1.json
.venv\Scripts\python.exe -m customer_service.agent_acceptance.runner --mode fake --output reports/evaluations/stage7-agent-mvp-entry-2.json
.venv\Scripts\pytest.exe -o addopts='' -q tests/component/agent_workflow tests/component/agent_acceptance tests/evaluation/test_agent_mvp_suite.py tests/unit/agent_runtime tests/unit/agent_planning tests/unit/agent_tools tests/unit/agent_response tests/unit/model_gateway tests/unit/response_gate tests/unit/recovery tests/component/orchestration -p no:cacheprovider --basetemp=.pytest-tmp-stage7-entry-targeted
.venv\Scripts\pytest.exe -o addopts='' -q -p no:cacheprovider --basetemp=.pytest-tmp-stage7-entry-full
.venv\Scripts\pytest.exe -o addopts='' -q tests/docs -p no:cacheprovider --basetemp=.pytest-tmp-stage7-entry-docs
.venv\Scripts\ruff.exe format --check .
.venv\Scripts\ruff.exe check .
.venv\Scripts\mypy.exe src tests
git diff --check
```

实际结果：

- 固定集版本 `1.2.0` 连续两次均为 38/38、0 failed，稳定投影一致。
- 单一入口及相关 Agent/审批/恢复/Gate 回归：135 passed。
- 全仓：389 passed、1 skipped；保留 1 条既有 Starlette TestClient 弃用警告。
- 文档：15 passed。
- Ruff format 检查 143 个文件、Ruff check、mypy 142 个源文件和 `git diff --check` 均通过。
- Reviewer 已确认阶段出口 `PASS`；没有创建 Tag、推送或发布。

## Reviewer 结论

- 结论：`PASS`。
- 范围：T-601～T-607 完整 Agent MVP 及阶段七出口的单一受控入口修复。
- 能力边界：DeepSeek 只负责理解、受限结构化计划和可信证据回复草稿；状态机、工具/计划校验、确定性资格规则、人工审批与 Response Gate 保留最终裁决权。
- 限制：当前仍是进程内合成 MVP，不代表生产持久化、跨进程恢复、生产认证、SLA 或 T-701～T-706 已实现。
- 证据：项目所有者在本次 Release Manager 请求中明确确认阶段七出口审查通过。

## T-601～T-607 发布准备汇总

| 任务 | Reviewer | 可核实能力 | 实际验证摘要 | 主要限制 |
| --- | --- | --- | --- | --- |
| T-601 | 2026-08-04 `PASS` | 完整 Agent MVP 产品、安全与架构边界 | 文档测试 15 passed；`git diff --check` 通过 | 仅设计基线，不单独证明实现或生产能力 |
| T-602 | 2026-08-04 `PASS` | 显式状态机、受控执行器、可信审批/恢复事件 | 专项 9 passed；全仓 310 passed、1 skipped；Ruff/mypy 通过 | 状态与审计为进程内实现，不是持久检查点 |
| T-603 | 2026-08-04 `PASS` | DeepSeek/Fake 意图、字段和 `agent-plan-v1` | 专项 25 passed；全仓 317 passed、1 skipped；文档 15 passed；Ruff/mypy 通过 | 模型只产出候选计划，不调用工具或裁决业务 |
| T-604 | 2026-08-05 `PASS` | 静态工具注册、计划/权限校验、EvidenceRecord 合同 | 专项 34 passed；全仓 326 passed、1 skipped；文档 15 passed；Ruff/mypy 通过 | 校验器不替代业务服务；证据 authority 为进程内实现 |
| T-605 | 2026-08-10 `PASS` | 政策、授权订单、资格、申请和人工审批/恢复的受控接入 | 收尾相关回归 173 passed；文档 15 passed；此前全仓 341 passed、1 skipped；Ruff/mypy 通过 | 使用合成数据和进程内仓储，不执行真实退款 |
| T-606 | 2026-08-10 `PASS` | 可信证据 DeepSeek/Fake 草稿与 Response Gate | 收尾相关回归 242 passed；全仓 365 passed、1 skipped；文档 15 passed；Ruff/mypy 通过 | 模型草稿没有最终裁决权；证据快照不跨进程持久化 |
| T-607 | 2026-08-11 `PASS` | 固定 Agent MVP 验收、安全对抗和单一受控入口 | 阶段固定集两次 38/38；专项 135 passed；全仓 389 passed、1 skipped；文档 15 passed；Ruff/mypy 通过 | DeepSeek 补充为 `BLOCKED`；不是生产 Agent API、SLA 或持久化系统 |

各行测试结果来自对应任务报告或阶段出口实测，较早的全仓计数反映当时仓库规模，不能相互替代。所有阶段运行均保留 1 条既有 Starlette TestClient 弃用警告；`skipped` 和 `BLOCKED` 均未计为通过。
