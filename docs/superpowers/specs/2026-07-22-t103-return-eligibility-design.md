# T-103 退货资格规则设计

## 1. 范围

T-103 建立确定性的退货资格与风险判断。它消费已授权订单事实、可信商品事实、当前政策证据和结构化退货信息，输出资格、命中规则、缺失项、风险原因及是否要求人工审批。

本任务不创建售后申请或审批任务，不实现 T-104、Agent、工作流、自然语言抽取、数据库或界面。

## 2. 固定假设

- T-001 数据集版本为 `1.0.0`，固定评估日期为 `2026-07-20`。
- T-103 规则配置版本为 `1.0.0`。
- 普通退货窗口取当前政策中的 7 个自然日，边界包含第 7 天。
- 质量问题窗口取当前政策中的 30 个自然日，并要求质量事实核验。
- CNY 订单总额达到或超过 `5000.00` 时为高金额，必须人工审批；`4999.99` 不命中。
- 日期计算使用评估日期与签收日期的自然日差，不使用测试运行当天时间。
- 金额使用 `Decimal`，不使用二进制浮点数。

## 3. 方案

采用独立 Eligibility Engine、类型化输入输出和版本化 JSON 规则配置。规则配置保存版本、高金额阈值、支持币种及可判断订单状态；引擎代码负责证据绑定、确定性规则顺序和结果不变量。

没有采用纯 Python 常量，因为阈值和规则版本需要独立审计；没有把资格规则加入 Mock Business API，因为这会把订单事实边界和资格决策耦合，并扩大 T-103 范围。

## 4. 输入边界

### 已授权订单事实

复用 T-102 的 `AuthorizedOrderFacts`。资格引擎不会接收用户 ID、所有者字段或未授权原始订单。

### 目标商品事实

新增冻结的 `EligibilityItemFacts`：

- `order_item_id`
- `product_id`
- `category`

引擎必须确认商品行 ID 和商品 ID 同时存在于授权订单中。多商品订单必须明确目标商品行；不允许根据顺序猜测。

### 退货信息

- `return_reason`：`changed_mind` 或 `quality_issue`；可缺失。
- `item_condition`：普通退货必需；当前固定可自动通过值为 `resalable`。
- `issue_code`：质量问题判断必需，用于声明需要核验的质量事实，不代表核验已经完成。
- `as_of`：可显式提供，否则使用规则配置的固定参考日期。

### 政策证据

输入为本次实际使用的 `PolicyDocument` 集合。T-101 的类型补充 T-001 已存在的 `return_window_days` 字段。引擎逐项验证：

- 发布状态和包含性有效期；
- 商品类别；
- 退货原因；
- 唯一适用政策及决策一致性。
- 唯一政策的 `decision`：`changed_mind` 只支持 `allow_if_resalable`，`quality_issue` 只支持 `allow_after_issue_verification`；`deny` 明确不符合资格，未知或原因错配安全升级。

无政策、过期政策、范围不匹配或多政策冲突都不能形成标准确定性通过结论。

## 5. 输出合同

`EligibilityResult` 使用冻结、拒绝额外字段的 Schema，包含：

- `rule_version`
- `status`
- `eligibility`
- `applicable_policy_ids`
- `matched_rule_ids`
- `missing_fields`
- `risk_reasons`
- `requires_human_approval`
- `days_since_delivery`
- `message`

状态：

- `eligible`：完整、低风险、符合标准条件。
- `needs_information`：必要输入不足，不猜测资格。
- `verification_required`：质量政策窗口内，但质量事实尚需核验。
- `requires_approval`：高金额、超期特例或政策冲突/证据风险。
- `ineligible`：事实明确不满足可自动处理条件，例如普通退货商品不可再次销售或订单状态不支持。

Schema 保证：

- `eligible` 不得有缺失项、风险或审批要求；
- `needs_information` 必须包含缺失项且不得给出确定性资格；
- `requires_approval` 必须有风险原因且审批标志为真；
- 非成功结果不得伪装为标准可退；
- 结果中的政策 ID 只能来自本次输入证据。

## 6. 规则顺序

规则以固定顺序执行，避免同一输入因分支顺序变化产生不同结果：

1. 校验规则配置和输入 Schema。
2. 绑定目标商品事实到授权订单。
3. 收集最小必要缺失项；若存在，返回 `needs_information`。
4. 验证订单状态和签收日期。
5. 选择与类别、原因和评估日期匹配的当前政策。
6. 检测政策冲突或证据不足。
7. 计算自然日差，按固定顺序收集超期和高金额风险；存在任一风险即要求人工审批。
8. 解释唯一政策的 decision；拒绝、未知或错配不得进入允许路径。
9. 应用原因对应窗口。
10. 应用商品状态或质量核验规则。
11. 按固定优先级生成唯一结果。

审批风险优先于低风险资格和政策拒绝；高金额或超期事实不因 `deny`、未知或错配 decision 消失。多风险按 `OVERDUE_EXCEPTION`、`HIGH_VALUE_ORDER` 的稳定顺序输出。超期普通退货进入特例审批，不自动创建申请。政策冲突进入审批。缺少用户可补充字段时优先返回缺失信息，不自行创建审批。

## 7. 场景结果

| 场景 | 结果 |
| --- | --- |
| `ORD-NORMAL-001`，普通原因、可再次销售 | `eligible`，低风险，使用 `POL-ACTIVE-STANDARD-001` |
| `ORD-BOUNDARY-001`，第 7 天 | `eligible`，命中包含性边界规则 |
| `ORD-QUALITY-001`，第 18 天、有 issue code | `verification_required`，使用 30 日质量政策 |
| `ORD-OVERDUE-001`，第 8 天 | `requires_approval`，原因 `OVERDUE_EXCEPTION` |
| `ORD-HIGH-VALUE-001`，CNY 9999 | `requires_approval`，原因 `HIGH_VALUE_ORDER` |
| 金额 CNY 5000.00 | 命中高金额审批 |
| 金额 CNY 4999.99 | 不命中高金额规则 |
| 普通退货缺少商品状态 | `needs_information`，缺少 `item_condition` |
| 质量问题缺少 issue code | `needs_information`，缺少 `issue_code` |
| 政策冲突 | `requires_approval`，不生成确定性资格 |

## 8. 测试

单元测试覆盖：

- 规则配置版本、金额阈值和无效配置；
- 结果 Schema 状态组合；
- 普通、7 天边界、质量 30 日、8 天超期、高金额；
- `4999.99/5000.00` 金额边界；
- 缺少原因、商品状态、issue code、签收日期和目标商品；
- 不支持订单状态、不可再次销售、政策缺失/过期/冲突；
- 商品事实与授权订单不绑定；
- 相同输入重复执行结果相等。

组件测试读取 T-002 的 `AC-FR06-N-001`、`AC-FR06-B-001`、`AC-FR06-N-002`、`AC-FR06-E-001` 和 `AC-FR06-E-002`，使用 T-001 固定订单、商品和政策，通过公开 Eligibility Engine 路径验证，不依赖完整自然语言措辞。

## 9. 预计文件

- `config/return-eligibility-rules.v1.json`
- `src/customer_service/eligibility/__init__.py`
- `src/customer_service/eligibility/config.py`
- `src/customer_service/eligibility/schemas.py`
- `src/customer_service/eligibility/engine.py`
- `src/customer_service/rag/schemas.py`（仅补充已有政策窗口字段）
- `tests/unit/eligibility/`
- `tests/component/eligibility/test_t002_eligibility_cases.py`
- `README.md`
- `TASKS.md`
- `docs/CHANGELOG.md`
- `docs/task-reports/T-103.md`

## 10. 风险与非目标

- 规则仅覆盖当前固定类别、原因、币种和单目标商品判断，不是通用退货规则平台。
- 质量问题结果只声明待核验，不实现图片、检测或人工核验。
- `requires_human_approval` 只表达规则要求，不创建审批任务；审批持久化属于 T-301。
- 不创建售后申请；T-104 只能在 T-103 独立通过 Reviewer 后开始。
