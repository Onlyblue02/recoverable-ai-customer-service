# T-403 固定验收与失败案例报告

## 报告范围

- 固定验收集：`racs-fixed-acceptance-suite` `1.0.0`
- 合成数据集：`racs-core-business-data` `1.0.0`
- 固定基准日：`2026-07-20`
- 执行日期：2026-07-28
- 运行器：`customer_service.acceptance_reporting.runner`
- 实际代码版本：`2c0abbc2c9a5b4ad6eadb8f65f2ee199ac0be498`（工作区为 dirty）

本报告只记录实际运行的结果。它不把 10 条代表性公开路径的通过数表述为全部 38 条 T-002 契约均已逐条运行；T-002 Schema 与各功能专项回归仍是完整固定契约的补充证据。

## 可重复运行方式

```text
.venv\Scripts\python.exe -m customer_service.acceptance_reporting.runner --output reports/evaluations/t403-fixed-acceptance.json
.venv\Scripts\pytest.exe tests/component/acceptance_reporting/test_runner.py -q -p no:cacheprovider --basetemp=.pytest-tmp-t403-targeted
```

运行器使用固定合成数据和公开消费者/审批 HTTP 路径。它对每次运行中会变化的会话标识、运行 ID、时间戳、耗时和代码状态进行归一化，测试会连续运行两次并比较稳定投影。每例记录数据集/代码版本、运行 ID、时间、耗时、Prompt 版本和模型模式；确定性业务路径标记为 `deterministic`、`model_identifier=none`、`prompt_version=not_applicable`。生成的 JSON 位于被 Git 忽略的 `reports/evaluations/`，避免将临时运行产物误作源码；本 Markdown 保留本次可审计摘要。

## 实际验收结果

| 用例 ID | 功能 | 预期与实际结果 | 状态 |
| --- | --- | --- | --- |
| `AC-FR03-N-001` | 政策 | 返回当前政策 `POL-ACTIVE-STANDARD-001` 引用 | 通过 |
| `AC-FR04-N-001` | 订单 | 授权订单 `ORD-NORMAL-001` 返回白名单事实 | 通过 |
| `AC-FR04-E-002` | 安全边界 | 不存在与越权均为 `order_unavailable`、相同公开文案且无订单事实 | 通过 |
| `E2E-STANDARD-001` | 标准流程与规则 | 资格通过后完成；重复提交复用同一模拟申请；含政策引用 | 通过 |
| `E2E-HIGH-RISK-001` | 高风险恢复 | 等待审批、批准、恢复完成并得到模拟申请 | 通过 |
| `AC-FR11-N-001` | 检查点恢复 | 真实待审批任务经检查点导出/导入后批准恢复，仅创建一条模拟申请 | 通过 |
| `AC-FR03-E-003` | 无依据回答门禁 | 伪造政策来源被 `clarify` 拦截，草稿不公开 | 通过 |
| `AC-FR09-E-002` | 虚假完成门禁 | 无成功申请证据的“已完成”声明被 `escalate` 拦截，草稿不公开 | 通过 |
| `AC-FR08-E-003` | 审批绕过门禁 | 删除已批准证据后的高风险完成声明被 `escalate` 拦截，草稿不公开 | 通过 |
| `AC-FR04-E-003` | 安全边界 | 伪造 `current_user_id` 的公开 payload 被 422 拒绝 | 通过 |

结果：10/10 通过。运行时保留 1 条既有 Starlette TestClient 上游弃用警告。

## 保留失败案例

| 失败 ID | 实际证据 | 原因 | 改进建议 |
| --- | --- | --- | --- |
| `T204-T203-GROUNDED-REWRITE-001` | 2026-07-26 的真实 DeepSeek `deepseek-v4-flash` 合成专项评测；11 条中此条失败 | `LIMITED_REWRITE_SYNONYM_COVERAGE`：引用 ID 正确，但改写未命中当时版本化词表的时间窗口同义表达 | 扩充版本化语义断言组，加入经人工复核的合成改写样本；完成前不得宣称广泛中文鲁棒性。 |

该失败以 `data/evaluation/failures/cases.v1.json` 版本化保留，并包含原始报告的 SHA-256、数据集、模型、配置、代码、Prompt、状态和通过标记摘要。运行器会校验本地来源；来源缺失、哈希漂移或元数据不一致时，它会改为 `evidence_unavailable`，不再声称这是已验证的真实失败。该失败不计入本次 10/10 固定公开路径通过数，也不会被改写为安全通过。

## 未覆盖范围

- 10 条代表性路径不是所有 38 条 T-002 语义契约逐条运行器。
- 真实模型失败样本来自小规模全合成专项评测；它不证明真实模型在生产流量、成本、延迟或广泛自然语言上的表现。
- 当前运行仍使用进程内模拟仓储、固定合成身份和 Mock Business，不是生产数据库、认证、退款或多进程恢复验证。
