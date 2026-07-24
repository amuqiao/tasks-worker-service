# fastapi-lite

`fastapi-lite` 是一套轻量但不空心的 FastAPI 服务骨架，用来统一后续业务 API、worker-adjacent API 和内部服务的工程范式。

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
- 脚本公共能力：`doctor`、端口扫描、PID/log 管理、三模式部署入口、迁移入口、secret/env-url 工具、registry/env/docs drift gate。
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
./scripts/dev.sh ports 8100 25432 26379
```

Start the common local development stack:

```bash
./scripts/deploy.sh up dev
```

This starts PostgreSQL and Redis with Docker Compose, then starts the FastAPI app on the host. The app process can start without opening a database connection, but `/ready` and the `items` API require a reachable PostgreSQL database unless tests inject a session override.

Run only local dependencies with Docker Compose:

```bash
./scripts/deploy.sh up compose-deps
```

Run only the host API:

```bash
./scripts/dev.sh start api
```

Run the API, PostgreSQL, and Redis in Compose:

```bash
./scripts/deploy.sh up compose-full
```

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
./scripts/tools.sh env-url postgres --username postgres --host 127.0.0.1 --database fastapi_lite --password-stdin
```

## Documentation

- Current implementation facts: [`docs/current/implementation.md`](docs/current/implementation.md)
- Worker runtime: [`docs/current/worker-runtime.md`](docs/current/worker-runtime.md)
- Worker template guide: [`docs/current/worker-template.md`](docs/current/worker-template.md)
- HTTP API contract: [`docs/contracts/api-contract.md`](docs/contracts/api-contract.md)
- Extension contract: [`docs/contracts/extension-contract.md`](docs/contracts/extension-contract.md)
- Drift checklist and P1 plan: [`docs/plans/drift-checklist.md`](docs/plans/drift-checklist.md)
- Scripts contract: [`scripts/README.md`](scripts/README.md)
- Original skeleton target: [`docs/FastAPI服务骨架.md`](docs/FastAPI服务骨架.md)

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
