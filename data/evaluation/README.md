# RACS 固定验收用例集

- 用例集版本：`1.0.0`
- 依赖数据集：`racs-core-business-data` `1.0.0`
- 固定基准日：`2026-07-20`
- Schema：`schema/acceptance-suite.schema.json`

用例按 routing、retrieval、rules、graph、experience 和 e2e 分组。每个用例定义前置条件、结构化输入语义、两条可替换示例措辞、有序期望过程和唯一结构化终态。

示例措辞不是精确匹配条件。未来运行器必须依据 `semantic_intent`、`required_entities` 和可观察断言判断结果。

本目录只定义验收契约，没有运行政策检索、订单查询、资格判断、审批、恢复或界面测试。Schema 和一致性检查通过不等于业务能力通过。

验证命令：

```text
uv run pytest tests/evaluation -q
```

## T-403 可重复验收报告

T-403 使用本目录的固定版本和既有公开服务路径生成代表性运行报告，不修改本验收契约。运行命令：

```text
.venv\Scripts\python.exe -m customer_service.acceptance_reporting.runner --output reports/evaluations/t403-fixed-acceptance.json
```

运行产物位于被 Git 忽略的 `reports/evaluations/`；可审计摘要见 `docs/acceptance/T-403-fixed-acceptance-report.md`。`failures/cases.v1.json` 保留真实历史失败及改进建议，不能被通过结果覆盖。

## T-607 Agent MVP 固定验收

`agent_mvp/cases.v1.json` 定义版本化、纯合成的完整 Agent 固定验收和安全对抗矩阵。确定性运行器逐例执行已审查的状态机、计划、工具、证据、模型和 Gate 测试节点：

```text
.venv\Scripts\python.exe -m customer_service.agent_acceptance.runner --mode fake --output reports/evaluations/t607-agent-mvp.json
```

真实 DeepSeek 使用独立非阻塞补充集：

```text
.venv\Scripts\python.exe -m customer_service.agent_acceptance.runner --mode deepseek --output reports/evaluations/t607-deepseek-supplement.json
```

缺少配置、网络失败或限流必须记录为 `skipped` 或 `blocked`，不得计入确定性 Fake 门禁。真实模型结果不构成 SLA；已有真实失败继续保留来源、实际结果和改进建议。

T-607 的回复草稿补充项按 `agent-response-draft-v1` Schema、允许声明类型、本次输入 evidence ID 和禁止业务对象字段匹配；合法输出不要求与动态生成文本逐字相等。逐例报告包含 Prompt、模型、配置、数据集、耗时、网络状态和失败原因，`invalid_output`、`provider_failure`、`unavailable` 与 `skipped` 均不得记为通过。
