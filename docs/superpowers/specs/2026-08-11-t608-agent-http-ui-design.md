# T-608 Agent HTTP API 与消费者页面接入设计

## 1. 文档状态

本文是 T-608 的最小设计补充。2026-08-11 Reviewer 首轮结论为 `CONDITIONAL PASS`；针对 HTTP 幂等关联、确定性 confirmed 字段来源、应用级唯一依赖图以及写后失败公开投影完成最小修复后，独立复审结论为 **`PASS`（仅限设计）**，允许开始 T-608 实现。本文不表示 HTTP Agent 模式、消费者模式选择或真实 DeepSeek 页面链路已经实现，也不构成 `v1.0.0-rc.2`、正式版本、提交或 Tag 的授权。

T-601～T-607 与阶段七已 PASS；现有进程内 `AgentWorkflowService` 是受控 Agent 内核的唯一组合入口。当前消费者 API 与页面仍调用确定性合成会话服务，不调用模型。T-608 只负责把已完成内核接入现有 HTTP API 和消费者页面，不修改 Agent 的状态机、计划协议、工具权限、业务规则、审批或 Response Gate 裁决边界。

## 2. 用户目标

- 默认继续使用无需 API Key、行为可重复的 Fake/合成 Agent 演示。
- 后端配置 DeepSeek API Key 后，用户能在消费者页面明确选择 DeepSeek Agent，并通过真实 HTTP 会话使用它。
- 用户始终知道当前会话使用 Fake 还是真实 DeepSeek，以及模型失败时实际发生了什么。
- 模型不可用时获得安全、可行动的状态，不把 Fake 输出或确定性模板伪装成 DeepSeek 成功回答。

## 3. 最小范围

### 3.1 包含

- 为消费者会话增加 `fake` 与 `deepseek` 两种显式模式。
- 新增安全的模式能力查询，并在创建会话时固定模式。
- 将消费者消息从 HTTP API 路由到对应 ModelGateway 的 `AgentWorkflowService.handle()`。
- 将可信人工审批终态经服务端上下文路由到 `AgentWorkflowService.resume()`。
- 将内部 `AgentWorkflowResult` 投影为最小公开会话 DTO。
- 消费者页面增加模式选择、模式标识、模型状态和安全失败提示。
- 增加 Fake 全回归、供应商失败模拟、HTTP/前端集成与真实 DeepSeek 受控评测。

### 3.2 不包含

- 不实现 T-701～T-706。
- 不增加生产认证、持久数据库、跨进程恢复、SSE、后台任务、限流平台或 SLA。
- 不允许浏览器输入、保存或传输 DeepSeek API Key。
- 不允许用户在同一会话中切换模式；切换必须显式创建新会话。
- 不允许自动把失败的 DeepSeek 会话静默切换为 Fake 并伪装成模型成功。
- 不修改模型计划 Schema、状态机、工具注册表、permit、EvidenceRecord、资格规则、审批决策、幂等语义或 Response Gate。
- 不修改版本号、候选发布记录、Docker 配置或依赖版本。

## 4. 模式模型

### 4.1 模式定义

| 模式 | 含义 | 可用条件 | 失败行为 |
| --- | --- | --- | --- |
| `fake` | 确定性 Fake ModelGateway + 现有合成业务工具 | 始终可用，默认模式 | 按现有 Agent 安全合同返回；用于稳定演示和回归 |
| `deepseek` | DeepSeekModelGateway + 同一 AgentWorkflowService 和合成业务工具 | 后端存在有效格式的配置；不向客户端暴露 Key | 模型故障进入明确 `failed_safe`；不自动冒充 Fake 成功 |

模式只决定 ModelGateway 实现，不改变任何工具、可信上下文、规则、审批、证据或 Gate。服务端为每个会话保存不可变 `requested_mode`；`effective_mode` 在 T-608 中必须等于已接受的会话模式，不定义静默 fallback 模式。

### 4.2 模式选择规则

- `POST /api/v1/conversations` 未提供 mode 时使用 `fake`，保持现有客户端兼容。
- 创建 `deepseek` 会话前，后端只检查配置是否存在且可加载，不在能力查询中发送探测模型请求。
- 未配置 Key 时创建 DeepSeek 会话返回安全的 `409 AGENT_MODE_NOT_CONFIGURED`，不创建会话、不调用模型。
- 会话创建后模式不可变。用户选择其他模式时，前端必须确认并创建新会话；旧会话历史保持原模式标签。
- 前端默认选中 Fake，并以“合成演示”明确标识；DeepSeek 仅在服务端报告 `configured=true` 时允许选择。

## 5. 调用链

### 5.1 模式发现与会话创建

```text
消费者页面
→ GET /api/v1/agent-modes
→ 展示 Fake（默认）与 DeepSeek（仅显示已配置/未配置）
→ POST /api/v1/conversations {mode}
→ 服务端创建会话、固定模式、可信 user_id 和 turn 计数
→ 返回不含密钥的 ConversationResponse
```

### 5.2 消息处理

```text
POST /api/v1/conversations/{conversation_id}/messages {message}
→ Conversation API 根据 conversation_id 读取服务端会话与固定模式
→ AgentConversationService 生成服务端 turn_id 与 TrustedAgentContext
→ AgentWorkflowFactory 按固定模式选择 Fake 或 DeepSeek ModelGateway
→ AgentWorkflowService.handle(AgentWorkflowRequest, TrustedAgentContext)
→ 状态机 → 计划校验 → 一次性 permit → 白名单工具 → EvidenceRecord
→ DeepSeek/Fake 证据草稿 → Response Gate
→ PublicConversationProjector 只投影允许公开的状态、回复和政策引用
→ 消费者页面显示模式、处理结果和下一步
```

HTTP 层不能构造工具步骤、permit、EvidenceRecord、资格、审批终态、workflow_id 或 Gate 结果。`AgentWorkflowService` 继续拥有从计划到 Gate 的完整受控链路。

### 5.3 高风险审批与恢复

```text
AgentWorkflowService.handle() 返回 WAITING_APPROVAL
→ 会话 API 保存服务端 pending 映射与公开等待状态
→ 人工审批 API 使用既有可信 actor context 提交决定
→ 服务端按 conversation_id/turn_id/user_id 查找绑定 Agent 会话
→ AgentWorkflowService.resume(TrustedAgentContext)
→ high_risk.resume 执行批准/调整/拒绝闭环
→ Response Gate 裁决公开回复
→ 消费者 GET 会话只读取更新后的公开快照
```

消费者 GET 不触发恢复或业务写入。浏览器不能提交 approval_id、workflow_id、恢复 permit 或审批决定。批准前零申请写入；重复审批通知或重复读取只复用同一终态。

## 6. HTTP 接口合同

### 6.1 查询模式

```http
GET /api/v1/agent-modes
```

公开响应：

```json
{
  "default_mode": "fake",
  "modes": [
    {"id": "fake", "configured": true, "selectable": true},
    {
      "id": "deepseek",
      "configured": false,
      "selectable": false,
      "reason_code": "AGENT_MODE_NOT_CONFIGURED"
    }
  ]
}
```

响应不得包含 API Key 是否为空之外的细节、Key 前后缀、Base URL、模型内部配置、Prompt、供应商响应或异常文本。`configured=true` 只表示后端配置存在，不承诺供应商当前可用。

### 6.2 创建会话

```http
POST /api/v1/conversations
Content-Type: application/json

{"mode": "fake"}
```

请求 Schema：

- `mode`: 可选，枚举 `fake | deepseek`；省略时为 `fake`。
- `extra=forbid`；拒绝 `api_key`、`model`、`base_url`、`user_id`、`permit`、`tools`、`evidence` 等所有额外字段。

DeepSeek 未配置时：

```json
{
  "detail": {
    "code": "AGENT_MODE_NOT_CONFIGURED",
    "message": "DeepSeek Agent 当前未配置，请使用合成演示模式。"
  }
}
```

HTTP 状态为 409。错误响应不回显请求体或配置细节。

### 6.3 发送消息

```http
POST /api/v1/conversations/{conversation_id}/messages
Content-Type: application/json

{"message": "我想退货"}
```

请求 body 仍只接受 `message`。mode、身份和执行数据全部从服务端会话读取；请求不得覆盖会话模式。每个会改变回合状态的 POST 必须同时携带版本化白名单请求头 `Idempotency-Key`；该请求头是 HTTP 重放关联标识，不进入模型 Prompt、工具参数或公开响应。

#### 6.3.1 HTTP 幂等合同 `http-idempotency-v1`

- 生成者：消费者页面在首次发送消息时使用密码学安全随机 UUID v4 生成；浏览器仅为同一次未确认 HTTP 操作保留并复用该值，用户明确发送一条新消息必须生成新值。服务端不接受 body 内的 `request_id`。
- 格式：ASCII UUID v4，规范小写形式，最大 36 字符；缺失、格式错误或超长返回 `400 IDEMPOTENCY_KEY_INVALID`，且不创建 turn、不调用模型或工具。
- 绑定：服务端记录 key 与服务端可信 `user_id`、`conversation_id`、固定 mode、HTTP method/path、规范化 message digest、所签发 `turn_id` 的绑定；任何绑定不一致返回 `409 IDEMPOTENCY_KEY_CONFLICT`，不泄露原绑定内容。
- 状态：`PROCESSING | COMPLETED | FAILED_SAFE`。首次接受时原子占位并只签发一次 `turn_id`；处理中重放返回 `409 IDEMPOTENCY_REQUEST_IN_PROGRESS` 和安全的 `can_retry=true`，不得启动第二次模型或工具执行；完成或安全失败后的同绑定重放返回已保存的同一公开 HTTP 投影，不重新执行模型、计划或工具。
- 写后失败：若业务写入已经发生而模型草稿、Response Gate 投影或网络发送失败，幂等记录必须保存可信业务终态和 `FAILED_SAFE` 公开快照；重放只能读取该快照或后续可信查询结果，绝不重放写操作。
- pending 审批：首次响应为 `waiting_approval` 后，同 key 重放只返回同一公开 pending 快照；不创建第二个审批、检查点或 turn。审批决定使用审批端既有幂等合同，不复用消费者消息 key。
- 生命周期：T-608 仅承诺与进程内会话相同的生命周期，默认 TTL 为 24 小时且不得短于会话生命周期；到期或进程重启后无法证明重放安全时返回 `409 IDEMPOTENCY_STATE_UNAVAILABLE`，不得猜测执行或创建新 turn。本限制必须在公开演示说明中披露，持久化不在 T-608 范围。
- 保密：公开 DTO、日志和浏览器错误文案不得包含 permit、workflow/checkpoint/evidence 标识；服务端日志中的幂等 key 必须摘要化。

### 6.4 公开会话响应

在现有公开字段基础上增加：

```text
requested_mode: fake | deepseek
effective_mode: fake | deepseek
agent_status: completed | clarify | waiting_approval | escalate | failed_safe
model_status: not_used | succeeded | not_configured | unavailable |
              timeout | rate_limited | invalid_output
reason_code: 公开稳定原因码
can_retry: boolean
can_start_fake_conversation: boolean
```

公开响应允许：

- Response Gate 放行或安全改写后的 `message`；
- 用户可行动的 `action_hint`；
- 已审核的政策引用公开字段；
- 已确认的公开申请/审批状态；
- 模式及安全模型状态。

公开响应禁止：

- API Key、Authorization header、Base URL 或完整模型配置；
- 模型隐藏推理、system prompt、原始请求/响应；
- execution permit、continuation permit、工具原始参数或工具原始返回；
- evidence ID、payload digest、内部 workflow/checkpoint ID；
- 内部 gate reasons、堆栈、供应商响应体或敏感审计事件。

内部 `AgentWorkflowResult.evidence_ids`、permit 和 gate 细节只能用于服务端验证与审计，不能直接序列化为 HTTP DTO。

## 7. DeepSeek 安全降级

### 7.1 状态映射

| 场景 | 公开 model_status | 公开处理 | 禁止行为 |
| --- | --- | --- | --- |
| 未配置 Key | `not_configured` | 创建会话返回 409，建议使用 Fake | 不调用网络，不创建伪 DeepSeek 会话 |
| 供应商不可用/连接失败 | `unavailable` | 当前轮 `failed_safe`，无业务断言 | 不静默切 Fake，不显示 Fake 为模型回答 |
| 超时 | `timeout` | 当前轮 `failed_safe`；仅在合同安全时允许重试 | 不猜测模型计划或回复 |
| 限流 | `rate_limited` | 当前轮 `failed_safe`，提供稍后重试或新建 Fake 会话 | 不把限流写成回答成功 |
| 两次结构化输出仍失败 | `invalid_output` | 当前轮 `failed_safe` 或既有状态机明确的 clarify/escalate | 不执行未经验证计划，不公开原始输出 |

所有失败必须保留 `requested_mode=effective_mode=deepseek`，并给出安全原因码。前端可以提供“新建合成演示会话”操作，但不得在原会话内自动改 mode。

### 7.2 副作用边界

- 计划阶段模型失败：不得执行任何工具。
- 只读工具后草稿模型失败：保留内部已确认事实，但公开结果不得绕过 Response Gate。
- 写操作已成功而草稿失败：不得重放计划或写操作；保留幂等终态，向用户返回无未经校验事实的安全状态，后续通过可信状态查询/人工渠道处理。
- 高风险等待审批时模型或页面失败：审批与 pending 绑定保持服务端状态，不创建申请。

### 7.3 写后失败的公开投影

当工具写入已由可信仓储确认成功，但草稿生成、Response Gate 处理或 HTTP 响应发送失败时，服务端必须区分“模型回答失败”和“业务写入未知”：

- 已确认写入成功：保存 `agent_status=failed_safe`、对应模型失败的 `model_status`（Gate/投影内部失败时为 `not_used`）、稳定 `reason_code=RESPONSE_UNAVAILABLE_AFTER_COMMIT`、`can_retry=true`。公开 message 只能说明“回复暂不可用，可查询当前状态”，不得声称写入失败或披露未经 Gate 校验的申请事实。
- 写入状态未知：保存 `agent_status=failed_safe`、`model_status=not_used`、`reason_code=WRITE_OUTCOME_UNKNOWN`、`can_retry=false`；禁止自动重放写入，只允许可信状态查询或人工处理。
- `GET /conversations/{conversation_id}` 返回最近保存的公开快照；若后续可信只读查询确认业务终态，只能经 Response Gate 生成新的公开快照。GET 本身不调用模型、不执行工具写入、不 resume。
- 同一幂等 key 的 POST 重放返回已保存投影；即使 `can_retry=true`，其含义也只是允许重取公开结果，不代表允许重放模型、计划或写操作。用户明确发起新消息必须使用新 key，并仍受当前会话状态机约束。

## 8. 前端设计

### 8.1 模式选择

- 会话开始页提供两个单选项：`合成演示（默认）`、`DeepSeek Agent`。
- DeepSeek 未配置时禁用该选项并显示“服务端未配置”，不显示 Key 输入框。
- 创建会话后在页面持续显示模式徽标，避免用户误解回答来源。
- 模式切换通过明确确认后创建新会话；不修改当前会话模式或混合历史。

### 8.2 状态与错误

- Fake 模式标记为“确定性合成演示”，不得写成真实模型。
- DeepSeek 成功只有在 `model_status=succeeded` 且 Agent/Gate 形成公开回复时显示为模型成功。
- `unavailable`、`timeout`、`rate_limited`、`invalid_output` 显示不同的可行动提示。
- 安全失败时只展示公开 `reason_code` 对应文案，不展示供应商异常文本、堆栈或审计详情。

### 8.3 浏览器数据边界

- localStorage/sessionStorage 最多保存 conversation_id 和非敏感模式 ID。
- 不保存 API Key、模型配置、permit、工具参数、证据、审批内部备注或审计载荷。
- 前端类型不得包含后端内部 AgentState、EvidenceRecord 或 ExecutionPermit。

## 9. 服务端组合边界

- `AgentWorkflowFactory` 为 Fake 和 DeepSeek 分别构造共享业务依赖但不同 ModelGateway 的 `AgentWorkflowService`；不在每条消息中从用户参数动态注入模型对象。
- `AgentConversationService` 保存 conversation_id、固定模式、可信 user_id、turn 序号、已确认字段、字段修订历史、HTTP 幂等记录和公开快照。T-608 演示环境继续使用现有服务端固定 `_DEMO_USER_ID`；客户端不能提交或覆盖身份，且文档不得把它表述为生产认证。
- 每轮在调用 Agent 前，必须先由现有确定性 `ReturnInformationCollectionService`（或保持其同等已审计规则的适配器）处理用户消息、现有 `CollectionContext` 和字段修订，输出 `confirmed_order_id`、`confirmed_return_reason`、`confirmed_item_condition`、修订历史及下一问题。只有该确定性收集器保存的输出可注入 `TrustedAgentContext`；模型抽取只能作为不可信候选，冲突时不得覆盖 confirmed 值。
- 用户否定或更正字段时，由确定性收集器按既有修订规则生成新的服务端版本并保留历史；HTTP 层、前端或模型不得直接构造 confirmed 字段。退货写操作所需字段不完整时保持 `clarify` 且零写入；政策问答和已授权订单只读查询可按各自工具前置条件执行，不要求先凑齐全部退货字段。
- 每条真正的新用户消息生成新的服务端 turn_id；同一 `Idempotency-Key` 的重试复用首次签发的 turn 与公开结果，遵循 `http-idempotency-v1`，不得重复模型调用或业务写入。
- DeepSeek API Key 只从后端环境读取，进入供应商 Authorization header；配置对象、日志和异常序列化必须脱敏。
- 当前实现仍为进程内状态，重启后会话与 pending Agent 状态丢失；T-608 不把它描述为持久恢复。

### 9.1 应用级组合根与 Agent 会话注册表

- HTTP 应用启动时由唯一 composition root 构造并持有 `ApprovalTaskService`、checkpoint repository、service-case repository、`HighRiskReturnWorkflowService`、Fake/DeepSeek `AgentWorkflowService`、`AgentConversationService` 和 `AgentSessionRegistry`；router 与 factory 只能注入这些共享实例，禁止模块级或按请求另建第二套进程内仓储/工作流。
- `AgentWorkflowFactory` 只按会话固定模式选择共享业务依赖上的 ModelGateway，不拥有审批、checkpoint 或申请仓储的独立副本。
- `AgentSessionRegistry` 由服务端保存 `conversation_id + turn_id + trusted user_id + mode` 到唯一 pending workflow/AgentWorkflowService 的不透明绑定。它不接受客户端 workflow、approval、permit 或 evidence 标识，也不把绑定序列化到公开 DTO。
- 审批工作台 list/decide 与消费者 Agent 必须访问同一 `ApprovalTaskService` 和仓储。可信审批决定成功后，服务端依据 registry 绑定定位唯一 AgentWorkflowService，并使用服务端重建的 `TrustedAgentContext` 调用一次 `resume()`；消费者 `GET` 始终只读公开快照，永不触发 resume。
- pending 映射未找到、conversation/turn/user/mode 绑定漂移、检测到不同 factory/依赖图实例或进程重启丢失状态时，统一安全失败：公开 `agent_status=failed_safe`、`model_status=not_used`、`reason_code=AGENT_RESUME_STATE_UNAVAILABLE`、`can_retry=false`，不确认审批/申请事实、不创建或恢复申请，并记录脱敏审计事件。
- 重复审批决定/通知只能复用既有审批终态和公开快照；批准后最多产生同一申请，调整/拒绝保持零申请写入。

## 10. 测试设计

### 10.1 单元测试

- 模式枚举、默认 Fake、会话模式不可变和未知模式拒绝。
- 模式能力响应不包含 Key、Base URL、Prompt 或供应商异常。
- 内部 AgentWorkflowResult 到公开 DTO 的字段白名单与敏感字段拒绝。
- DeepSeek 错误到公开 model_status/reason_code 的稳定映射。
- 未配置 Key 时不构造网络请求。

### 10.2 API/组件测试

- 无 body/省略 mode 创建 Fake 会话并完成现有代表性 Agent 流程。
- 配置测试 DeepSeek Gateway 后，消息实际进入 `AgentWorkflowService.handle()` 而非确定性旧会话路径。
- DeepSeek 计划和草稿分别覆盖成功、超时、限流、不可用、一次修复成功和最终 invalid_output。
- 失败响应不含模型原始输出、Key、permit、工具参数、evidence ID、内部 gate reason 或堆栈。
- 订单越权、资格、审批前零写入、批准后单次恢复、调整/拒绝零写入和 Response Gate 回归保持通过。
- 人工决定后由可信服务端绑定调用 `resume()`；GET 会话不产生副作用。
- 重复 POST/审批通知/页面刷新不产生第二条模拟申请。
- 同 key 同 body 的并发请求和串行重试只签发一个 turn，最多调用一次模型和写工具；同 key 不同 body、跨 conversation/user/mode 重放返回 409 安全冲突。
- 写后草稿/Gate/网络响应失败再重试时只返回保存的安全投影，最多一条申请；写入结果未知时不自动重放。
- pending approval 的消息重试只返回同一 pending 快照；消费者 GET 刷新零副作用。
- 多轮确定性收集 order/reason/condition、否定与更正历史、模型候选与收集器冲突、伪造 confirmed 字段和信息不全零写入。
- high-risk 消费者会话到同一审批工作台 list，再分别 approve/adjust/reject 并读取同一会话；覆盖跨会话/用户伪造、重复决定/通知、不同 Factory 实例防护、绑定丢失和恢复后唯一申请。

### 10.3 前端测试

- 默认选择 Fake，正确显示合成演示标识。
- DeepSeek 未配置时禁用且不出现 Key 输入框。
- DeepSeek 配置后可创建独立会话并持续显示模式徽标。
- 五类模型失败状态显示安全且可行动的文案。
- 切换模式创建新会话，不复用或改写旧历史。
- DOM、浏览器存储和网络请求中不出现敏感字段。

### 10.4 回归门禁

- T-607 固定 Fake 集与安全对抗集必须保持通过。
- 现有消费者 Fake 演示保持默认可用。
- Agent 状态机、计划校验、工具白名单、EvidenceRecord、审批恢复和 Response Gate 专项保持通过。
- 文档测试、后端质量检查和前端格式/lint/test/build 均通过。

## 11. 真实 DeepSeek 评测

真实评测必须通过新 HTTP API 入口运行，不能只直接调用 ModelGateway 或 AgentWorkflowService，从而证明“页面所依赖的 API → Agent 内核 → Gate”链路实际接通。

### 11.1 受控用例

- 有效政策咨询：产生 `model_status=succeeded` 和 Gate 放行的带引用回复。
- 低风险标准退货：通过模型计划、受控工具和 Gate，最多创建一条模拟申请。
- 高风险退货：进入等待审批，人工决定前零申请写入；批准后可信恢复一次。
- 一条提示注入/越权计划对抗：不得突破工具白名单或公开敏感信息。

全部使用 T-001 合成身份、订单和政策，不发送真实个人或业务数据。

### 11.2 记录要求

评测报告记录：

- requested/effective mode、model_status、公开 outcome 和 reason_code；
- 模型标识、配置版本、Prompt 版本、数据集版本和代码 revision；
- 每步耗时、网络状态、预期/实际、通过/失败/跳过/阻塞及失败原因；
- API 与 Gate 的公开结果和脱敏审计关联，不记录 Key 或原始敏感请求。

### 11.3 放行口径

- 确定性 Fake、错误注入和安全回归是 T-608 的强制工程门禁。
- 要宣称“用户可实际使用 DeepSeek Agent”并允许 T-608 最终 PASS，必须至少实际完成上述 DeepSeek 正常政策、低风险、高风险和对抗代表路径，且安全断言全部通过。
- 缺少 Key 记为 `SKIPPED`；供应商、网络或限流导致无法完成记为 `BLOCKED`，均不得记为通过。
- 若真实 DeepSeek 评测未完成，Reviewer 最多给出条件结论；不得恢复 rc.2 候选发布或在 README/发布材料中宣称页面已验证 DeepSeek。

## 12. 验收标准

- 默认 Fake 会话保持向后兼容，并实际调用 Fake AgentWorkflowService，而非旧确定性会话编排。
- 配置 Key 后，DeepSeek 模式通过同一 HTTP 会话合同实际调用 DeepSeek AgentWorkflowService。
- 会话模式服务端固定且公开可辨；不存在同会话静默切换或伪装成功。
- 未配置、不可用、超时、限流和结构化失败均返回正确安全状态，不执行未经验证计划。
- HTTP 和前端不暴露 API Key、推理链、Prompt、permit、工具原始参数、EvidenceRecord、内部 workflow/checkpoint 或敏感审计。
- `http-idempotency-v1` 的绑定、状态、冲突、TTL 与重放语义通过并证明并发/网络重试最多一条申请，且幂等 key 不承载内部 Agent 权限数据。
- 已确认退货字段仅由确定性收集器签发和修订；模型候选、前端字段或伪造请求不能进入 `TrustedAgentContext`。
- HTTP API、Agent 会话和审批工作台复用同一应用级依赖图与 registry；审批决定只能恢复绑定的唯一 AgentWorkflowService，丢失或漂移时安全失败。
- 订单授权、资格规则、工具白名单、审批恢复、幂等和 Response Gate 的最终裁决保持不变。
- Fake 与供应商失败全套自动化测试通过；T-607 回归无退化。
- 真实 DeepSeek 四类代表路径有实际、可追溯且脱敏的通过证据，失败项如实保留。
- 文档仍明确当前是进程内合成工具环境，不是生产 Agent API，不实现 T-701～T-706。

## 13. Reviewer 检查重点

- 模式选择是否真正位于服务端信任边界，且默认 Fake 向后兼容。
- DeepSeek 失败是否可能被误显示成 Fake 或模型成功。
- HTTP DTO 是否泄露 AgentWorkflowResult 的内部证据、permit 或 Gate 细节。
- 审批恢复是否通过可信服务端绑定调用 `resume()`，且 GET 无副作用。
- 真实模型评测是否经过 HTTP 链路并足以支持“实际使用”声明。
- T-608 是否保持最小接入范围，未偷跑 T-701～T-706 或发布动作。
