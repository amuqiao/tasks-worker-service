# Worker Template

本文说明当前仓库作为 Job Platform Worker 模板时的目录边界、业务 task 接入方式、注册流程和验收要求。

## 整体模型

当前模板把 Job Platform 对接层和业务层分开维护：

```text
app/job_platform_worker/
  公共对接层：manifest loader、registry client、job client、runtime、runner、taskiq broker。

app/worker/
  当前 worker 业务层：manifest.json 和 task_modules。
```

新业务通常只修改：

```text
app/worker/manifest.json
app/worker/task_modules/
```

通常不要修改：

```text
app/job_platform_worker/
```

`app/job_platform_worker/` 不是 SDK 包；它是短期可复制的公共模板层。未来如果引入 Job Platform SDK，优先替换这个目录内部实现，业务层保持稳定。

## 目录职责

| 路径 | 职责 |
|---|---|
| `app/job_platform_worker/manifest.py` | 读取和校验 `WorkerManifest`，按 handler path import 业务 handler。 |
| `app/job_platform_worker/register_cli.py` | 提供 `validate` / `render` / `register` 命令。 |
| `app/job_platform_worker/registry_client.py` | 调用 Job Service Registry API 注册 manifest。 |
| `app/job_platform_worker/job_client.py` | 调用 Job Service Worker Internal API：acquire、heartbeat、complete、fail。 |
| `app/job_platform_worker/runtime.py` | 执行 acquire -> handler -> complete/fail，并返回 ack/no_ack 决策。 |
| `app/job_platform_worker/runner.py` | 监听 Redis Stream broker，并显式 ack/no_ack。 |
| `app/job_platform_worker/handlers.py` | 定义 `TaskHandler`、`HandlerResult`、`WorkerContext`。 |
| `app/worker/manifest.json` | 当前 worker 对外声明的 task、schema、queue、caller binding。 |
| `app/worker/task_modules/` | 当前 worker 的业务 handler 和业务 service。 |

## 新增 Task

每个业务 task 使用独立子目录：

```text
app/worker/task_modules/<task_name>/
  __init__.py
  handler.py
  service.py
  schemas.py
```

推荐职责：

| 文件 | 职责 |
|---|---|
| `handler.py` | Job Platform handler 入口，只做 envelope/context 到 service 的适配。 |
| `service.py` | 业务逻辑、算法调用、对象存储读写、幂等处理。 |
| `schemas.py` | 业务输入输出模型。 |

Manifest 中的 handler path 指向 handler class：

```json
{
  "task_name": "audio.transcribe",
  "task_version": 1,
  "handler": "app.worker.task_modules.audio_transcribe.handler:AudioTranscribeHandler"
}
```

## Handler 规范

Handler 必须实现：

```python
from app.job_platform_worker.handlers import HandlerResult, WorkerContext
from app.job_platform_worker.protocol import QueueEnvelope


class AudioTranscribeHandler:
    async def handle(self, envelope: QueueEnvelope, context: WorkerContext) -> HandlerResult:
        ...
```

Handler 只负责：

```text
1. 从 envelope.input 或 envelope.input_ref 读取输入。
2. 调用当前 task 的 service。
3. 返回 HandlerResult(output=...) 或 HandlerResult(output=..., output_ref=...)。
```

复杂业务逻辑不要堆在 handler 里，放到 `service.py`。

## Manifest 规范

`app/worker/manifest.json` 是当前 worker 的正式任务声明源。新增 task 时必须添加一条 task 声明：

```json
{
  "task_name": "example.task",
  "task_version": 1,
  "handler": "app.worker.task_modules.example.handler:ExampleTaskHandler",
  "input_schema": {"type": "object", "additionalProperties": true},
  "output_schema": {"type": "object", "additionalProperties": true},
  "timeout_seconds": 300,
  "max_retries": 1,
  "retry_policy": {},
  "idempotency_retention_seconds": 86400,
  "required_worker_capabilities": ["cpu"],
  "caller_bindings": [
    {
      "caller_service": "business-api-a",
      "callback_url": null,
      "compensation_window_seconds": 3600
    }
  ]
}
```

必须保持：

```text
manifest.worker_service == WORKER__SERVICE_NAME
manifest.queue_name == TASKIQ__QUEUE_NAME
```

`register_cli validate|render|register` 和 Worker runtime 都会校验这两个条件。

同一 `task_name + task_version` 的 schema、timeout、retry、worker binding 和 caller binding 不做静默更新。需要改变合同时，优先升 `task_version`。

## Input And Output

轻量 JSON 输入使用 `input`：

```json
{
  "input": {"message": "hello"}
}
```

大文件、图片、音频、模型输入使用 `input_ref`：

```json
{
  "input_ref": {"uri": "s3://bucket/input.wav", "media_type": "audio/wav"}
}
```

轻量结果使用 `output`：

```python
return HandlerResult(output={"text": "hello"})
```

大结果使用 `output_ref`，同时返回一个小的 `output` 元数据，兼容 Job Service 的 output schema 校验：

```python
return HandlerResult(
    output={"ok": True, "result_uri": "s3://bucket/result.json"},
    output_ref={"uri": "s3://bucket/result.json", "media_type": "application/json"},
)
```

当前模板示例：

```text
app/worker/task_modules/object_ref_example/
```

## 幂等规范

有外部副作用的 task 必须设计业务幂等。常见重复场景：

```text
handler 已经写入外部结果
complete 回写 Job Service 失败
broker 消息 no_ack 后重新投递
同一 attempt 再次执行 handler
```

推荐幂等 key：

```text
<task_name>:v<task_version>:<run_id>:<attempt_id>
```

当前模板示例：

```text
app/worker/task_modules/object_ref_example/
```

示例使用 `InMemoryObjectRefExecutionStore.write_once()` 展示模式。真实业务应替换为数据库、对象存储元数据、Redis 或外部业务系统的持久幂等记录。

## 长任务规范

长任务应该按步骤执行，并在步骤边界上报 progress 和检查取消：

```python
context.raise_if_cancel_requested()
await context.report_progress(50, "halfway")
```

`context.report_progress()` 会通过 Job Service heartbeat API 上报进度并续租。如果 Job Service 返回取消标记，模板 runtime 会把当前消息收敛为 no_ack，让 Job Service 和 broker 后续处理。

当前模板示例：

```text
app/worker/task_modules/long_running_example/
```

## 注册流程

本地校验 manifest 和 handler import：

```bash
uv run python -m app.job_platform_worker.register_cli validate
```

渲染将发送给 Job Service 的 payload：

```bash
uv run python -m app.job_platform_worker.register_cli render
```

注册到 Job Service：

```bash
uv run python -m app.job_platform_worker.register_cli register
```

注册需要：

```dotenv
WORKER__JOB_SERVICE_BASE_URL=http://127.0.0.1:8100/internal/v1
WORKER__SERVICE_NAME=worker-x
WORKER__JOB_SERVICE_REGISTRY_API_KEY=dev-registry-key
WORKER__MANIFEST_PATH=app/worker/manifest.json
TASKIQ__QUEUE_NAME=job.example-task.v1
```

## 启动 Worker

容器和本地入口统一使用：

```bash
python -m app.job_platform_worker.runner
```

`start-worker.sh` 已封装该入口。

运行时需要：

```dotenv
TASKIQ__BROKER_KIND=redis_stream
TASKIQ__REDIS_URL=redis://127.0.0.1:6379/0
TASKIQ__QUEUE_NAME=job.example-task.v1
WORKER__JOB_SERVICE_BASE_URL=http://127.0.0.1:8100/internal/v1
WORKER__SERVICE_NAME=worker-x
WORKER__WORKER_NAME=worker-x-taskiq
WORKER__WORKER_SESSION_ID=worker-x-local
WORKER__JOB_SERVICE_API_KEY=dev-service-key
WORKER__MANIFEST_PATH=app/worker/manifest.json
```

`WORKER__JOB_SERVICE_API_KEY` 是 runtime token，`WORKER__JOB_SERVICE_REGISTRY_API_KEY` 是注册 token，二者不要混用。

## 验收要求

新增或修改业务 task 后至少运行：

```bash
uv run python -m app.job_platform_worker.register_cli validate
uv run pytest tests/test_worker_manifest.py
uv run pytest tests/test_worker_runtime.py
uv run pytest tests/test_worker_object_ref_example.py tests/test_worker_long_running_example.py
./scripts/verify.sh check
```

涉及 broker ack/no_ack 时运行：

```bash
FASTAPI_LITE_REDIS_STREAM_URL=redis://127.0.0.1:36379/0 ./scripts/verify.sh redis-stream
```

接入 Job Service 前，建议做一次跨服务 smoke：

```text
1. register_cli register
2. POST /v1/jobs 提交已注册 task
3. Job dispatcher 发布 dispatch outbox
4. Worker runner 消费并 complete
5. GET /v1/jobs/{run_id} 确认为 succeeded
```

## 未来 SDK 切换

如果后续引入 Job Platform SDK，优先替换：

```text
app/job_platform_worker/
```

业务层保持不变：

```text
app/worker/manifest.json
app/worker/task_modules/
```

平滑切换方式：

```text
阶段 1：当前本地公共模板层。
阶段 2：app/job_platform_worker 内部改为 import SDK client/protocol。
阶段 3：SDK 足够稳定后，再决定是否进一步删除本地薄封装。
```
