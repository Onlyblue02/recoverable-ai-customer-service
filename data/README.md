# RACS 合成数据集

## 数据版本

- 数据集：`racs-core-business-data`
- 版本：`1.0.0`
- 固定业务基准日：`2026-07-20`
- 数据性质：全部为合成数据，不代表真实用户、订单、商品、政策或售后申请

`manifest.json` 是版本、文件清单和关键场景引用的唯一入口。所有日期场景都相对固定业务基准日定义，不依赖测试运行当天的系统日期。

## 数据内容

| 文件 | 内容 |
| --- | --- |
| `seed/users/users.v1.json` | 两名消费者和一名人工客服的演示身份 |
| `seed/products/products.v1.json` | 订单商品及有效、过期、无结果、冲突政策所需类别 |
| `seed/orders/orders.v1.json` | 正常、质量、边界、超期、高金额、越权和已有申请订单 |
| `seed/service_cases/service_cases.v1.json` | 一个与独立订单一致关联的已有模拟售后申请 |
| `knowledge/active/policies.v1.json` | 当前有效普通退货和质量问题政策 |
| `knowledge/expired/policies.v1.json` | 基准日前已失效的政策 |
| `knowledge/conflicting/policies.v1.json` | 同时有效、范围重叠且结论相反的政策 |

每条关键记录包含 `scenario_tags`、`business_purpose` 和 `expected_behavior`。这些字段说明数据为何存在以及后续能力应如何解释该事实，但不定义 T-002 的对话输入、过程断言或端到端终态。

## 固定口径

- 普通无理由退货数据窗口为签收后 7 个自然日。
- `ORD-BOUNDARY-001` 在基准日恰好签收满 7 天。
- `ORD-OVERDUE-001` 在基准日恰好签收满 8 天。
- 质量问题政策数据窗口为签收后 30 个自然日。
- 高金额样本为 CNY 9,999；具体风险阈值由后续规则任务定义。
- `ORD-NOT-FOUND-001` 被保留为不存在订单标识，不得加入订单数据。
- `ORD-OTHER-USER-001` 真实存在但属于 `USR-DEMO-002`，用于 `USR-DEMO-001` 的越权边界。
- `custom_collectible` 类别存在商品但没有任何政策覆盖，用于无结果场景。
- `smart_home` 类别同时被两份结论相反的有效政策覆盖，用于冲突场景。

## 验证

```text
uv run pytest tests/data
```

测试验证版本、文件清单、标识唯一性、实体引用、金额、日期、商品和政策适用范围、关键场景覆盖及合成身份约束。
