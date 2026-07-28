# RACS 本地启动指南

本指南用于本仓库的合成演示环境。它不会连接真实订单、支付、物流或退款系统，也不会要求发送真实个人信息。

## 前置条件

- Python 3.12、Node.js 24、pnpm 11。
- 已安装 `uv`，或已有仓库内 `.venv`。
- 无需配置 DeepSeek API Key 即可完成消费者、审批和固定验收演示。
- Docker Compose 是可选路径；当前项目记录中 Docker CLI/Compose 端到端验证尚未完成，不能作为本次演示的已验证前提。

## 安装依赖

在仓库根目录执行：

```powershell
uv sync --frozen --all-groups
pnpm --dir web install --frozen-lockfile
```

如只使用已存在的本地虚拟环境，可跳过第一条安装命令。`.env.example` 仅包含开发默认值；不要将实际 `DEEPSEEK_API_KEY` 提交到 Git、报告或截图中。

## 启动后端

新开一个 PowerShell：

```powershell
uv run uvicorn customer_service.main:app --host 127.0.0.1 --port 8000 --reload
```

验证：打开 `http://127.0.0.1:8000/health/live`，应返回存活响应。

## 启动前端

再开一个 PowerShell：

```powershell
pnpm --dir web dev -- --host 127.0.0.1 --port 5173
```

打开 `http://127.0.0.1:5173`。开发服务器已将 `/api` 代理到 `http://127.0.0.1:8000`；若后端未启动，页面会安全显示“需要协助”，不会虚构完成。

## 演示前检查

```powershell
.venv\Scripts\python.exe -m customer_service.acceptance_reporting.runner --output reports/evaluations/t403-fixed-acceptance.json
.venv\Scripts\pytest.exe tests/component/interfaces tests/component/acceptance_reporting -q
pnpm --dir web test
```

运行器预期输出 `10/10 passed`。生成的 JSON 位于被 Git 忽略的 `reports/evaluations/`；可提交的审计摘要是 `docs/acceptance/T-403-fixed-acceptance-report.md`。

## 常见问题

| 现象 | 处理方式 |
| --- | --- |
| 前端显示“需要协助” | 确认后端的 `health/live` 可访问，然后刷新页面。 |
| 审批列表为空 | 先在消费者会话中完成高金额订单的三轮输入，再滚动到页面下方的审批工作台。 |
| 刷新后会话丢失 | 当前会话与审批状态是进程内合成状态；后端重启后创建新会话，不要把它当作持久化恢复。 |
| `pnpm` 无法识别 | 安装 pnpm 11，重新打开终端，或使用已安装 pnpm 的完整路径。 |
| Docker 命令不可用 | 使用上述本地双进程演示；不要把 Compose 未执行写成通过。 |

## 停止与边界

在两个终端中按 `Ctrl+C` 停止服务。所有申请均为模拟申请；批准或“已完成”不代表退款、取消订单或其他不可逆业务操作。
