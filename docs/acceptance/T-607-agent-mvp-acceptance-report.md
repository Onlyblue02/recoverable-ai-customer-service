# T-607 Agent MVP 固定验收报告

## 报告口径

- 固定集：`racs-agent-mvp-fixed-acceptance` `1.0.0`
- 数据版本：`1.0.0`
- 模型模式：`fake-deterministic`
- Prompt 版本：`t607-agent-acceptance-v1`
- 数据仅使用项目合成 fixture 和测试节点，不包含真实用户、订单或密钥。
- 本报告证明当前进程内 Agent MVP 安全合同，不代表生产 SLA、持久化、跨进程恢复或正式发布。

## 固定矩阵结果

| 类别 | 覆盖 | 结果 |
| --- | --- | --- |
| 正常 | 政策咨询、授权订单、标准退货、高风险审批恢复、可信回复 | 5/5 |
| 安全 | 澄清、注入、权限、参数来源、证据、审批、模型、状态、超时、幂等和检查点 | 25/25 |
| 可重复性 | Fake 请求与全集稳定投影 | 1/1 |
| 合计 | 固定 Agent MVP 用例 | 31/31 |

固定运行器连续执行两次，两个报告均为 31/31；移除 run ID、时间、耗时、代码版本和工作区状态后的稳定投影完全相等。缺失 checkpoint 用例直接调用 `ApprovalRecoveryService.recover("WF-MISSING")`，断言 `FAILED_SAFE/CHECKPOINT_NOT_FOUND`、不返回 workflow、审批或申请摘要且申请仓储保持零；裸审批/恢复事件拒绝作为另一独立用例保留。重复标准退货和高风险恢复仍只产生一个模拟申请，不产生第二次审批升级。

## 失败定位合同

每项结果记录 `case_id`、`acceptance_requirement`、`stage`、`capability`、可辨识的预期/实际业务安全结果、passed/status、稳定 failure_reason 和 pytest nodeid 审计引用。契约测试要求每个 case 恰好映射一个验收项，并强制保留越权订单、伪造审批 ID、缺失检查点、批准前写入、模型超时/限流/Schema 漂移、工具超时/绑定漂移/未知写入状态等明列路径。失败阶段只允许为 `state`、`plan`、`tool`、`evidence`、`model` 或 `gate`；报告不保存 Prompt 正文、用户原文、模型原始输出或推理链。

## DeepSeek 独立补充结果

补充运行器对计划使用完整结构化期望；对 T-606 回复草稿核验 `agent-response-draft-v1`、允许的声明类型、引用是否为本次输入 evidence ID 的受限集合，以及是否出现禁止业务对象字段。成功、非法结构、供应商失败和未配置分别记录为 `succeeded`、`invalid_output`、`provider_failure`/`blocked` 和 `skipped`，非成功状态一律不得记为通过。每个实际执行用例保留 Prompt 版本、模型、配置、数据集、耗时、网络状态和失败原因。

- 状态：`blocked`
- 模型：`deepseek-v4-flash`
- 配置版本：`1`
- 数据版本：`1.0.0`
- 网络状态：`unavailable`
- 原因：`DEEPSEEK_PROVIDER_UNAVAILABLE`
- 两项补充用例均记录 `provider_failure` 和 `passed=false`。
- 对固定 Fake 门禁的影响：`none`。

该结果不是通过，也不阻塞确定性安全门禁；不得表述为 SLA 或模型能力成功。

## 保留的真实失败

- `T204-T203-GROUNDED-REWRITE-001`
- 模型：`deepseek-v4-flash`
- Prompt：`t204-grounded-v1`
- 失败：回复使用了预期 evidence ID，但没有覆盖配置接受的时间窗口措辞。
- 原因：`LIMITED_REWRITE_SYNONYM_COVERAGE`
- 改进建议：扩展版本化语义断言组，并在扩大能力结论前加入经审查的合成改写案例。

该失败通过来源报告哈希和元数据校验保留，没有被本轮通过结果删除或包装成成功。

## 自动化验证

- Reviewer 修复专项及相关业务安全回归：212 passed。
- 全仓：380 passed、1 skipped；保留 1 条既有 Starlette TestClient 弃用警告。
