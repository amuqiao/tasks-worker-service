# FastAPI Lite 全局心智模型

本文是一张 `fastapi-lite` 工程地图：帮助你快速知道这套骨架有什么、边界在哪里、开发新业务时应该先看哪里。

## 文档定位

这篇文档只负责建立全局视角，不作为权威合同，不替代实现文档、API 文档、扩展合同或计划文档。

权威来源按职责分工：

- 已实现事实：[`../current/implementation.md`](../current/implementation.md)
- HTTP 调用合同：[`../contracts/api-contract.md`](../contracts/api-contract.md)
- 新功能扩展规则：[`../contracts/extension-contract.md`](../contracts/extension-contract.md)
- P1 缺口和漂移检查：[`../plans/drift-checklist.md`](../plans/drift-checklist.md)
- 脚本入口说明：[`../../scripts/README.md`](../../scripts/README.md)

## 一句话理解

`fastapi-lite` 是面向业务 HTTP API 的轻量服务骨架。它已经固定了 HTTP 请求处理、配置、日志、错误、数据库访问、provider lifecycle、示例业务、脚本和验证范式；worker、broker、outbox、reconciler 和更完整观测能力仍是后续扩展点。

它的价值不是预置所有基础设施，而是让不同业务服务按同一套工程范式扩展，避免目录、配置、错误码、仓储、日志、启动脚本和验证方式各自漂移。

## 阅读路径

如果你要开发业务 API 服务，按这个顺序读：

1. 本文，建立全局模型。
2. [`../contracts/extension-contract.md`](../contracts/extension-contract.md)，确认新增模块规则。
3. [`../../app/api/routes/items.py`](../../app/api/routes/items.py)、[`../../app/services/item_service.py`](../../app/services/item_service.py)、[`../../app/repositories/item_repository.py`](../../app/repositories/item_repository.py)、[`../../app/models/item.py`](../../app/models/item.py)，照 `items` 示例落业务链路。
4. [`../contracts/api-contract.md`](../contracts/api-contract.md)，同步 HTTP 合同。
5. [`../plans/drift-checklist.md`](../plans/drift-checklist.md)，提交前做漂移检查。

如果你要接入新的外部资源，优先看：

1. [`../../app/core/lifecycle.py`](../../app/core/lifecycle.py)
2. [`../../app/integrations/postgres.py`](../../app/integrations/postgres.py)
3. [`../../app/integrations/storage.py`](../../app/integrations/storage.py)
4. [`../contracts/extension-contract.md`](../contracts/extension-contract.md) 的 provider 章节。

如果你要调整本地开发、部署或验证入口，看 [`../../scripts/README.md`](../../scripts/README.md)，不要先复制新增脚本。

## 整体分层

当前骨架按三层理解：

```text
foundation
  -> config / logging / request context / error envelope / registries / scripts

integrations
  -> Postgres lifecycle / Redis fake boundary / object storage / shared HTTP client

example domain
  -> items route / schema / service / repository / ORM model / migration
```

`foundation` 是所有服务共享的工程规则。`integrations` 是外部资源的接入范式。`example domain` 不是目标业务，而是新增业务模块的样板。

## 运行面一：HTTP 请求链路

单次 HTTP 请求只经过运行时链路，不经过 migration、文档 drift gate 或测试：

```text
request
  -> request_id / trace_id middleware
  -> auth dependency
  -> schema validation
  -> route
  -> service
  -> UowFactory
  -> UnitOfWork
  -> repository
  -> ORM model
  -> database
  -> AppError / validation / unexpected error mapping
  -> success/error envelope
```

排障时也先按这个链路看：header/context 是否正确，auth 是否通过，schema 是否校验失败，service 是否抛出 `AppError`，repository/DB 是否返回预期结果，最后 envelope 是否符合合同。

业务运行路径要求显式注入 `UowFactory`。底层仍保留少量 DB helper 用于测试和兼容场景，但新业务 service 不应隐式依赖全局数据库状态。

## 运行面二：Provider / Lifespan 链路

外部资源不在请求中临时创建，而是在 lifespan 中统一启动、检查和关闭：

```text
settings
  -> lifecycle provider registry
  -> provider startup
  -> typed app.state resource
  -> health check registration
  -> /ready
  -> reverse shutdown
```

provider seam 已经稳定，但 adapter 成熟度不同：

- PostgreSQL provider 已接入 async engine 和 session factory。
- Redis 当前只有 fake boundary；启用真实 Redis 会 fail fast。
- Object storage 当前支持 `disabled` 和 local filesystem；S3-compatible 仍在计划中。
- HTTP client provider 提供 shared `httpx.AsyncClient`，并透传 request/trace headers。

## 变更面：开发和验证链路

新增或修改业务能力时，才进入变更/验证链路：

```text
schema / route / service / repository / model
  -> operation registry
  -> error registry
  -> Alembic migration
  -> API contract Routes table
  -> tests
  -> verify gate
```

具体字段、命名、测试和验证要求不要在本文维护，统一看 [`../contracts/extension-contract.md`](../contracts/extension-contract.md)。本文只提醒你：运行链路和变更链路是两件事，不要把 migration、docs drift、tests 当成单次请求的一部分。

## 骨架组成

| 层面 | 当前有什么 | 应如何理解 |
|---|---|---|
| HTTP foundation | app factory、middleware、exception handlers、OpenAPI 定制 | 固定请求入口、响应 envelope、错误映射和合同投影。 |
| Context / logging | request id、trace id、access/error 稳定字段 | 保证请求、日志和下游 HTTP client 能串起来；不是完整 OTel/metrics 平台。 |
| Config | section 化 settings、env manifest、release invariant | 新配置必须进入 typed section 和 env 校验链路。 |
| Data | SQLAlchemy async、Alembic、UoW、repository、`items` 示例 | 提供数据库访问和业务模块分层范式。 |
| Providers | Postgres、Redis fake、object storage、HTTP client | 固定外部资源接入方式；不同 adapter 完成度不同。 |
| Registries | error registry、operation registry、health registry、provider registry | 用注册点减少隐性约定，并让 verify 能发现漂移。 |
| Tools | `app/tools/example_tool.py` | 给纯工具模块提供放置和校验样板。 |
| Scripts | `dev.sh`、`deploy.sh`、`verify.sh`、`tools.sh` | 统一开发、部署、验证和本地工具入口。 |
| Docs | current / contracts / plans | 分开维护“已实现事实、稳定合同、未来计划”。 |

## 扩展时怎么判断放哪里

新增业务能力：

```text
app/api/routes
app/schemas
app/services
app/repositories
app/models
alembic/versions
tests
docs/contracts/api-contract.md
```

具体步骤看 [`../contracts/extension-contract.md`](../contracts/extension-contract.md) 的 business module 和 API contract 章节。

新增外部资源：

```text
app/core/config
app/integrations
app/core/lifecycle.py
tests
docs/current 或 docs/contracts
```

它必须走 provider/lifespan，不要在 import 时创建连接。

新增 middleware：

```text
app/core/middleware.py
app/main.py:create_app()
tests
docs/contracts/extension-contract.md
```

middleware 只做 HTTP 横切能力，不放业务规则、数据库事务、provider lifecycle 或 route-specific auth。

新增工具：

```text
app/tools
tests/test_tools.py
```

纯工具先保持静态 spec + schema + callable + tests。不要提前做 dynamic tool catalog。

新增脚本能力：

```text
scripts/dev.sh       # 本地开发生命周期
scripts/verify.sh    # 一次性验证
scripts/deploy.sh    # 部署模型 / compose
scripts/tools.sh     # 无默认持久副作用的本地工具
scripts/lib          # shell helper
```

脚本详细规则看 [`../../scripts/README.md`](../../scripts/README.md) 和 [`../contracts/extension-contract.md`](../contracts/extension-contract.md)。

## 当前不属于骨架的能力

这些类别当前不属于已实现基础骨架，不应在业务服务里假设已经可用：

- worker / broker / outbox / DLQ / reconciler。
- Celery / Taskiq / Kafka / RabbitMQ。
- 真实 Redis adapter、S3-compatible storage adapter。
- metrics / rate limit / OpenTelemetry / Prometheus。
- provider retry / backoff / bulkhead。
- dynamic tool catalog。

具体 P1 backlog 以 [`../plans/drift-checklist.md`](../plans/drift-checklist.md) 为准。等真实业务服务或 worker 服务出现需求时，再按现有范式沉淀新的稳定接入方式。

## 稳定性判断

当前 `fastapi-lite` 已经适合作为业务 API 服务骨架。这个判断建立在 [`../current/implementation.md`](../current/implementation.md) 的已实现事实和验证基线上：

- HTTP 请求链路闭合。
- 数据访问范式闭合。
- HTTP 合同和 OpenAPI drift gate 闭合。
- provider/lifespan 范式闭合。
- 脚本和验证入口可用。
- 文档分层明确。

后续新增功能时，优先遵守一个原则：

```text
能复用已有范式就复用；
需要新增范式时，先补合同、示例和验证；
没有真实业务需求时，不提前引入复杂基础设施。
```
