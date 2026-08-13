# Docker 发布验证记录（2026-08-11）

## 结论

Docker 构建、启动、健康检查、连通性、日志和清理闭环已在全新纯 ASCII 副本中完成。验证过程中发现并修复两个项目 Docker 配置问题：后端镜像缺少运行时 `config/`、`data/`，以及宿主端口不可覆盖。项目版本、业务代码和安全边界未修改。

本记录只关闭 Docker 技术验证阻塞，不授权提交、Tag、推送或发布。进入正式发布操作仍须项目所有者明确授权，并按发布清单核对当前未提交变更。

2026-08-13，项目所有者确认最新 post-fix Docker 发布验证闭环已获 Reviewer `PASS`，并授权将已核对的修复及本记录纳入本地 `v1.0.0-rc.2` 候选提交；该授权不包含远程推送或正式 `v1.0.0` 发布。

## 环境

- Docker Desktop：`4.79.0 (230596)`。
- Docker Client/Engine：`29.5.3`，context `desktop-linux`。
- Docker Compose：`v5.1.4`。
- Docker Buildx：`v0.34.1-desktop.1`。
- `default`、`desktop-linux` builder：均为 `running`，BuildKit `v0.30.0`。
- `docker compose -f deploy/compose.yaml config --quiet`：主工作区通过；端口覆盖配置也通过。

## 镜像仓库与镜像

以下固定镜像均成功拉取或确认 digest 已存在：

- `docker/dockerfile:1`
- `pgvector/pgvector:0.8.2-pg17-bookworm`
- `ghcr.io/astral-sh/uv:0.11.23`
- `python:3.12.13-slim-bookworm`
- `node:24.18.0-alpine`
- `nginx:1.29-alpine`

Docker Hub 的元数据请求仍明显缓慢：BuildKit frontend digest 解析约 120 秒，基础镜像元数据约 42 秒；但请求最终成功，没有将该延迟写成项目故障。

## ASCII 副本一致性

- 验证路径：`C:\temp\racs-docker-verify-20260811`。
- deploy 文件、`pyproject.toml`、`uv.lock`、`README.md`、前端清单/锁文件 SHA-256 全部与主工作区一致。
- `src/`、`web/` 排除生成物后的 106 个文件，路径和 SHA-256 清单完全一致。
- 修复后重新同步 `deploy/`、`config/`、`data/`；副本包含 1 个配置文件和 23 个数据文件。
- 未复制 `.git`、虚拟环境、密钥、`node_modules`、`dist`、缓存或测试临时目录。

## 发现与修复

### 后端镜像运行时文件缺失

初次构建成功后，两个 API 均在启动时失败：

```text
mock_business.repository.MockBusinessDataError:
cannot load mock business data file /app/data/manifest.json: [Errno 2] No such file or directory
```

原因是 `deploy/backend.Dockerfile` 只复制 `src/`，没有复制运行时所需的 `data/`；业务路由还会读取 `config/return-eligibility-rules.v1.json`。修复为在安装项目包前复制 `config/` 与 `data/`。

### Windows 宿主端口冲突

Windows TCP 排除范围 `7912–8011` 覆盖默认端口 8000/8001，原始固定端口启动返回：

```text
ports are not available: listen tcp 0.0.0.0:8000:
bind: An attempt was made to access a socket in a way forbidden by its access permissions
```

随后 `KLCertMgr` 还占用了诊断端口 18001。Compose 宿主端口改为可配置、默认值保持不变：

- `RACS_BACKEND_PORT`，默认 `8000`
- `RACS_MOCK_BUSINESS_PORT`，默认 `8001`
- `RACS_WEB_PORT`，默认 `5173`

容器内部端口和健康检查未改变。最终使用 `18000`、`28001`、`15173` 完成验证。

## 构建、健康和连通性结果

执行：

```powershell
docker compose -p racsverify20260811 -f deploy/compose.yaml up --build -d
docker compose -p racsverify20260811 -f deploy/compose.yaml ps
```

结果：三个项目镜像构建成功，四个服务全部启动。

- PostgreSQL：`healthy`；`pg_isready -U racs -d racs` 返回 `accepting connections`。
- `racs-api`：`healthy`；宿主 `/health/live` 返回 HTTP 200、`{"status":"ok"}`。
- `mock-business-api`：`healthy`；宿主 `/health/live` 返回 HTTP 200。
- Mock 业务读取：授权查询 `ORD-NORMAL-001 / USR-DEMO-001` 返回 HTTP 200 和合成订单事实。
- Web：宿主 `/` 返回 HTTP 200 和 RACS HTML/静态资源引用。
- `racs-api → mock-business-api`：容器内 DNS/HTTP 返回 200。
- `web → racs-api`：容器内 HTTP 返回 `{"status":"ok"}`。
- 日志显示 PostgreSQL ready、两个 Uvicorn application startup complete、nginx ready；保留既有 Starlette TestClient 弃用警告。

## 测试与清理

- 新增 Docker 交付契约测试，覆盖镜像必须包含 `config/data`、端口覆盖不改变容器端口，以及健康检查仍存在。
- Docker 契约与发布记录专项：`6 passed`。
- 文档测试：18 passed。
- Ruff format/check、mypy 与 `git diff --check`：全部通过。

执行：

```powershell
docker compose -p racsverify20260811 -f deploy/compose.yaml logs --no-color --timestamps
docker compose -p racsverify20260811 -f deploy/compose.yaml down --volumes --remove-orphans
docker compose -p racsverify20260811 -f deploy/compose.yaml ps -a
docker volume inspect racsverify20260811_postgres-data
docker volume ls --filter "name=^racsverify20260811_postgres-data$" --format "{{.Name}}"
```

清理复核环境为 Docker Desktop `4.79.0`、Client/Engine `29.5.3`、Compose `v5.1.4`。实际结果：

- `down --volumes --remove-orphans`：退出码 `0`。
- Compose `ps -a`：退出码 `0`，仅输出空表头，无项目容器。
- `docker volume inspect racsverify20260811_postgres-data`：退出码 `1`，返回 `no such volume`；这是精确卷不存在的预期证据。
- 精确名称过滤的 `docker volume ls`：退出码 `0`、空输出。
- 项目 label 过滤的容器和网络列表：均为空。

因此项目容器、网络和命名卷均无残留。三个 `racsverify20260811-*` 验证镜像和 ASCII 临时副本也已移除；其他正在运行的 Docker 项目未触碰。

## T-608 提交后复验（提交 `5b24609f`）

2026-08-11 使用已提交且干净的 `5b24609fba10ce9a189c06f8b0da87efda0082ea`（`feat(agent): expose controlled workflow through web API`）建立 pre-fix 基线。初始副本为 `C:\temp\racs-docker-verify-5b24609`，由 `git archive HEAD` 导出，不含 `.git`、虚拟环境、测试缓存或凭据。141 个基线构建输入经仓库同一 Git clean filter 后与 HEAD blob 全部一致（0 mismatch）；该 pre-fix 副本 SHA-256 manifest digest 为 `9f874973e8db0d497d5327f07b376599685b0fb4b6924c7329fd895f952f20c9`。这个身份只证明复现 `/api` 404 的提交基线，不代表后续未提交的 nginx 修复输入。

实际环境仍为 Docker Desktop `4.79.0`、Client/Engine `29.5.3`、Compose `v5.1.4`、Buildx `v0.34.1-desktop.1`。使用固定项目名 `racsverify5b24609` 和隔离宿主端口 `18000`、`28001`、`15173` 执行：

```powershell
docker compose -p racsverify5b24609 -f deploy/compose.yaml config --quiet
docker compose -p racsverify5b24609 -f deploy/compose.yaml up --build -d
docker compose -p racsverify5b24609 -f deploy/compose.yaml ps
```

三条命令均退出 `0`，后端、Mock 与 Web 镜像构建成功。首次运行发现生产 Web 的 `/api/v1/agent/modes` 返回 HTTP 404：Vite 开发代理不会进入 nginx 生产镜像，因此页面无法调用已实现的 HTTP Agent。这是项目 Docker 配置问题，最小修复为新增 `deploy/nginx.conf`，将 `/api/` 代理到既有 `racs-api:8000`，并由 `deploy/web.Dockerfile` 复制该配置；未改变 Agent、权限、审批、Response Gate 或模型边界。修复后重新执行 config/build/up，均退出 `0`。

修复后实际结果：

- PostgreSQL、`racs-api`、`mock-business-api` 均为 `healthy`；`pg_isready` 返回 `accepting connections`。
- Web `/` 返回 HTTP 200；Web 同源 `/api/v1/agent/modes` 返回 `agent-modes-v1`，证明浏览器到 API 的生产代理链路可用。
- Web 容器到 `racs-api` HTTP 200；`racs-api` 容器到 Mock API HTTP 200、到 PostgreSQL TCP 5432 成功。
- Fake 政策咨询通过同源 Web API 完成，`RESPONSE_GATE_ALLOWED` 且含 1 条可信政策引用。
- Fake 低风险退货完成并仅创建 `SC-SIM-001`；状态为 `completed`、`RESPONSE_GATE_ALLOWED`。
- Fake 高风险退货在审批前为 `waiting_approval` 且无申请；批准后受控恢复，最终 `completed`、`RESPONSE_GATE_ALLOWED`，创建 `SC-SIM-002`。
- 容器模式合同明确显示 DeepSeek `configured=false`、`selectable=false`。Compose 未显式注入 DeepSeek 凭据，因此真实模型 Docker 路径未执行，既不计失败也不计通过。
- Compose 日志记录所有上述同源 API 请求为 HTTP 200；未记录 API Key、Authorization、permit、推理链或内部证据载荷。

清理实际执行：

```powershell
docker compose -p racsverify5b24609 -f deploy/compose.yaml down --volumes --remove-orphans
docker compose -p racsverify5b24609 -f deploy/compose.yaml ps -a
docker volume inspect racsverify5b24609_postgres-data
```

`down` 退出 `0`；最终 `ps -a` 仅有空表头；卷 inspect 以预期的 `no such volume` 退出 `1`。项目 label 过滤后的容器、网络、卷均为 0，三个精确命名的验证镜像也已删除。清理前后其他项目的三个既有容器 ID 完全一致，未停止或删除其他项目资源。ASCII 验证副本仅在验证与记录核对期间保留，完成记录后删除。

## nginx 修复后内容身份复验

Reviewer 指出上述提交身份不能单独证明未提交的 nginx 修复，且第一版 post-fix manifest 仍受 Windows `core.autocrlf=true` 影响，把 archive 的 CRLF 字节错误标成 HEAD 原始字节；旧 digest `a5464d23…` 及其运行不作为通过证据。有效复验副本为 `C:\temp\racs-docker-postfix-raw-5b24609`：使用 `git -c core.autocrlf=false archive HEAD` 物化全部 HEAD 原始字节，再在任何构建前显式覆盖当前工作树的 `deploy/nginx.conf` 与 `deploy/web.Dockerfile`。随后对实际副本的全部 142 个构建输入生成逐文件 `path`、`source`、`sha256`、`size` 清单：两项修复标记为 `working-tree`，其余 140 项标记为 `HEAD`。完整清单见 `docs/evaluations/docker-compose-5b24609-post-fix-manifest.json`。

- manifest 版本：`docker-post-fix-input-v2`
- 基础 revision：`5b24609fba10ce9a189c06f8b0da87efda0082ea`
- post-fix digest：`4cbba7d00f4c3b8bbf713fca47703fbc319c710ea55844e6709407d3cb2d8b0f`
- `deploy/nginx.conf`（`working-tree`）：`879e76a962e892c21e9b3a0daeb71b76d9b8b312b7004a69f5779cf8cc932e16`
- `deploy/web.Dockerfile`（`working-tree`）：`baf45d32d28d8df8394b447b703f841bf076ff510ddc7f830adfbaac1536a196`
- `deploy/compose.yaml`（`HEAD`）：`c0b474708af0605de214682bf9c17587805b3fb822fad558040016b5a35864c2`
- `deploy/backend.Dockerfile`（`HEAD`）：`a639146d1f96a601ca529cbdde278c8d9bdb354eda0df552d05cd5d93d538586`

实际构建前读取该副本中的 manifest 并打印同一 post-fix digest，随后以新项目名执行：

```powershell
docker compose -p racsverifyraw5b24609 -f deploy/compose.yaml config --quiet
docker compose -p racsverifyraw5b24609 -f deploy/compose.yaml up --build -d
docker compose -p racsverifyraw5b24609 -f deploy/compose.yaml ps
```

三项均退出 `0`。构建日志明确包含 `COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf`，因此实际运行镜像与上述 post-fix manifest 对应。PostgreSQL、`racs-api`、Mock API 均为 `healthy`；Web HTTP 200、同源 `/api/v1/agent/modes` HTTP 200；Web→API、API→Mock、API→PostgreSQL 均连通。Fake 政策为 `completed / RESPONSE_GATE_ALLOWED / 1 citation`，低风险为 `completed / SC-SIM-001`，高风险审批前 `waiting_approval` 且无申请、批准后 `completed / RESPONSE_GATE_ALLOWED / SC-SIM-002`。DeepSeek 在 Compose 中仍为 `configured=false`，真实模型 Docker 路径未执行且不计通过或失败。

最后实际执行 `down --volumes --remove-orphans`（退出 `0`）；`ps -a` 空表；精确卷 inspect 返回 `no such volume`（预期退出 `1`）；项目容器、网络、卷均为 0。修复后逐项结果见 `docs/evaluations/docker-compose-5b24609-post-fix-validation.log`。该复验只证明当前未提交 Docker 修复的内容身份和运行结果，不把基础 commit 单独表述为修复后完整输入。
