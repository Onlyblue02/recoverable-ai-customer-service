# RACS 本地启动指南

## Windows 双击启动

已安装依赖时，直接双击项目中的 `scripts/启动本地演示.cmd`。它会启动本地演示并自动打开消费者页面。停止时双击 `scripts/停止本地演示.cmd`。

首次安装依赖或依赖有变更时，请使用下方 PowerShell 启动命令（不要使用 `-SkipInstall`）。

## PyCharm 一键启动

重新加载项目后，在窗口右上角的运行配置下拉框选择“启动本地演示”，点击绿色三角运行按钮。它会调用现有启动脚本并自动打开消费者页面。停止时在同一位置选择“停止本地演示”。

本指南用于本仓库的合成演示环境。它不会连接真实订单、支付、物流或退款系统，也不会要求发送真实个人信息。

## 前置条件

- Python 3.12、Node.js 24、pnpm 11。
- 已安装 `uv`，或已有仓库内 `.venv`。
- 无需配置 DeepSeek API Key 即可完成消费者、审批和固定验收演示。
- Docker Compose 是可选路径；当前项目记录中 Docker CLI/Compose 端到端验证尚未完成，不能作为本次演示的已验证前提。

## 一键启动（推荐）

在仓库根目录打开 PowerShell 后直接执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_local_demo.ps1
```

脚本会检查 Python、`uv` 和 `pnpm`；若 `pnpm` 未进入 PATH，则自动尝试 Node 的 `corepack pnpm`。它会设置 `UV_LINK_MODE=copy`（避免 OneDrive 硬链接问题），自动同步依赖，并从 `8000`、`8010`、`8020`、`18000` 依次选择可用后端端口。它会将同一端口传给后端和 Vite 代理，随后输出消费者页面 URL。无需配置 DeepSeek API Key。

若依赖已安装，可加入 `-SkipInstall`：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_local_demo.ps1 -SkipInstall
```

停止本次脚本启动的进程：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\stop_local_demo.ps1
```

## 安装依赖

在仓库根目录执行：

```powershell
uv sync --frozen --all-groups
pnpm --dir web install --frozen-lockfile
```

如只使用已存在的本地虚拟环境，可跳过第一条安装命令。`.env.example` 仅包含开发默认值；不要将实际 `DEEPSEEK_API_KEY` 提交到 Git、报告或截图中。

## 启动后端

如需手动启动，可新开一个 PowerShell：

```powershell
uv run python -m customer_service.local_server
```

默认验证地址为 `http://127.0.0.1:8000/health/live`。如需改端口，在启动前设置 `RACS_BACKEND_PORT`；一键脚本会自动完成该设置。

## 启动前端

再开一个 PowerShell：

```powershell
$env:VITE_RACS_BACKEND_PORT = $env:RACS_BACKEND_PORT
pnpm --dir web dev -- --host 127.0.0.1 --port 5173
```

打开 `http://127.0.0.1:5173`。开发服务器会将 `/api` 代理到 `VITE_RACS_BACKEND_PORT` 指定的本地端口，默认仍是 `8000`；若后端未启动，页面会安全显示“需要协助”，不会虚构完成。

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
| 8000 端口报 WinError 10013 | 使用一键启动脚本；它会自动尝试 8010、8020、18000，并让 Vite 使用同一后端端口。 |

## 停止与边界

一键启动时运行 `powershell -ExecutionPolicy Bypass -File .\scripts\stop_local_demo.ps1` 停止服务；手动启动时在两个终端中按 `Ctrl+C`。所有申请均为模拟申请；批准或“已完成”不代表退款、取消订单或其他不可逆业务操作。
