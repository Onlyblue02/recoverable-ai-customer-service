# RACS 项目结构

## 1. 阅读口径

本文件区分当前仓库中已经存在的目录与未来目标结构。当前目录树只列已落地的主要模块；未来规划不表示已创建、更不表示已有数据库、SSE、LangGraph 或 Agent 能力。

## 2. 当前实际目录与能力

```text
src/
  customer_service/
    acceptance_reporting/  固定验收运行器
    agent_acceptance/      Agent MVP 固定验收与安全对抗运行器
    agent_planning/        受限模型计划协议与确定性路由
    agent_response/        可信证据草稿解析与 Response Gate 编排
    agent_runtime/         有界 Agent 状态机与审计状态
    agent_tools/           静态工具合同、许可、受控执行与证据
    agent_workflow/        串联 T-602～T-606 的单一受控进程内入口
    approvals/             进程内审批任务与服务
    collection/            多轮信息收集与更正
    eligibility/           确定性资格规则
    infrastructure/        当前 HTTP 客户端与配置
    interfaces/api/        最小 FastAPI 会话、审批和健康检查路由
    model_gateway/         DeepSeek/Fake 适配和独立评测
    orchestration/         标准与高风险的受控进程内编排
    rag/                   固定政策筛选、引用绑定
    recovery/              进程内检查点与恢复保护
    response_gate/         跨领域最终回复门禁
    routing/               确定性诉求路由
    service_cases/         模拟申请与稳定重复保护
    tools/                 订单授权查询边界
  mock_business/           合成订单与模拟申请 Mock API
data/                      版本化合成数据与固定验收用例
docs/
  acceptance/              固定验收报告
  demo/                    本地启动和演示脚本
  task-reports/            任务证据与发布限制
tests/                     数据、单元、组件、接口和文档回归
web/                       消费者与审批 React/Vite 页面
deploy/compose.yaml        未在当前环境完成验证的 Compose 配置
```

当前已有受控 Agent MVP 目录及单一 `AgentWorkflowService` 组合入口，但运行状态仍是进程内合成演示：它只串联受限计划、静态校验、既有确定性业务工具、可信证据和 Response Gate，不是通用 Agent 平台，不使用 LangGraph，也没有 PostgreSQL 数据库、数据库迁移、SSE/EventSource、持久会话历史、跨进程恢复或生产认证。`reports/evaluations/` 是被 Git 忽略的运行产物，不能被当作已持久化服务数据或提交证据。

## 3. 目录边界

- `customer_service` 与 `mock_business` 为同一仓库内的两个 FastAPI 入口；主应用通过客户端/服务边界使用 Mock API，不直接读外部业务表。
- `data` 只保存固定合成输入与验收合同，不含真实个人信息。
- `tests` 覆盖当前确定性组件与公开接口；真实模型只在独立的 T-204 评测中使用。
- `web` 只实现消费者与人工审批页面，不包含 SSE 客户端、运营后台或生产登录。

## 4. 未来目标结构（未实现）

以下目录和能力是可能的后续演进方向，当前不存在或未接入运行路径：

```text
application/               用例层与事务边界
domain/                    独立领域模型与策略层
agents/                    未来通用 Agent 或完整 LangGraph 节点（当前未实现）
infrastructure/database/   PostgreSQL 持久化实现
migrations/                数据库迁移
interfaces/sse.py          SSE 与事件重放接口
```

这些未来目标不能替代当前目录说明，也不能作为 T-404、阶段五或 `v1.0.0` 的已实现证据。

## 5. 任务映射

`TASKS.md` 是任务状态和验收证据的唯一任务清单。当前已实现目录按其职责对应 T-101～T-404；任何未来目录必须在新的、明确授权的任务首次产生真实实现时创建，而不是预先批量创建空模块。
