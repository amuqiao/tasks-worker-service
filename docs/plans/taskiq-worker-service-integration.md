# Taskiq Worker Service Integration Plan

本文规划 `tasks-platform` Job Service 与 `fastapi-lite` Worker Service 的 taskiq 对接路线：taskiq 只负责消息发送和接收，Job 生命周期权威仍由 Job Service 通过数据库、outbox、lease、reconciler 和 Worker Internal HTTP API 维护。

## Document Scope

本文负责：

- 定义微服务拆分后的目标交互模型。
- 说明 taskiq 在 Job Service 和 Worker Service 中的职责边界。
- 规划 `tasks-platform` 侧 dispatcher/publisher 改造。
- 规划 `fastapi-lite` 侧 worker runtime、taskiq consumer 和本地执行表。
- 给出先打通链路、后接具体业务的实施顺序和验收标准。

本文不负责：

- 把未实现能力写入 current implementation。
- 定义新的外部 HTTP 字段合同；Worker API 字段以 `tasks-platform` 合同为准。
- 选择最终业务 handler、模型服务、对象存储业务目录或具体任务 schema。
- 要求 Job Service 导入 Worker Service 业务代码。

相关资料：

- 当前骨架事实：[`../current/implementation.md`](../current/implementation.md)
- 扩展规则：[`../contracts/extension-contract.md`](../contracts/extension-contract.md)
- `tasks-platform` 当前事实：[`../../../tasks-platform/docs/current/implementation.md`](../../../tasks-platform/docs/current/implementation.md)
- `tasks-platform` API 合同：[`../../../tasks-platform/docs/contracts/api-contract.md`](../../../tasks-platform/docs/contracts/api-contract.md)
- `tasks-platform` Phase 1 计划：[`../../../tasks-platform/docs/plans/phase-1.md`](../../../tasks-platform/docs/plans/phase-1.md)

## Mental Model

旧单仓库模式里，API pod 和 worker pod 来自同一个仓库、同一个镜像、同一套 ORM model 和同一个数据库。taskiq 投递的是同仓库 Python task，例如 `jobs.run_attempt(attempt_id)`；worker 收到后可以直接 import `JobRepo`、claim attempt、执行 job runner，并直接写 Job DB。

微服务拆分后，这个边界必须改变：

```text
tasks-platform
  owns job_run / job_node / job_attempt / dispatch outbox / callback outbox

fastapi-lite Worker Service
  owns worker process / task handler / local execution idempotency

taskiq
  moves QueueEnvelope from Job Service publisher to Worker Service consumer

HTTP Worker API
  is the only authority path for Worker to change Job state
```

一句话原则：

```text
taskiq message is command copy, not state fact
```

因此新链路不是“taskiq 管 Job 生命周期”，而是：

```text
Business API
  -> tasks-platform Public Job API
  -> tasks-platform job_dispatch_outbox
  -> taskiq broker
  -> fastapi-lite taskiq consumer
  -> fastapi-lite WorkerRuntime
  -> tasks-platform Worker Internal HTTP API
  -> tasks-platform terminal projection / retry / callback / reconciler
```

## Current Baseline

`tasks-platform` 当前已经实现：

- Public Job API 和 Worker Internal API。
- `job_run -> job_node(main) -> job_attempt` 状态机。
- submit 幂等、caller binding、worker binding 和 frozen schema snapshot。
- `job_dispatch_outbox`、`job_callback_outbox`、lease、retrying、dead_letter 内部入口。
- `QueueEnvelope` 协议 DTO。
- 外部 Worker runtime 样例，按 `QueueEnvelope -> acquire -> complete/fail/cancel` 工作。
- 本地 `dispatch-once` / `worker-once` / `three-service-smoke` 验证闭环。

`tasks-platform` 当前没有实现：

- 生产级 taskiq publisher。
- 常驻 dispatch outbox dispatcher。
- 真实 broker 集成。
- 生产 Worker Service consumer。

`fastapi-lite` 当前已经实现：

- FastAPI app factory、health/readiness、request/trace id、envelope、error registry。
- section 化配置、env manifest、provider lifecycle。
- SQLAlchemy async、Alembic、UnitOfWork、repository 示例。
- shared `httpx.AsyncClient` provider，可作为 Job Service HTTP client 基础。
- `worker-taskiq` optional dependency group 预留，但为空。

`fastapi-lite` 当前没有实现：

- Worker runtime。
- taskiq consumer。
- Job Service HTTP client。
- task handler registry。
- worker 本地执行表。
- worker 启停脚本、容器入口和 readiness。

## Target Interaction

### Normal Success Path

```text
1. Business API -> tasks-platform
   POST /v1/jobs

2. tasks-platform
   validate registry / binding / idempotency
   insert job_run
   insert job_node(main)
   insert job_attempt(status=pending)
   insert job_dispatch_outbox(status=pending, payload=QueueEnvelope)

3. Job dispatcher
   lease due job_dispatch_outbox
   publish QueueEnvelope to taskiq broker
   mark dispatch published

4. fastapi-lite taskiq worker
   receive QueueEnvelope
   call WorkerRuntime.run_once(envelope)

5. WorkerRuntime
   HTTP acquire attempt from tasks-platform
   execute registered handler
   HTTP complete attempt

6. tasks-platform
   validate attempt_id + lease_token
   mark attempt/node/run succeeded
   create callback outbox
```

### Retry Path

```text
Worker handler failed retryably
  -> Worker HTTP fail(retryable=true)
  -> tasks-platform checks retry policy
  -> old attempt failed
  -> new attempt pending
  -> new dispatch outbox pending
  -> dispatcher publishes next QueueEnvelope
```

### Timeout Path

```text
Worker crashes or stops heartbeat
  -> attempt lease expires
  -> tasks-platform reconciler detects expired running attempt
  -> retry or fail according to policy
```

## Taskiq Responsibility

Taskiq is a transport adapter in this plan.

It may own:

- Publishing a `QueueEnvelope` message to the selected broker.
- Running the Worker Service task consumer.
- Worker process concurrency and task invocation.
- Broker serialization and deserialization.

It must not own:

- Job status authority.
- Task result authority through taskiq result backend.
- Retry exhaustion decision.
- Job retry policy through taskiq built-in retry.
- Attempt lease ownership.
- Callback delivery authority.
- Registry, caller binding, worker binding, or schema compatibility.
- Business side-effect idempotency.

Both services need taskiq only if taskiq is selected as the transport:

```text
tasks-platform
  taskiq dependency for publishing QueueEnvelope

fastapi-lite
  taskiq dependency for consuming QueueEnvelope
```

Both services should share only protocol-level objects:

```text
QueueEnvelope
task name constant
header names
schema hash format
error semantics
```

They must not share Worker handlers or Job Service repositories.

## Planned Work

### Phase 1 - Protocol-Aligned Worker Template

Goal: make `fastapi-lite` able to consume one `QueueEnvelope` without a real broker.

Add Worker Service modules:

```text
app/worker/protocol.py
app/worker/job_client.py
app/worker/runtime.py
app/worker/handlers.py
app/worker/execution_store.py
```

Minimum responsibilities:

- Parse `QueueEnvelope`.
- Call `tasks-platform` Worker Internal API:
  - `acquire`
  - `heartbeat`
  - `progress`
  - `complete`
  - `fail`
  - `cancel`
- Register handlers by `(task_name, task_version)`.
- Return `ack` / `no_ack` decision for future broker adapters.
- Provide a `run-once` CLI or local command that accepts a JSON message file.

No taskiq dependency is required in this phase.

### Phase 2 - Worker Local Execution Tables

Goal: avoid ambiguous outcomes when messages repeat, workers crash, or terminal HTTP calls timeout.

This phase is required before real business handlers that create local side effects, write artifacts, call external providers, or need long-running checkpoints. It should not create a mirror of Job Service state, and it can be deferred while the first chain only runs a deterministic example handler.

Add minimal worker-owned tables:

```text
worker_execution
worker_checkpoint
```

`worker_execution` records one local execution ledger per attempt:

| Field | Purpose |
| --- | --- |
| `id` | Local primary key. |
| `attempt_id` | Unique Job Service attempt id. |
| `run_id` | Job Service run id for logs and diagnostics. |
| `node_id` | Job Service node id for logs and diagnostics. |
| `task_name` | Handler dispatch key. |
| `task_version` | Handler dispatch key. |
| `queue_name` | Source queue. |
| `input_hash` | Stable hash of inline input or input_ref. |
| `status` | `received/acquired/running/succeeded/failed/cancelled/terminal_unknown`. |
| `lease_token_hash` | Diagnostic lease token hash; do not store reusable secrets when avoidable. |
| `output_ref` | Worker-produced artifact reference when available. |
| `error` | Worker-side error payload. |
| `ack_decision` | Last broker decision. |
| `created_at/started_at/finished_at/updated_at` | Recovery and audit timestamps. |

`worker_execution.attempt_id` must not become a local ownership gate. The Worker must first call Job Service `acquire`; only an acquired attempt may create or lock side-effect ledger state. A duplicate message that has not acquired the attempt must be handled by the Worker API result, not rejected by the local table first.

`worker_checkpoint` is optional for long-running handlers:

| Field | Purpose |
| --- | --- |
| `id` | Local primary key. |
| `attempt_id` | Job Service attempt id. |
| `checkpoint_key` | Handler-defined checkpoint name. |
| `payload` | Serializable checkpoint payload. |
| `created_at/updated_at` | Recovery timestamps. |

These tables are not a copy of Job Service state. They are worker-side idempotency and recovery records only.

### Phase 3 - Taskiq Consumer In fastapi-lite

Goal: use taskiq to receive `QueueEnvelope` and call `WorkerRuntime`.

Add optional dependencies under `worker-taskiq` after version validation:

```text
taskiq
taskiq-redis or selected broker plugin
taskiq-fastapi only if FastAPI integration is needed
```

Add modules:

```text
app/worker/taskiq_app.py
app/worker/taskiq_tasks.py
start-worker.sh
```

Worker task shape:

```python
@broker.task(task_name="job-platform.consume_queue_envelope")
async def consume_queue_envelope(payload: dict) -> dict:
    result = await worker_runtime.run_once(payload)
    return taskiq_adapter.apply_ack_decision(result)
```

The taskiq adapter must map `ack_decision` to broker disposition. A `no_ack` result must not be returned as a normal successful task result if that would acknowledge the broker message. The concrete implementation may raise a retry/requeue exception, call a broker-specific nack primitive, or use another tested taskiq-supported disposition path.

Taskiq task must not import `tasks-platform` ORM, repository, services, or business internals.

### Phase 4 - Taskiq Dispatcher In tasks-platform

Goal: replace local `dispatch-once` with a production dispatcher that publishes to taskiq.

Expected `tasks-platform` additions:

```text
app/runtime/dispatchers/taskiq_publisher.py
app/runtime/dispatchers/loop.py
start-dispatcher.sh or managed command
```

Dispatcher loop:

```text
lease due job_dispatch_outbox
  -> publish QueueEnvelope through taskiq
  -> mark_dispatch_published on success
  -> mark_dispatch_failed on publish error
  -> rely on reconciler for expired leases and dead_letter settlement
```

The dispatcher must publish only `QueueEnvelope`, not Python callables tied to Worker implementation.

Submit must not publish directly to taskiq. Submit writes durable intent into `job_dispatch_outbox`; a separate dispatcher publishes that intent. This keeps "job committed" and "message publish attempted" recoverable when the API process crashes between database commit and broker publish.

### Phase 5 - Local End-To-End Closure

Goal: prove the two repos can run as separate services before adding real business handlers.

Minimum local flow:

```text
tasks-platform API
  -> taskiq dispatcher
  -> broker
  -> fastapi-lite taskiq worker
  -> WorkerRuntime example handler
  -> tasks-platform Worker Internal API
  -> callback dry-run or callbacker
```

The first handler should be a deterministic example task:

```text
task_name: example.task
task_version: 1
input: object
output: {"ok": true, "worker": "..."}
```

## Configuration Plan

Add worker-focused settings in `fastapi-lite` only when implementing the worker phases:

```text
WORKER__SERVICE_NAME
WORKER__WORKER_NAME
WORKER__QUEUE_NAMES
WORKER__JOB_SERVICE_BASE_URL
WORKER__JOB_SERVICE_API_KEY
WORKER__HEARTBEAT_INTERVAL_SECONDS
WORKER__TASKIQ_BROKER_KIND
WORKER__TASKIQ_BROKER_URL
```

Follow existing config rules:

- Add typed settings section.
- Add env manifest keys.
- Update `.env.example`.
- Add config tests.
- Do not read `os.environ` directly inside worker runtime.

## Ack / No-Ack Contract

Worker runtime should preserve the `tasks-platform` ack semantics:

| Condition | Broker Decision |
| --- | --- |
| `QueueEnvelope` cannot be parsed | `ack` |
| `acquire` succeeds and terminal HTTP succeeds | `ack` |
| `ATTEMPT_NOT_ACQUIRABLE` with `safe_to_ack=true` | `ack` |
| `ATTEMPT_NOT_ACQUIRABLE` with `safe_to_ack=false` | `no_ack` |
| Schema, worker binding, or capability mismatch | `ack` |
| Terminal API returns `LEASE_INVALID` | `ack` |
| Job Service transport error | `no_ack` |
| Unclassified API error | `no_ack` |
| Handler output violates frozen output schema | call `fail(retryable=false)`, then `ack` if accepted |

This decision table belongs in tests before a production broker adapter is enabled.

The taskiq wrapper must have a tested `no_ack` path. It is not enough for `WorkerRuntime` to compute `no_ack`; the taskiq consumer must translate it into retry/redelivery behavior for the selected broker.

## Failure Modes

### Dispatch Publish Failure

If taskiq publish fails after Job Service has committed the job:

```text
dispatcher mark_dispatch_failed
  -> retrying or dead_letter
  -> reconciler settles dead_letter dispatch into attempt failure
```

### Publish Succeeds But Mark Published Fails

If taskiq accepts the message but the dispatcher crashes before `mark_dispatch_published`:

```text
dispatch outbox may be retried
same QueueEnvelope may be published again
Worker must still call acquire
Job Service lease/CAS allows at most one execution owner
```

Correctness must not depend on broker-level deduplication.

### Duplicate Broker Message

If the same `QueueEnvelope` is delivered twice:

```text
first Worker acquire wins
second Worker acquire receives not_acquirable or stale result
worker ack/no_ack follows Worker API response
```

Worker local `worker_execution.attempt_id` unique constraint protects handler side effects.

The local ledger may protect only effects after acquire. It must not decide execution ownership before Job Service does.

### Handler Succeeds But Complete Times Out

Worker cannot know if Job Service accepted the terminal write.

Required behavior:

- Record local `worker_execution` as `terminal_unknown`.
- Return `no_ack` unless the Worker API later confirms `LEASE_INVALID` or terminal status is safe to ack.
- Handler side effects must be idempotent by `attempt_id` or business output key.

Minimum recovery path:

```text
terminal HTTP result unknown
  -> no_ack
  -> broker redelivers same QueueEnvelope
  -> Worker calls acquire again
  -> Job Service returns safe-to-ack terminal/stale result, or a retryable not-acquired result
  -> Worker updates local execution ledger accordingly
```

If the selected broker cannot redeliver after `no_ack`, this plan must add an explicit `terminal_unknown` sweeper before production use.

### Worker Crash

If worker crashes while running:

```text
Job Service lease expires
reconciler retries or fails attempt
broker redelivery may occur
new Worker must pass acquire before executing
```

### Job Service Temporarily Unreachable

Worker must not treat taskiq ack as task completion when Job Service is unreachable:

```text
HTTP acquire/heartbeat/terminal transport error
  -> no_ack or equivalent retry decision
  -> no local terminal claim unless Job Service confirms it
```

### Cancel Request

Worker should check cancellation through heartbeat/progress responses:

```text
heartbeat -> cancel_requested=true
  -> stop at a safe checkpoint
  -> HTTP cancel attempt
```

Long-running handlers must define safe cancellation checkpoints.

## Verification Plan

### fastapi-lite

Before enabling taskiq:

- Unit tests for `QueueEnvelope` parsing wrapper.
- Unit tests for `JobServiceClient` request paths and error mapping.
- Unit tests for `WorkerRuntime.run_once` ack/no-ack matrix.
- Migration test for `worker_execution`.
- Migration test for `worker_checkpoint` only when long-running checkpoint support is introduced.
- Config manifest tests for worker settings.

After enabling taskiq:

- Taskiq consumer test with fake/in-memory broker if feasible.
- Integration smoke with real broker in gated test.
- A real `no_ack` adapter test proving the selected taskiq broker retries or redelivers instead of implicitly acking.
- Script smoke for worker help/start command without starting production services.

### tasks-platform

Expected verification in the Job Service repo:

- Dispatcher leases one due dispatch outbox row.
- Successful taskiq publish marks dispatch published.
- Failed taskiq publish marks retrying/dead_letter according to policy.
- Dispatcher does not publish cancelled/skipped dispatch.
- Reconciler handles expired dispatch leases and dead_letter dispatch.

### Cross-Repo Smoke

End-to-end acceptance:

```text
1. Start tasks-platform API.
2. Start taskiq broker.
3. Start tasks-platform dispatcher.
4. Start fastapi-lite worker.
5. Submit example job to tasks-platform.
6. Verify worker receives QueueEnvelope.
7. Verify Worker HTTP acquire succeeds.
8. Verify Worker HTTP complete succeeds.
9. Verify tasks-platform run becomes succeeded.
10. Verify callback outbox is created or skipped according to callback config.
11. Verify duplicate QueueEnvelope delivery has at most one acquire winner.
12. Verify a forced terminal HTTP timeout produces `no_ack` and later settles without double terminal writes.
```

## Acceptance

This plan can be moved out of active planning only when:

- `tasks-platform` has an independent dispatcher/publisher loop based on `job_dispatch_outbox`.
- `fastapi-lite` has a WorkerRuntime and taskiq consumer that do not import Job Service internals.
- Worker state changes happen only through Worker Internal HTTP API.
- `worker_execution` protects duplicate messages and ambiguous terminal outcomes.
- The taskiq adapter has a tested broker disposition mapping for both `ack` and `no_ack`.
- A local cross-repo smoke proves `submit -> dispatch -> taskiq -> worker -> complete -> terminal projection`.
- A failure-path smoke or integration test proves duplicate redelivery and terminal-result-unknown recovery do not create double terminal writes.
- Current docs are updated after implementation; this plan no longer describes shipped behavior.

## Non-Goals

- Do not make Job Service depend on Worker handler code.
- Do not let Worker write Job Service database tables.
- Do not duplicate `job_run/job_node/job_attempt/job_dispatch_outbox` in Worker Service.
- Do not treat taskiq retries as the source of Job retry policy.
- Do not add concrete business handlers before the platform chain works with `example.task`.
