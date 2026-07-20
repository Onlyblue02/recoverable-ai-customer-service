# RACS 技术栈

## 1. 选型目标

本技术栈服务于 `PROJECT.md`、`REQUIREMENTS.md`、`TASKS.md` 和 `ARCHITECTURE.md` 定义的第一版本。选型优先级依次为：业务正确性、可恢复性、可测试性、实现简洁度和作品集可读性。

本文给出技术类别和建议版本策略，不将尚未安装或尚未验证的具体版本描述为既成事实。创建工程锁文件时，应选择当时仍受支持的稳定版本并通过自动化测试固定。

## 2. 技术栈总览

| 层级 | 选择 | 用途 |
| --- | --- | --- |
| 前端 | React + TypeScript + Vite | 消费者对话和人工审批界面 |
| 前端包管理 | pnpm | 安装依赖并生成唯一前端锁文件 |
| UI 状态 | TanStack Query + 轻量本地状态 | 服务端状态缓存与最小交互状态 |
| 后端 | Python + FastAPI | 类型化 HTTP API、SSE 和应用入口 |
| 数据校验 | Pydantic | API、模型输出、工具和工作流 Schema |
| ORM / 迁移 | SQLAlchemy + Alembic | 持久化访问和数据库迁移 |
| 工作流 | LangGraph | 显式状态、条件路由、检查点、中断与恢复 |
| 数据库 | PostgreSQL | 业务数据、工作流状态、审批、审计和评测 |
| 向量能力 | pgvector | 首版政策语义检索 |
| 模型接入 | 自定义 ModelGateway + 单一供应商适配器 | 隔离业务代码与具体模型 SDK |
| HTTP Client | HTTPX | 调用 Mock Business API |
| 测试 | pytest + pytest-asyncio + Docker Compose 测试配置 | 单元、异步与真实数据库集成测试 |
| 前端测试 | Vitest + Testing Library + Playwright | 组件和端到端界面测试 |
| 质量工具 | Ruff + mypy | Python 格式、静态检查与类型检查 |
| 前端质量 | ESLint + Prettier + TypeScript strict | 前端静态质量控制 |
| 容器 | Docker + Docker Compose | 一致的本地和演示运行环境 |
| CI | GitHub Actions | 质量检查、测试和构建验证 |
| 日志 | Python 标准 logging + JSON formatter | 结构化日志与关联 ID |

## 3. 运行时与版本策略

### 3.1 Python

- 使用项目创建时仍受支持的稳定 Python 版本，建议以 Python 3.12 为首选基线。
- 在 `pyproject.toml` 中设置明确的最低和最高兼容范围。
- 使用 `uv` 管理虚拟环境、解析依赖和生成锁文件。
- 生产与 CI 必须使用锁文件安装，不使用未约束的浮动依赖。

选择 Python 是因为模型、检索、工作流和数据校验生态完整，同时适合通过类型化边界实现确定性业务层。

### 3.2 Node.js 与 TypeScript

- 使用当前 Active LTS Node.js 主版本，并在 `.nvmrc` 或等价文件中固定。
- 使用 pnpm，并只提交 `pnpm-lock.yaml`，不得混用 npm、Yarn 或多种锁文件。
- TypeScript 开启 `strict`。
- 不引入大型组件库作为架构前提；只在实现界面时选择满足无障碍和最小交互需求的组件方案。

### 3.3 数据库

- 使用仍受 PostgreSQL 社区支持的稳定主版本。
- pgvector 版本必须与 PostgreSQL 镜像兼容，并通过集成测试验证索引与查询行为。
- Schema 变更只能通过 Alembic 迁移，不在应用启动时隐式改表。

### 3.4 工程初始化版本清单

T-000 验收时必须在工程文件中固定并记录以下基线，文档不预先虚构尚未验证的具体版本号：

- Python 精确 minor 版本及 `requires-python` 范围；
- Node.js LTS major 与 pnpm major；
- PostgreSQL major 与 pgvector 镜像标签；
- LangGraph、PostgreSQL checkpointer 和 Pydantic 的兼容组合；
- Docker Compose 最低兼容版本。

版本组合必须通过锁文件安装、后端最小应用启动与存活检查、前端空壳构建、质量命令和 Docker Compose 配置校验后才能作为工程基线。数据库迁移、检查点恢复和核心集成测试分别在产生对应行为的后续任务中验证，不作为 T-000 的前置业务实现。

T-001 以已验收的 T-000 工程基线为前置，只负责合成业务数据与场景基线，不负责重新选择运行时、创建工程骨架或建立 CI。

## 4. 后端技术

### 4.1 FastAPI

承担：

- `/api/v1` 类型化 REST 接口；
- 会话消息的 SSE 状态流；
- 依赖注入、身份上下文和统一错误映射；
- OpenAPI 文档，方便评审者理解和验证接口。

FastAPI 路由只做协议转换和输入校验，不包含资格规则、工作流路由或数据库查询细节。

### 4.2 Pydantic

统一定义：

- API 请求与响应 DTO；
- 模型结构化输出；
- 工具调用参数和结果信封；
- 工作流节点输入输出；
- 评测用例与报告格式。

模型输出校验失败最多进行一次结构修复，之后进入澄清或人工路径。

### 4.3 SQLAlchemy 与 Alembic

- SQLAlchemy 2.x 风格用于仓储实现和显式事务。
- Alembic 管理数据库版本，迁移必须可在空数据库顺序执行。
- 领域对象与 ORM 模型分离，避免业务规则依赖数据库框架。

### 4.4 LangGraph

用于实现持久化状态机，而不是让多个 Agent 自由对话。使用范围包括：

- 类型化 Graph State；
- 白名单条件路由；
- 人工审批中断和恢复；
- 检查点；
- 有限循环与错误分支。

领域规则、权限、幂等和回复门禁仍由普通确定性 Python 组件完成。工作流框架不得成为业务事实来源。

## 5. AI 模型接入

### 5.1 ModelGateway

应用依赖内部协议，不直接依赖具体供应商 SDK：

```text
classify_intent(input) -> IntentResult
extract_slots(input) -> SlotExtractionResult
draft_policy_answer(input, evidence) -> ResponseDraft
```

第一版本只实现一个真实供应商适配器和一个确定性测试替身。不建设多供应商路由、自动降本或模型 A/B 平台。

首版审批摘要由结构化订单事实、政策证据、规则结果和风险原因通过确定性模板生成，不定义独立模型摘要接口。只有模板无法满足已验证展示需求时才增加可选模型润色，且关键字段仍由程序填充和校验。

### 5.2 模型选择原则

- 支持可靠的结构化输出或工具调用约束；
- 支持中文售后语义；
- 可配置温度、超时和最大输出；
- 供应商条款允许所需的演示使用；
- 评测报告记录模型标识与配置。

具体模型名称通过配置提供，不写死在领域或工作流代码中。未经固定评测，不宣称模型达到某项实际准确率。

### 5.3 Prompt 管理

- Prompt 以可审阅文本文件或版本化模块存放。
- 每个 Prompt 有稳定名称和版本。
- Prompt 明确限制输出 Schema、允许证据和禁止事项。
- 不把密钥、真实个人数据或隐藏推理写入 Prompt 日志。

## 6. 知识检索

### 6.1 PostgreSQL + pgvector

首版使用同一 PostgreSQL 实例保存政策元数据、切分片段和向量，减少额外基础设施。在线检索顺序为：

```text
发布状态与有效期过滤
→ 语义相似度检索
→ 最低证据阈值
→ 冲突检测
→ 上下文与引用组装
```

检索结果必须包含文档 ID、版本、标题、来源、有效期、片段 ID 和分数。回答只能引用本次实际传入模型的证据。

### 6.2 Embedding

- 通过独立 EmbeddingGateway 接入，与生成模型解耦。
- 文档与查询必须使用相同模型和向量维度。
- Embedding 模型标识随索引版本保存。
- 更换模型时创建新索引版本，不原地混合向量。

### 6.3 首版不采用

- 独立向量数据库；
- 重排服务；
- 混合检索与 RRF；
- 在线知识上传和自动重建索引。

这些属于增强检索或知识管理扩展，需在 P0 验收后单独启动。

## 7. 前端技术

### 7.1 React + TypeScript + Vite

一个 Web 应用包含两个受角色约束的功能区：

- 消费者：消息、历史、引用、处理状态和可行动错误；
- 人工客服：审批列表、详情、证据、规则、决定和备注。

使用 Vite 保持构建配置简洁。React 组件不承载资格判断或权限规则。

### 7.2 状态与通信

- TanStack Query 管理会话、审批等服务端状态及缓存失效。
- 浏览器进入会话后先使用原生 `EventSource` 连接 `GET /conversations/{conversation_id}/events`，再通过独立 `POST` 提交消息。POST 请求同步推进工作流至终态或持久化等待点，不依赖后台 worker。
- SSE 事件带稳定事件 ID 和递增序号，并支持 `Last-Event-ID` 或等价游标恢复。
- 表单与临时 UI 状态优先使用 React 本地状态；首版不默认引入 Redux。
- 审批提交后依据服务端终态禁用操作，不能只依赖按钮本地禁用防重。

### 7.3 UI 约束

- 不渲染模型隐藏推理或内部错误堆栈。
- 引用必须能关联当前回答。
- 明确区分等待补充、等待人工、完成和失败状态。
- 错误信息说明用户下一步可执行动作。

## 8. Mock Business API

使用独立 FastAPI 进程模拟外部业务边界，提供：

```text
GET  /orders/{order_id}
POST /service-cases
GET  /service-cases/by-idempotency-key/{key}
```

职责包括：

- 在数据源边界校验订单归属；
- 返回合成订单事实；
- 以唯一约束保证模拟申请幂等；
- 支持固定的成功、失败、超时和未知状态测试场景。

主应用通过 HTTPX Client 和受控工具接口调用，不直接读取 Mock 数据库表，以便真实集成时替换适配器。

## 9. 测试技术

### 9.1 后端

- `pytest`：统一测试运行器；
- `pytest-asyncio`：异步接口与工作流测试；
- FastAPI TestClient 或 HTTPX ASGI transport：API 测试；
- Docker Compose 测试配置：使用真实 PostgreSQL/pgvector 和 Mock API 运行集成测试；
- 确定性 ModelGateway：稳定覆盖路由、恢复和失败分支。

### 9.2 前端与 E2E

- Vitest：前端单元测试；
- Testing Library：按用户行为验证组件；
- Playwright：标准退货与人工审批端到端测试，包括刷新和恢复。

P0 只要求关键状态展示和审批交互的少量 Vitest/Testing Library 测试，以及标准退货、高风险审批两条 Playwright 主链路。前端广泛组件覆盖不作为三周交付门槛。

### 9.3 测试数据

合成数据和固定用例以 JSON、YAML 或数据库 seed 保存，并带数据版本。覆盖：

- 当前、过期、无结果和冲突政策；
- 正常、质量问题、边界日期、超期和高金额订单；
- 不存在、越权和缺少订单号；
- 创建成功、失败、超时、重复提交；
- 审批批准、调整、拒绝和重复处理；
- 无依据回答、虚假完成和审批绕过。

## 10. 工程质量与 CI

### 10.1 Python

- Ruff 负责格式化、导入排序和常见静态问题；
- mypy 对领域、应用、工作流状态和端口执行严格类型检查；
- pytest 负责测试与覆盖率报告。

### 10.2 前端

- TypeScript `strict`；
- ESLint 检查代码；
- Prettier 固定格式；
- Vitest 和 Playwright 验证行为。

### 10.3 CI 阶段

```text
依赖锁文件校验
→ 格式与静态检查
→ 单元测试
→ Docker Compose PostgreSQL/Mock API 集成测试
→ 前端构建与组件测试
→ 核心 E2E（主分支或显式工作流）
→ 容器构建
```

真实模型评测不作为每次提交的阻塞 CI；它以显式任务运行并保存版本化报告，避免外部波动造成基础流水线不稳定。

评测通过 CLI 启动并持久化结果。Web/API 只查询已生成的报告，不在 FastAPI 进程中运行不可恢复的长时间评测任务。

## 11. 配置与密钥

- 使用 Pydantic Settings 或等价类型化配置读取环境变量。
- 提交 `.env.example`，不提交真实 `.env` 和供应商密钥。
- 配置区分开发、测试和演示环境，但不建立复杂配置中心。
- 模型、Prompt、规则、政策索引和数据集均保存独立版本标识。
- 日志默认脱敏 Authorization、Cookie、模型密钥和用户标识。

## 12. 可观测性

P0 使用结构化 JSON 日志和关联 ID，不部署完整可观测平台。建议字段包括：

```text
timestamp, level, event, trace_id, conversation_id,
workflow_id, checkpoint_id, component, duration_ms,
model_config_version, prompt_version, rule_version,
tool_name, error_code
```

业务审计使用数据库 `audit_events`，不依赖可能采样或轮转的应用日志。OpenTelemetry、指标面板和成本分析属于后续扩展。

## 13. 容器与本地开发

Docker Compose 包含：

- `web`；
- `racs-api`；
- `postgres`（含 pgvector）；
- `mock-business-api`。

仓库提供可重复命令完成：安装、迁移、写入合成数据、建立政策索引、启动服务、运行测试和生成验收报告。开发环境可单独运行前后端，但 Compose 是演示和验收的标准启动方式。

## 14. 明确不选用的技术

| 技术或方案 | 首版不选原因 |
| --- | --- |
| 微服务 | 单一业务闭环不值得引入分布式事务与运维成本 |
| Kafka / RabbitMQ | 人工等待由持久化状态恢复即可，无事件吞吐需求 |
| Redis | 首版没有必须依赖的缓存、队列或分布式锁场景 |
| Kubernetes | 超出本地作品集演示与首版部署需求 |
| 独立向量数据库 | pgvector 足以支持固定规模政策数据 |
| Redux | 服务端状态和少量本地状态不需要全局状态容器 |
| 多 Agent 自由协作 | 路径不可控，不利于审批、恢复和验收 |
| LLM 质量裁判作为门禁 | 不能可靠证明事实、权限和执行状态 |
| 多模型供应商矩阵 | 属于 P1 版本对比和成本优化范围 |

## 15. 依赖引入规则

新增依赖必须满足至少一项：

- 直接承载 P0 需求；
- 显著降低安全、恢复、测试或维护风险；
- 替代更复杂的自研实现。

同时必须记录用途、许可证、维护状态和替代方案；没有实际调用的“预留依赖”不得加入锁文件。所有具体版本以工程初始化时生成并经 CI 验证的锁文件为准。
