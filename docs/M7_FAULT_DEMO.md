# M7.5 故障注入与技术说明

M7.5 不增加新的 Agent 能力。它把 M7.1～M7.4 的失败语义整理成一条可重复执行、可机器判定、可向面试官讲清的数据流。故障只通过测试依赖注入，生产 API 没有“让下一次请求失败”的开关。

## 运行

从 `backend` 目录执行：

```powershell
uv run python labs/m7_fault_demo.py
```

默认生成根目录的 `../output/m7-fault-demo/report.json` 和同名 Markdown。临时数据库也建在 `output` 所在磁盘，运行结束自动删除，不占系统临时目录。任一断言不满足时进程退出码为 1。

## 三个场景

| 场景 | 注入位置 | 经过的正式代码 | 必须观察到的结果 |
| --- | --- | --- | --- |
| `model_stream_failure` | 替换模型在首个可见 chunk 前抛出 `RuntimeError` | API 入场 → `RunExecutor._execute` → `astream()` → `complete_failure` | Run failed；root/model Span 均关闭并 failed；业务错误码与底层异常类型都保留 |
| `uncertain_write_recovery` | 文件已写入，但账本停在 running 后关闭并重启应用 | `ToolLedgerService.prepare/begin` → 文件服务 → lifespan 启动对账 | 工具变 uncertain、Run 变 interrupted；recover/replay 返回 409；hash 核验不增加 attempts |
| `coder_validation_failure` | Coder 提案批准后，替换 Docker 服务返回 exit 1 | diff/hash 提案 → 审批 → `CoderChangeService.resolve` | 提案 failed 并保存验证输出；父文件保持旧内容；Docker 只调用一次 |

### 为什么工具故障要模拟在 `begin` 与 `finish` 之间

账本的关键状态是：

```text
prepared → running → succeeded/failed
                 ↘ 进程退出 → uncertain
```

`running` 只能说明执行已经开始，不能证明副作用是否完成。演示先写出文件，再故意不调用 `ledger.finish()`。下一次应用启动将遗留 `running` 改为 `uncertain`。系统保留文件，让用户用服务端重新读取的 SHA-256 核验；它不会再次调用写工具，所以 attempts 仍是 1。

### 为什么模型失败同时看 Run 和 Span

Run 是产品状态，回答“本次任务结束了吗”；Span 是诊断投影，回答“哪一层失败、耗时多少”。只把 Run 写成 failed 而留下 running model Span，会让时间线永远显示执行中。反过来只关闭 Span，HTTP 查询仍无法给出可靠终态。因此 `complete_failure` 收口 Run/root Span，框架 callback 收口 model Span。

### 为什么 Coder 失败仍要经过审批

审批冻结的是 diff、父文件旧 hash、候选文件新 hash 和验证命令。批准只允许系统开始验证，并不等于候选代码已经可信。Docker exit 1 时，提案保存 failed 和验证证据，发布步骤不会开始，父工作区仍是审批前内容。

## fake 与 live 的边界

这三个场景使用确定性失败模型和失败 Docker 替身，验证的是 AgentLoom 的状态机与不变量。它们不会访问真实模型 API，也不能证明某个供应商的超时、限流或重试行为。真实模型正常路径单独运行：

```powershell
uv run python labs/live_api_smoke.py
```

当前模型适配器把 `max_retries` 交给 OpenAI/Anthropic SDK。AgentLoom 尚未实现跨 Provider 自动切换，也没有把 SDK 内部每次网络重试拆成独立 Span；演示和简历不能声称已具备这两项能力。

## 与 DeerFlow 的映射

当前 DeerFlow HEAD `5c3329afadfd8f65fd2fc3f8665069759218b704` 中，`backend/tests/test_run_manager.py::FlakyStatusRunStore` 用可替换存储稳定制造 SQLite 锁错误；`backend/packages/harness/deerflow/runtime/runs/worker.py::run_agent/_stream_once` 在流消费的 `finally` 中关闭流，并避免清理异常覆盖原始失败。

AgentLoom 保留“通过依赖替换制造故障”和“失败后必须收口资源/状态”。精简版没有复制 DeerFlow 的多 Worker 租约、完整 stream bridge、跨进程事件投递或持久化重试框架。
