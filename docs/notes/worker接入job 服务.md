可以这样理解：以后每个 Worker 服务只维护两类东西：

1. **业务 handler 代码**
2. **worker manifest 声明文件**

Job Service 不再为新增业务 task 改代码。

**整体闭环**

```text
业务 API / 调用方
  POST /v1/jobs
        |
        v
tasks-platform
  1. 查 task registry / caller binding / worker binding
  2. 写 job_run / attempt / dispatch_outbox
  3. taskiq dispatcher 发布 QueueEnvelope 到 Redis Stream
        |
        v
Redis Stream queue_name
        |
        v
Worker Service
  1. app.worker.runner 监听 TASKIQ__QUEUE_NAME
  2. acquire attempt
  3. 找 manifest 注册的 handler
  4. 执行业务逻辑
  5. complete/fail 回写 Job Service
  6. ack/no_ack broker 消息
        |
        v
tasks-platform
  job_run 变 succeeded / failed
```

**当前 fastapi-lite 这个 Worker 怎么接入**

核心代码位置：

- Worker manifest: [app/worker/manifest.json](/Users/admin/Code/fastapi-lite/app/worker/manifest.json)
- manifest 加载/校验: [app/worker/manifest.py](/Users/admin/Code/fastapi-lite/app/worker/manifest.py)
- handler registry: [app/worker/registry.py](/Users/admin/Code/fastapi-lite/app/worker/registry.py)
- 注册 CLI: [app/worker/register_cli.py](/Users/admin/Code/fastapi-lite/app/worker/register_cli.py)
- Registry API client: [app/worker/registry_client.py](/Users/admin/Code/fastapi-lite/app/worker/registry_client.py)
- Worker 消费入口: [app/worker/runner.py](/Users/admin/Code/fastapi-lite/app/worker/runner.py)
- 示例业务 handler: [app/worker/task_modules/example.py](/Users/admin/Code/fastapi-lite/app/worker/task_modules/example.py)

接入流程：

```text
1. 写 handler
2. 在 manifest.json 声明 task + handler path + schema + caller_bindings
3. 本地校验 manifest
4. 注册 manifest 到 tasks-platform
5. 启动 worker runner 消费队列
```

命令：

```bash
uv run python -m app.worker.register_cli validate
uv run python -m app.worker.register_cli render
uv run python -m app.worker.register_cli register
python -m app.worker.runner
```

关键环境变量：

```dotenv
WORKER__SERVICE_NAME=worker-x
TASKIQ__QUEUE_NAME=job.example-task.v1
WORKER__MANIFEST_PATH=app/worker/manifest.json

WORKER__JOB_SERVICE_BASE_URL=http://tasks-platform/internal/v1
WORKER__JOB_SERVICE_API_KEY=worker-runtime-token
WORKER__JOB_SERVICE_REGISTRY_API_KEY=worker-registry-token
```

`WORKER__JOB_SERVICE_API_KEY` 用于运行时 `acquire/complete/fail`。
`WORKER__JOB_SERVICE_REGISTRY_API_KEY` 只用于注册 manifest，控制面和数据面已经分开。

**怎么添加业务逻辑**

比如新增一个算法任务 `audio.stem_separate@v1`：

```python
# app/worker/task_modules/stem_separation.py

from app.worker.handlers import HandlerResult, WorkerContext
from app.worker.protocol import QueueEnvelope


class StemSeparationHandler:
    async def handle(self, envelope: QueueEnvelope, context: WorkerContext) -> HandlerResult:
        audio_url = envelope.input["audio_url"]

        # 这里写真实算法调用、模型推理、文件处理、上传结果等业务逻辑
        result_url = "s3://bucket/result.wav"

        return HandlerResult(
            output={
                "result_url": result_url,
                "worker": context.worker_name,
            }
        )
```

然后只改 manifest：

```json
{
  "task_name": "audio.stem_separate",
  "task_version": 1,
  "handler": "app.worker.task_modules.stem_separation:StemSeparationHandler",
  "input_schema": {
    "type": "object",
    "required": ["audio_url"],
    "properties": {
      "audio_url": {"type": "string"}
    }
  },
  "output_schema": {
    "type": "object",
    "required": ["result_url"],
    "properties": {
      "result_url": {"type": "string"}
    }
  },
  "timeout_seconds": 3600,
  "max_retries": 1,
  "required_worker_capabilities": ["gpu"],
  "caller_bindings": [
    {
      "caller_service": "business-api-a",
      "compensation_window_seconds": 3600
    }
  ]
}
```

不用改 `app.worker.registry.py`，也不用改 `tasks-platform` 代码。

**新 Worker 服务怎么做**

新 Worker 服务也按同样模板：

```text
new-worker-service
  app/worker/
    manifest.json
    manifest.py
    registry.py
    register_cli.py
    registry_client.py
    runner.py
    job_client.py
    runtime.py
    handlers.py
    task_modules/
      your_business.py
```

短期可以从 `fastapi-lite` 复制 Worker runtime 模板。
后续更好的方式是抽成一个 `job-platform-worker-sdk` 包，把这些通用模块沉淀进去：

```text
job-platform-worker-sdk
  manifest loader
  registry client
  job client
  runner
  handler protocol
  QueueEnvelope DTO
```

新 worker 只保留：

```text
app/worker/manifest.json
app/worker/task_modules/*.py
```

**避免冲突的规则**

- `worker_service` 必须唯一，例如 `audio-worker`、`ocr-worker`。
- `queue_name` 建议每个 worker 独立，例如 `job.audio-worker.v1`。
- 同一个 `queue_name` 只能给同一个 `worker_service` 下的多个 task 共享。
- `task_name + task_version` 全局唯一。
- schema、timeout、retry、binding 变更不要改原版本，应该升 `task_version`。

**一句话总结**

以后接业务不是“Job Service 改一遍、Worker 改一遍”，而是：

```text
Worker 写 handler
Worker 改 manifest
Worker CI/CD 调 register_cli register
Job Service 保存 registry
调用方 submit job
taskiq 投递
Worker runner 消费并执行
Job Service 管生命周期
```