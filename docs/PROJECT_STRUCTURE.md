# 项目目录规划

## 1. 规划原则

- 采用单仓库、模块化单体；主应用、Mock 业务 API 与 Web 保持清晰进程边界。
- Python 源码使用 `src` 布局，避免测试时误导入仓库根目录代码。
- 领域规则不依赖 FastAPI、LangGraph、数据库或具体模型 SDK。
- 三个 Agent 只保存各自的 Prompt、结构化输出和策略；工作流连接关系统一放在 `orchestration`。
- ResponseValidator 是确定性领域组件，不放入 `agents`。
- 测试按层级组织，并与架构中的单元、组件、Graph、集成、E2E、安全测试对应。
- 目录按任务逐步创建；不提前添加无行为的占位模块。

## 2. 最终目标结构

```text
customer-service-agent/
├── src/
│   ├── customer_service/
│   │   ├── __init__.py
│   │   ├── main.py                       # 主 FastAPI 应用入口
│   │   ├── interfaces/                   # 输入输出边界
│   │   │   ├── api/
│   │   │   │   ├── dependencies.py      # 鉴权、会话和请求依赖
│   │   │   │   ├── errors.py            # HTTP 错误映射
│   │   │   │   ├── router.py             # v1 路由聚合
│   │   │   │   └── routes/
│   │   │   │       ├── health.py
│   │   │   │       ├── conversations.py
│   │   │   │       ├── approvals.py
│   │   │   │       └── evaluations.py
│   │   │   ├── schemas/                  # API DTO，不承载领域规则
│   │   │   │   ├── conversations.py
│   │   │   │   ├── approvals.py
│   │   │   │   └── common.py
│   │   │   └── sse.py                    # 工作流状态事件编码
│   │   ├── application/                  # 用例和事务协调
│   │   │   ├── ports/                    # 应用依赖的抽象接口
│   │   │   │   ├── repositories.py
│   │   │   │   ├── model_gateway.py
│   │   │   │   └── checkpoint_store.py
│   │   │   └── services/
│   │   │       ├── conversation_service.py
│   │   │       ├── approval_service.py
│   │   │       └── evaluation_service.py
│   │   ├── orchestration/                # LangGraph 专属代码
│   │   │   ├── graph.py                  # Graph 构建与编译
│   │   │   ├── state.py                  # 类型化 GraphState
│   │   │   ├── reducers.py
│   │   │   ├── routing.py                # 条件边和终止条件
│   │   │   └── nodes/
│   │   │       ├── supervisor.py
│   │   │       ├── knowledge.py
│   │   │       ├── service.py
│   │   │       ├── clarify.py
│   │   │       ├── approval.py
│   │   │       ├── response.py
│   │   │       └── error.py
│   │   ├── agents/                       # 三类逻辑角色
│   │   │   ├── supervisor/
│   │   │   │   ├── agent.py
│   │   │   │   ├── schemas.py
│   │   │   │   └── prompts.py
│   │   │   ├── knowledge/
│   │   │   │   ├── agent.py
│   │   │   │   ├── schemas.py
│   │   │   │   └── prompts.py
│   │   │   └── service/
│   │   │       ├── agent.py
│   │   │       ├── schemas.py
│   │   │       └── prompts.py
│   │   ├── domain/                       # 无框架依赖的核心业务
│   │   │   ├── models/
│   │   │   │   ├── order.py
│   │   │   │   ├── service_case.py
│   │   │   │   ├── approval.py
│   │   │   │   └── evidence.py
│   │   │   ├── rules/
│   │   │   │   ├── return_eligibility.py
│   │   │   │   └── risk_policy.py
│   │   │   ├── validation/
│   │   │   │   └── response_validator.py
│   │   │   ├── errors.py
│   │   │   └── enums.py
│   │   ├── rag/                          # 知识索引与检索
│   │   │   ├── ingestion/
│   │   │   │   ├── loader.py
│   │   │   │   ├── cleaner.py
│   │   │   │   ├── splitter.py
│   │   │   │   └── indexer.py
│   │   │   ├── retrieval/
│   │   │   │   ├── retriever.py
│   │   │   │   ├── filters.py
│   │   │   │   └── context_builder.py
│   │   │   ├── citations.py
│   │   │   └── schemas.py
│   │   ├── tools/                        # Agent 可调用的受控业务工具
│   │   │   ├── schemas.py                # 统一工具结果信封
│   │   │   ├── order_tool.py
│   │   │   ├── case_tool.py
│   │   │   └── gateway.py
│   │   ├── infrastructure/               # 外部技术实现
│   │   │   ├── config/
│   │   │   │   └── settings.py
│   │   │   ├── database/
│   │   │   │   ├── session.py
│   │   │   │   ├── models.py
│   │   │   │   └── repositories.py
│   │   │   ├── llm/
│   │   │   │   ├── provider.py
│   │   │   │   └── deterministic_fake.py
│   │   │   ├── checkpoints/
│   │   │   │   └── postgres.py
│   │   │   ├── clients/
│   │   │   │   └── mock_business.py
│   │   │   └── observability/
│   │   │       ├── logging.py
│   │   │       └── context.py
│   │   └── evaluation/                   # 评测逻辑，不存大型结果
│   │       ├── runner.py
│   │       ├── metrics/
│   │       │   ├── routing.py
│   │       │   ├── retrieval.py
│   │       │   ├── citations.py
│   │       │   └── workflow.py
│   │       └── report.py
│   └── mock_business/                    # 独立 FastAPI 进程
│       ├── __init__.py
│       ├── main.py
│       ├── schemas.py
│       ├── repository.py
│       └── routes/
│           ├── orders.py
│           └── service_cases.py
├── web/                                  # 最小消费者端与审批工作台
│   ├── src/
│   │   ├── api/
│   │   ├── components/
│   │   ├── features/
│   │   │   ├── chat/
│   │   │   └── approvals/
│   │   ├── pages/
│   │   └── app/
│   ├── package.json
│   └── tsconfig.json
├── tests/
│   ├── unit/
│   │   ├── domain/
│   │   ├── rag/
│   │   └── orchestration/
│   ├── component/
│   │   ├── tools/
│   │   ├── repositories/
│   │   └── model_adapters/
│   ├── graph/
│   ├── integration/
│   ├── e2e/
│   ├── security/
│   ├── fixtures/
│   └── conftest.py
├── data/                                 # 仅合成和可公开数据
│   ├── seed/
│   │   ├── users/
│   │   └── orders/
│   ├── knowledge/
│   │   ├── active/
│   │   ├── expired/
│   │   └── conflicting/
│   └── evaluation/
│       ├── routing/
│       ├── retrieval/
│       ├── rules/
│       ├── graph/
│       └── e2e/
├── migrations/                           # Alembic 迁移
│   ├── versions/
│   └── env.py
├── scripts/                              # 可重复的工程命令
│   ├── init_db.py
│   ├── seed_demo_data.py
│   ├── index_knowledge.py
│   ├── run_evaluation.py
│   └── run_demo.py
├── prompts/                              # 可审阅、版本化 Prompt 内容
│   ├── supervisor/
│   ├── knowledge/
│   └── service/
├── configs/                              # 非敏感、版本化业务配置
│   ├── return_rules.yaml
│   ├── risk_policy.yaml
│   └── models.yaml
├── reports/                              # 版本化评测摘要和示例报告
│   └── evaluations/
├── docs/
│   ├── PROJECT_STRUCTURE.md
│   ├── adr/
│   │   ├── 001-modular-monolith.md
│   │   ├── 002-three-agent-boundaries.md
│   │   ├── 003-langgraph-checkpointing.md
│   │   ├── 004-deterministic-response-validator.md
│   │   └── 005-approval-idempotency.md
│   ├── api/
│   ├── demo/
│   └── superpowers/specs/
├── deploy/
│   ├── docker/
│   │   ├── app.Dockerfile
│   │   ├── mock-business.Dockerfile
│   │   └── web.Dockerfile
│   └── compose.yaml
├── .github/
│   └── workflows/
│       └── ci.yml
├── .env.example
├── .gitignore
├── alembic.ini
├── pyproject.toml
├── uv.lock
├── README.md
├── PROJECT.md
├── REQUIREMENTS.md
├── ARCHITECTURE.md
└── TASKS.md
```

## 3. 关键边界说明

### `agents` 与 `orchestration`

`agents` 只负责单个角色的结构化推理能力；`orchestration` 决定调用顺序、条件分支、循环上限、中断与恢复。Agent 不直接选择任意下一节点。

### `domain` 与 `tools`

`domain` 保存退货资格、风险和回复校验等确定性规则；`tools` 是 Agent 可见的受控门面。工具不得把权限判断交给模型。

### `application` 与 `infrastructure`

`application` 编排会话、审批和评测用例，并依赖抽象端口；`infrastructure` 实现 PostgreSQL、模型供应商、检查点和 HTTP Client。

### `customer_service` 与 `mock_business`

二者位于同一仓库，但使用不同 FastAPI 入口和容器。主应用只能通过 Mock Client/Tool 接口访问模拟订单和售后服务，避免直接跨边界读表。

### `data` 与 `reports`

`data` 保存输入数据集；`reports` 保存评测输出摘要。运行时日志、临时向量文件、缓存和包含敏感配置的结果不得提交。

## 4. 创建策略

T-000 只创建可重复安装、启动和验证最小工程所需的主包、存活检查、前端空壳、配置、测试、质量工具、CI 和 Compose 基础文件。其余目录在对应任务首次产生真实实现时创建：

| 任务 | 新增主要目录 |
| --- | --- |
| T-000 | 最小 `src/customer_service`、存活检查、`infrastructure/config`、前端空壳、最小测试、`.github/workflows`、依赖与锁文件、`deploy/compose.yaml` |
| T-001 | `data/seed`、`data/knowledge` 及数据版本说明 |
| T-002 | `data/evaluation`、`tests/fixtures` 及固定用例定义 |
| T-101 | `rag`、`infrastructure/database`、`migrations`、政策导入与检索测试 |
| T-102 | `tools/order_tool.py`、`infrastructure/clients`、`src/mock_business` 的订单接口及集成测试 |
| T-103 | `domain/rules`、`configs/return_rules.yaml`、`configs/risk_policy.yaml` 及规则测试 |
| T-104 | `tools/case_tool.py`、Mock 售后申请接口、幂等记录及集成测试 |
| T-201 | `agents/supervisor`、`orchestration/routing.py`、相关 Prompt 与 Graph 测试 |
| T-202 | 工作流状态、字段收集与更正节点及测试 |
| T-203 | 标准退货 Graph、`application/services` 与端到端流程测试 |
| T-301 | 审批领域模型、应用服务、API 和审批测试 |
| T-302 | `infrastructure/checkpoints`、恢复逻辑、检查点相关迁移及恢复测试 |
| T-303 | `domain/validation`、回复节点及安全测试 |
| T-304 | 高风险 Graph、审批恢复集成测试和 E2E 测试 |
| T-401 | `web/src/features/chat`、消费者页面及前端测试 |
| T-402 | `web/src/features/approvals`、审批页面及前端测试 |
| T-403 | `evaluation`、`reports/evaluations`、评测脚本和失败案例报告 |
| T-404 | 使用指南、`docs/demo`、ADR、演示脚本和最终 Compose 交付配置 |

目录规划是目标结构，不要求 T-000 批量创建空业务模块。每个目录必须在有实际职责、实现或测试时进入仓库。
