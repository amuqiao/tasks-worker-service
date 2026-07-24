# Worker Service Docs

本文是 `tasks-worker-service` 模板文档入口。模板使用者优先阅读 current 文档；contracts 只描述对外可依赖的 HTTP 和扩展边界。

## 模板开发入口

- [`current/worker-template.md`](current/worker-template.md)：新增业务 worker task 的主要手册。复制模板后，业务开发优先只看这篇。
- [`current/worker-runtime.md`](current/worker-runtime.md)：worker runner、attempt、ack/no_ack、heartbeat、cancel 的当前运行模型。
- [`current/implementation.md`](current/implementation.md)：仓库当前实现事实和脚本能力总览。

## 稳定合同

- [`contracts/api-contract.md`](contracts/api-contract.md)：HTTP API 合同。
- [`contracts/extension-contract.md`](contracts/extension-contract.md)：扩展仓库骨架、脚本和 provider 时的工程合同。

## 模板边界

新业务 worker task 默认只在以下位置扩展：

```text
app/worker/manifest.json
app/worker/task_modules/<business_task>/
```

通常不要修改：

```text
app/job_platform_worker/
```

`app/job_platform_worker/` 是 Job Platform 对接层；业务 task 通过 manifest 和 handler 接入，不直接改 runtime、runner、Job client 或 broker adapter。
