# tasks-worker-service

`tasks-worker-service` 是面向 Job Platform 的 FastAPI + Worker 服务，保留轻量服务骨架的 API、配置、数据库和脚本合同，并显式管理宿主机 Worker 与 Compose Worker 运行模型。

## What Is Included

- FastAPI app factory 和 lifespan。
- section 化配置、`.env.example` manifest 校验和 release invariant。
- request id / trace id 中间件、access log、CORS、异常处理。
- success/error envelope、error registry、operation registry。
- `/health` 和 `/ready`。
- SQLAlchemy async、Alembic、UnitOfWork、repository。
- `items` CRUD 示例模块。
- lifecycle providers：Postgres、Redis fake boundary、object storage、shared HTTP client。
- Job Platform worker runtime：`QueueEnvelope` consumer、Worker Internal API client、handler registry 和 taskiq adapter。
- Worker 使用 Redis Stream taskiq broker，按 `TASKIQ__QUEUE_NAME` 监听物理队列，并由自有 runner 显式控制 ack。
- Worker 模板接入规范：manifest 注册、业务 task 目录、input_ref/output_ref、幂等、progress/cancel 和跨仓 Job Service smoke。
- `app/tools/` 示例工具模块。
- `dev.sh`、`deploy.sh`、`verify.sh`、`tools.sh` 脚本入口。
- 脚本公共能力：`doctor`、端口扫描、PID/log 管理、三种管理入口、迁移入口、secret/env-url 工具、registry/env/docs drift gate。
- Dockerfile、docker-compose.yml、`start-api.sh` API 容器入口和 `start-worker.sh` Worker 容器入口。

## Quick Start

Install dependencies:

```bash
uv sync
```

Run the default verification:

```bash
./scripts/verify.sh check
```

Show local development commands:

```bash
./scripts/dev.sh help
```

Check the local development environment:

```bash
./scripts/dev.sh doctor
```

Scan common local ports:

```bash
./scripts/dev.sh ports 8130 25435 26382
```

## Local Service Management

本仓库有 3 种本地管理方式，按控制粒度区分：

| Way | Commands | Scope |
|---|---|---|
| 日常入口 | `./scripts/deploy.sh up/status/down dev` | Docker PostgreSQL / Redis + 宿主机 API + 宿主机 Worker。 |
| 单进程入口 | `./scripts/dev.sh start/status/stop api|worker` | 只管理宿主机 API 或 Worker 进程，不启动或停止 Docker 依赖。 |
| 运行模型入口 | `./scripts/deploy.sh up/status/down local|worker|compose-deps|compose-full` | 精确选择本机组件、Docker 依赖或全 Docker 模型。 |

Start the common local development stack:

```bash
./scripts/deploy.sh up dev
```

This starts PostgreSQL and Redis with Docker Compose, then starts the FastAPI app and Worker runner on the host. The app process can start without opening a database connection, but `/ready` and the `items` API require a reachable PostgreSQL database unless tests inject a session override.

Run only local dependencies with Docker Compose:

```bash
./scripts/deploy.sh up compose-deps
```

Run only the host API:

```bash
./scripts/dev.sh start api
```

Run the API, Worker, PostgreSQL, and Redis in Compose:

```bash
./scripts/deploy.sh up compose-full
```

The Docker Worker still needs a reachable Job Service API and Job Redis broker. By default the Worker container calls `http://host.docker.internal:8110/internal/v1` and consumes `redis://host.docker.internal:26380/0`; override `WORKER__JOB_SERVICE_BASE_URL` and `TASKIQ__REDIS_URL` when Job Service is elsewhere.

Run the Job Platform worker on the host:

```bash
./scripts/dev.sh start worker
./scripts/dev.sh status worker
./scripts/dev.sh stop worker
```

Check the Worker template and optional Job Service smoke entry:

```bash
uv run python -m app.job_platform_worker.register_cli validate
./scripts/smoke-job-platform.sh check
```

Generate local secrets and encoded connection URLs:

```bash
./scripts/tools.sh secret
./scripts/tools.sh env-url postgres --username postgres --host 127.0.0.1 --port 25435 --database tasks_worker_service --password-stdin
```

## Documentation

- Current implementation facts: [`docs/current/implementation.md`](docs/current/implementation.md)
- Docs index: [`docs/README.md`](docs/README.md)
- Worker runtime: [`docs/current/worker-runtime.md`](docs/current/worker-runtime.md)
- Worker template guide: [`docs/current/worker-template.md`](docs/current/worker-template.md)
- HTTP API contract: [`docs/contracts/api-contract.md`](docs/contracts/api-contract.md)
- Extension contract: [`docs/contracts/extension-contract.md`](docs/contracts/extension-contract.md)
- Scripts contract: [`scripts/README.md`](scripts/README.md)

## Verification

Default gate:

```bash
./scripts/verify.sh check
```

PostgreSQL integration gate:

```bash
./scripts/verify.sh postgres
```

The Postgres gate is opt-in and protected by a `_test` database check.

Migration roundtrip gate:

```bash
./scripts/verify.sh migration-roundtrip
```

Optional cross-repo Job Platform smoke:

```bash
./scripts/verify.sh job-platform-smoke
```
