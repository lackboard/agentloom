# 能力与证据映射

简历或项目介绍只使用已经有代码、测试和演示证据的表述。下面的数字来自 2026-10-15 的本机运行，不能写成对其他模型或任务的普遍性能承诺。

| 可陈述能力 | 实现位置 | 验证证据 |
| --- | --- | --- |
| 可恢复 Agent Run 与持久事件流 | `runtime/manager.py`、`runtime/executor.py`、`runtime/events.py` | M1/M2 状态、幂等、SSE、取消和恢复测试 |
| 工具调用审批、去重和失败消费 | `agents/middleware.py`、`runtime/ledger.py` | 审批恢复、重复请求、结构化工具失败测试和 live smoke |
| 受控文件、不可变产物和 Docker Bash | `sandbox/`、`artifacts/` | 文件边界、hash 前置条件、Docker 超时/取消集成测试 |
| Skill、上下文压缩和大结果外置 | `skills/`、`agents/context.py` | 权限双检、摘要失败保留旧消息、结果分页测试 |
| 并发隔离子 Agent 与共享预算 | `subagents/`、`runtime/budget.py` | 兄弟部分失败、并发上限、父取消和 live 并行 smoke |
| MCP 与显式偏好 | `mcp/`、`memory/` | 独立 stdio 发现/调用、超时隔离、审批保存和版本冲突 |
| React 工作台和刷新恢复 | `frontend/src/` | reducer/安全预览测试、浏览器上传/审批/下载/reload 轨迹 |
| 可复现真实评测 | `evaluation/`、`evaluations/*.json` | 固定 30 题、12 Run 对照、失败和人工复核完整保留 |
| 持久增量、Trace、安全回放与证据化 Coder 接纳 | `runtime/streaming.py`、`runtime/replay.py`、`subagents/changes.py` | M7 调用树、无执行回放、Run 对比、Docker 验证/冲突/回滚测试 |
| 可重复故障演示 | `labs/m7_fault_demo.py`、`docs/M7_FAULT_DEMO.md` | 模型流失败、uncertain 写工具和 Coder 验证失败报告；任一不变量失败返回非零 |

建议项目描述：

> 独立实现单用户 Agent Harness：基于 LangChain/LangGraph 组装模型、工具、状态和中间件，加入 SQLite 持久化 Run、审批恢复、工具账本、Docker 文件沙箱、Skill、隔离子 Agent、MCP 与 React 工作台；实现持久增量、Trace 调用树、历史证据回放和 Coder diff/审批/容器验证/原子接纳，并以三类故障注入验证失败收口和副作用边界；建立 30 题真实模型评测，人工复核后完成 28/30 并保留 2 个失败。

边界说明：LangChain/LangGraph 提供图与 Agent 框架；FastAPI、SQLAlchemy、Docker、MCP SDK 和 React 提供基础设施。状态机约束、业务表、审批恢复、工具账本、权限策略、工作区映射、child 隔离、事件投影和评测器是 AgentLoom 代码。DeerFlow 是阅读参照，不是运行依赖。
