# Recoverable AI Customer Service

RACS 是一个可恢复式 AI 售后客服项目。阶段一 `v0.2.0`、阶段二 `v0.3.0`、阶段三 `v0.4.0` 和阶段四 `v0.5.0` 已按 Reviewer 门禁发布；`v0.5.0` 仍是最近正式版本。T-401～T-404、T-601～T-608 与 Docker 发布验证闭环均已通过 Reviewer；当前本地候选版本为 `v1.0.0-rc.2`（`1.0.0rc2`）。该候选未推送，也不是正式 `v1.0.0`。

## 项目版本与发布

项目唯一版本号来源是 `pyproject.toml` 的 `[project].version`，当前候选版本为 PEP 440 格式的 `1.0.0rc2`，对应本地 annotated Tag `v1.0.0-rc.2`。阶段版本规划、发布门禁与一致性检查见 `docs/RELEASES.md`；版本变化见 `docs/CHANGELOG.md`；任务验收证据按 `docs/task-reports/T-xxx.md` 维护。

阶段一产品基线已通过 Reviewer 复审，正式版本为 `v0.2.0`，允许进入 T-101。该版本只证明 T-000～T-002 的工程、合成数据和固定验收合同，不代表 T-101 及后续业务能力已经实现。

## 版本基线

| 组件 | 基线 |
| --- | --- |
| Python | 3.12（`requires-python >=3.12,<3.13`） |
| Node.js | 24.18.0 LTS |
| pnpm | 11.9.0 |
| PostgreSQL | 17 |
| pgvector | 0.8.2 |
| Docker Compose | 2.24.0 或更高 |

Python 依赖的精确版本记录在 `uv.lock`，前端依赖的精确版本记录在 `pnpm-lock.yaml`。当前验证的核心兼容组合为 Pydantic 2.13.4、LangGraph 1.2.9 和 PostgreSQL checkpointer 3.1.0，并由后端锁文件与导入测试共同固定。

## 本地验证

```text
uv sync --frozen --all-groups
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest

pnpm --dir web install --frozen-lockfile
pnpm --dir web format:check
pnpm --dir web lint
pnpm --dir web test
pnpm --dir web build

docker compose -f deploy/compose.yaml config
```

后端开发启动命令：

```text
uv run uvicorn customer_service.main:app --reload
```

存活检查为 `GET /health/live`。完整基础服务可使用 `docker compose -f deploy/compose.yaml up --build` 启动。

## 快速启动与演示

本项目只使用合成数据，不需要真实个人信息或真实订单。最短启动与故障处理见 [启动指南](docs/demo/STARTUP.md)，5–8 分钟的评审演示步骤见 [演示脚本](docs/demo/DEMO_SCRIPT.md)。

项目所有者可在仓库根目录用以下一条命令启动本地合成演示（无需 Docker、无需 DeepSeek API Key）：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_local_demo.ps1
```

脚本会自动检查依赖（`pnpm` 不在 PATH 时尝试 `corepack pnpm`）、设置 OneDrive 兼容的 `UV_LINK_MODE=copy`、选择可用后端端口，并将同一端口配置给 Vite 代理；完成后会输出消费者页面 URL。Windows 用户也可以直接双击 `scripts/启动本地演示.cmd`，它会启动并打开消费者页面；停止时双击 `scripts/停止本地演示.cmd`。PyCharm 用户可在右上角运行配置中选择“启动本地演示”或“停止本地演示”，再点击绿色运行按钮。详细说明见 [启动指南](docs/demo/STARTUP.md)。

手动开发默认使用后端 `http://127.0.0.1:8000` 与前端 `http://127.0.0.1:5173`。`RACS_BACKEND_PORT` 可配置后端端口，`VITE_RACS_BACKEND_PORT` 配置 Vite 代理目标；两者默认均为 `8000`。

固定验收及失败案例的实际结果见 [T-403 验收报告](docs/acceptance/T-403-fixed-acceptance-report.md)。它记录 10 条代表性公开路径与保留的真实模型失败样本；并非把 10 条通过写成全部 38 条固定契约均已逐条运行。

当前消费者页面已经接入进程内受控 Agent HTTP 工作流，默认仍是无需 API Key 的确定性合成演示；它不执行真实退款，也不提供生产认证、持久数据库、跨进程恢复、SSE 或完整生产部署。页面可以显式选择后端已配置的 DeepSeek 模式；最终真实 DeepSeek HTTP 代表评测在同一工作区 digest 下为 4/4 `PASSED`。这只证明受控合成路径可实际调用模型，不等于生产模型能力或 SLA。

## 完整 Agent MVP

T-601～T-607 已通过单任务 Reviewer 审查和阶段七出口审查。当前实现提供进程内 `AgentWorkflowService` 单一受控入口，组合显式状态机、结构化计划、静态工具权限、既有确定性业务工具、可信 EvidenceRecord 和 Response Gate。固定验收集 `1.2.0` 覆盖正常、失败与攻击路径，阶段出口实际结果为连续两次 38/38 且稳定投影一致；完整记录见 [阶段七报告](docs/task-reports/STAGE-7-AGENT-MVP.md) 和 [T-607 固定验收报告](docs/acceptance/T-607-agent-mvp-acceptance-report.md)。

职责边界如下：

- DeepSeek 只负责意图理解、受限结构化计划和基于本轮可信证据的回复草稿；它不能直接调用工具、提供可信身份/permit、裁决资格或审批，也不能决定最终公开回复。
- 显式状态机决定合法迁移与失败终止；静态工具注册表和计划校验器决定允许的工具、参数来源、预算和副作用边界。
- 订单权限与退货资格由确定性业务服务裁决；高风险操作必须经过人工审批与受控恢复；Response Gate 对最终事实、证据和公开文本作最后发送裁决。
- 当前是进程内合成 Agent MVP，不是通用 Agent 平台或生产 API；不提供生产持久化、跨进程恢复、生产认证、SLA 或真实退款执行。T-701～T-706 未实现，仅预留给后续生产化增强。

当前候选版本为 `1.0.0rc2` / `v1.0.0-rc.2`。T-608 已获 Reviewer PASS；Docker 复验已覆盖生产 Web 同源 Agent API 代理、四服务健康、关键连通性、Fake 业务路径、日志与清理。历史 `BLOCKED 3/4` 与 `BLOCKED 0/4` 运行仍作为历史事实保留，最终真实 DeepSeek HTTP 4/4 记录以同一工作区 digest 绑定且不包含 Key、推理链或敏感内部数据。

## 合成数据基线

版本化数据入口为 `data/manifest.json`，数据说明见 `data/README.md`。数据集版本 `1.0.0` 使用固定业务基准日 `2026-07-20`，覆盖正常退货、质量问题、边界日期、超期、高金额、订单不存在、订单越权以及有效、过期、无结果和冲突政策场景。

数据一致性专项验证：

```text
uv run pytest tests/data
```

这些文件只提供合成事实与设计用途，不包含任何业务处理功能。

## 固定验收基线

验收集入口为 `data/evaluation/manifest.json`，Schema 位于 `data/evaluation/schema/acceptance-suite.schema.json`。验收集版本 `1.0.0` 固定引用 T-001 数据集 `1.0.0`，覆盖 FR-01～FR-12 的正常与异常/边界用例，以及标准退货和高风险人工审批与恢复两条端到端故事。

```text
uv run pytest tests/evaluation
```

验收用例是后续功能的可执行数据合同，不代表 T-101 或后续业务能力已经实现。

## 政策知识与引用回答

T-101 使用 T-001 固定政策 JSON 提供类型化、确定性的政策筛选与回答组件。调用方提供商品类别、退货原因和可选查询日期；只有当前有效且无冲突的政策可以形成答案，答案引用包含本次实际使用政策的 ID、版本、标题、来源、有效期和内容摘录。过期、无结果、冲突或多来源含糊时返回结构化安全结果，不生成确定性结论。

```text
uv run pytest tests/unit/rag tests/component/rag
```

## 订单查询与权限边界

T-102 使用 T-001 固定用户与订单 JSON，通过 Mock Business API 在可信业务边界校验订单归属。公开订单 payload 只接收 `order_id`，服务端通过独立权限上下文注入可信 `user_id`；成功结果只返回订单与商品明细白名单字段。不存在与越权在仓库内部保持区分，但公开结果统一为 `ORDER_UNAVAILABLE`，不携带订单详情或暴露订单是否存在。下游异常统一安全降级为 `ORDER_LOOKUP_UNAVAILABLE`。

```text
uv run pytest tests/unit/tools tests/unit/mock_business tests/component/tools
```

T-102 已通过 Reviewer 最终审查并允许进入 T-103；当前实现不包含退货资格、Agent 工作流或界面，且不代表阶段二或 `v0.3.0` 已发布。

T-101 政策知识组件不包含自然语言抽取、HTTP API、数据库/向量索引、Agent 或工作流；这些能力仍属于后续任务。

## 退货资格规则

T-103 使用版本化规则配置和确定性 Eligibility Engine，消费已授权订单事实、目标商品事实、当前政策证据及结构化退货信息。普通退货只有在政策明确为 `allow_if_resalable` 时才进入包含第七天的资格判断；质量问题只有在政策明确为 `allow_after_issue_verification` 时才返回三十日窗口内待核验结果。明确 `deny` 在低风险场景返回不符合资格，未知或原因错配的决策安全升级。普通退货超期、政策冲突和 CNY `5000.00` 及以上高金额订单要求人工审批；已知超期或高金额风险优先于政策 decision，不会被 `deny`、未知或错配结论覆盖；信息不足时只返回缺失项。

```text
uv run pytest tests/unit/eligibility tests/component/eligibility
```

T-103 仅输出资格和审批要求，不创建审批任务。T-104 使用进程内模拟仓库为已授权、低风险且符合资格的请求创建申请；稳定幂等键由可信用户、订单和商品行派生，公开 payload 不能指定工作流或资格结论，重复调用返回首次已确认记录。它不执行真实退款、跨进程恢复、审批或工作流。

## 诉求识别与流程引导

T-201 使用有限、可审计的确定性中文关键词和订单号模式，识别政策咨询、订单查询、退货申请和未知诉求。进行中的退货任务由可信上下文优先延续；未知诉求首次只澄清一次，第二次无效输入安全转人工。该组件不调用订单、政策、资格或申请服务，不产生业务副作用，也不实现 T-202 的字段收集、持久化恢复、Agent、工作流或界面；当前等待 Reviewer 审查。
