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
- `app/tools/` 示例工具模块。
- `dev.sh`、`deploy.sh`、`verify.sh` 脚本入口。

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

Run the API locally:

```bash
./scripts/dev.sh start
```

The app process can start without opening a database connection, but `/ready` and the `items` API require a reachable PostgreSQL database unless tests inject a session override.

## Documentation

- Current implementation facts: [`docs/current/implementation.md`](docs/current/implementation.md)
- HTTP API contract: [`docs/contracts/api-contract.md`](docs/contracts/api-contract.md)
- Extension contract: [`docs/contracts/extension-contract.md`](docs/contracts/extension-contract.md)
- Drift checklist and P1 plan: [`docs/plans/drift-checklist.md`](docs/plans/drift-checklist.md)
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
