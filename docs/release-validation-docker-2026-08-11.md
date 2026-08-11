# Docker 发布验证记录（2026-08-11）

## 结论

Docker 构建、启动、健康检查、连通性、日志和清理闭环已在全新纯 ASCII 副本中完成。验证过程中发现并修复两个项目 Docker 配置问题：后端镜像缺少运行时 `config/`、`data/`，以及宿主端口不可覆盖。项目版本、业务代码和安全边界未修改。

本记录只关闭 Docker 技术验证阻塞，不授权提交、Tag、推送或发布。进入正式发布操作仍须项目所有者明确授权，并按发布清单核对当前未提交变更。

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
