# AgentLoom backend

当前后端按 `api / runtime / agents / models / tools / sandbox / artifacts / persistence` 分层。HTTP 提交先持久化
`pending` Run，再由应用生命周期持有的后台任务执行；文件工具使用每线程虚拟工作目录，展示文件先捕获为不可变产物快照。

## 安装与离线检查

```powershell
uv sync --locked
uv run alembic upgrade head
uv run python labs/04_m1_demo.py
uv run python labs/m2_approval_demo.py
uv run python labs/m2_csv_demo.py
uv run python labs/m3_skills_demo.py
uv run python labs/m3_context_demo.py
uv run python labs/m7_fault_demo.py
uv run pytest -m "not live and not docker"
uv run ruff check .
uv run ruff format --check .
```

## 配置真实模型

项目根目录有两组文件：

- `config.example.yaml`、`.env.example`：可提交的完整样例。
- `config.yaml`、`.env`：本机文件，已被根 `.gitignore` 忽略。

`config.yaml` 支持原生 `anthropic` 和 `openai_compatible`。Anthropic 配置示例：

```dotenv
ANTHROPIC_API_KEY=你的密钥
ANTHROPIC_BASE_URL=
```

Anthropic 官方接口的 `ANTHROPIC_BASE_URL` 留空；只有代理服务才填写地址。若要切换 OpenAI 或兼容接口，使用
`provider: openai_compatible`，并把环境变量名改回 `MODEL_API_KEY` 和 `MODEL_BASE_URL`。配置检查和真实工具调用：

使用 OpenAI 或兼容服务时，将 provider 改为 `openai_compatible`，并在 `.env` 中设置
`MODEL_API_KEY` 与可选的 `MODEL_BASE_URL`。本机实际选择以被忽略的 `config.yaml` 为准。

```powershell
uv run python labs/live_model_smoke.py
uv run python labs/live_api_smoke.py
uv run python labs/live_files_smoke.py
uv run python labs/live_approval_smoke.py
uv run python labs/live_failure_smoke.py
uv run python labs/live_cancel_smoke.py
uv run python labs/live_subagent_smoke.py
uv run python labs/live_subagent_parallel_smoke.py
uv run python labs/live_mcp_memory_smoke.py
```

这些 live 脚本只有在 `config.yaml` 选择真实 provider 且 `.env` 中有密钥时才发出请求。模型 smoke 检查中文工具调用、
usage 和模型流；API smoke 通过临时数据库检查 worker、重复请求与持久化事件；文件 smoke 让真实模型写入并登记一个
临时产物；审批 smoke 让模型读取旧 hash、请求覆盖、等待批准并恢复同一 Run；失败 smoke 验证模型消费明确工具错误；
取消 smoke 组合真实模型、审批和真实 Docker，并检查容器与账本收尾。缺少密钥或 Docker 返回 `NOT_RUN`；服务商错误
返回 `FAIL`，不会降级成 fake。

M5 smoke 会从独立 stdio 进程发现并调用 `reference_library`，再让真实模型提出一条偏好保存、等待用户审批并验证
新线程收到该偏好。`config.yaml` 的 `mcp.enabled` 必须为 `true`。

## 启动 API

```powershell
uv run uvicorn agentloom.api:create_app --factory --host 127.0.0.1 --port 8000
```

默认业务库为项目根 `.agentloom/app.sqlite`，LangGraph checkpoint 库为
`.agentloom/checkpoints.sqlite`。两者职责不同，不能合并。

当前 Run 接口：

- `GET /api/threads`、`GET /api/threads/{thread_id}`：恢复线程列表、最新 Run 和 Todo 投影。
- `POST /api/threads/{thread_id}/runs`：202 入场，后台继续执行。
- `GET /api/runs/{run_id}`：查询状态与 usage。
- `GET /api/runs/{run_id}/events?after_seq=N`：SSE 回放；也支持 `Last-Event-ID`。
- `POST /api/runs/{run_id}/cancel`：幂等请求取消。
- `GET /api/runs/{run_id}/tool-executions`：读取工具账本和实际尝试次数。
- `GET /api/runs/{run_id}/approvals`：读取持久化审批卡。
- `POST /api/approvals/{approval_id}/resolve`：批准或拒绝并恢复同一 Run；不接受修改工具参数。
- `POST /api/tool-executions/{execution_id}/resolve`：对 uncertain 工具选择 `skip`，或提交已声明文件的 SHA-256 做 `verify`。
- `POST /api/runs/{run_id}/recover`：所有 uncertain 项处理后，从原 checkpoint 恢复 interrupted Run。
- `POST /api/threads/{thread_id}/uploads`：上传并登记线程只读文件。
- `GET /api/threads/{thread_id}/artifacts`：列出右侧文件面板所需的上传与输出快照。
- `GET /api/runs/{run_id}/subagents`：恢复当前 Run 的子任务卡片。
- `POST /api/runs/{run_id}/replays`：冻结终态 Run 的历史消息、事件和工具结果证据；不会重跑模型或工具。
- `GET /api/run-comparisons?left_run_id=...&right_run_id=...`：比较两个 Run 的用量、耗时、工具、Span 和产物 hash。
- `POST /api/subagents/{task_id}/change-proposals`：为成功 Coder 子任务生成服务端 diff/hash 审批；批准后先做 Docker 验证，再接纳父工作区。
- `GET /api/artifacts/{artifact_id}`：读取产物元数据，不返回宿主机路径。
- `GET /api/artifacts/{artifact_id}/content`：校验 SHA-256 后下载快照。
- `GET /api/tools`：列出内置/MCP 工具及 MCP Server 的有限诊断信息。
- `GET/POST /api/memories`：读取有效偏好，或由用户明确创建偏好。
- `PATCH/DELETE /api/memories/{memory_id}`：按 `expected_version` 更新或软删除，过期版本返回 409。

关闭 SSE 连接不会取消 Run。只有显式 cancel 请求或应用关闭才会触发执行任务收尾。

## M2 Docker 与 CSV 演示

Bash 只在 Docker 中执行。后端不会在 Docker 缺失时回退到宿主机 shell。先构建固定镜像：

```powershell
docker build -t agentloom-python:v1 -f docker/Dockerfile docker
uv run pytest -m docker
uv run python labs/m2_csv_demo.py
```

每条命令使用一个非 root、无网络、只读根文件系统的容器；只挂载当前线程的 `workspace`、`outputs`，以及只读的
`uploads`、`tool-results`。取消 Run 会先强制删除已登记容器，再用失败 ToolMessage 补齐尚未响应的调用。

## M6 评测

评测器走正式 HTTP、后台 Run、审批、账本和 Artifact 查询链，不直接调用模型绕过应用。先用 `--ids` 冒烟，再运行完整任务：

```powershell
uv run python -m agentloom.evaluation `
  --tasks evaluations/fixed_tasks.json `
  --expected-count 30 `
  --ids FC-01,RT-01,AG-01 `
  --output ../output/evaluation/smoke.json `
  --require-live

uv run python -m agentloom.evaluation `
  --tasks evaluations/fixed_tasks.json `
  --expected-count 30 `
  --output ../output/evaluation/fixed-30.json `
  --require-live
```

`--require-live` 会在 provider 为 fake 时返回 NOT_RUN，防止把离线模型冒充真实评测。JSON 保存逐题观察和失败；Markdown 保存摘要。对照任务用 `evaluations/comparison_tasks.json --repeat 3`。已运行结果见根目录 `docs/M6_EVALUATION.md`。

## M7 故障演示

`uv run python labs/m7_fault_demo.py` 通过替换模型/Docker 依赖和模拟工具账本崩溃窗口，检查模型失败 Trace 收口、uncertain 写操作不盲重放、Coder 验证失败不修改父目录。报告写入根目录 `output/m7-fault-demo/`，任一不变量失败时返回非零。它明确属于 fake 故障注入；`labs/live_api_smoke.py` 另行验证真实模型正常路径。
