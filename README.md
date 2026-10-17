# AgentLoom（织能）

AgentLoom 是一个单用户、单进程的通用 Agent Harness，也是基于当前 DeerFlow 源码边学边实现的独立项目。M0～M7 已完成：模型工具循环、持久 Run、审批恢复、受控文件与 Docker、Skill、上下文管理、隔离子 Agent、MCP、显式偏好、React 工作台、真实评测、持久化模型增量、Trace 调用树、历史证据回放、Coder 变更接纳和确定性故障演示均有可运行证据。

DeerFlow 只用于源码阅读和设计对照。AgentLoom 不导入 DeerFlow 包，也不把原仓库作为运行依赖。公开的架构、能力证据和验证结果位于 `docs/`。

## 已实现能力

- LangChain `create_agent` 组装唯一正式执行链；fake/live 明确区分。
- FastAPI 后台 Run、SQLite 业务事实、LangGraph 独立 checkpoint、可重连 SSE。
- LangGraph `astream()` 模型增量先持久化再推送，最终消息按稳定 ID 覆盖 partial 内容。
- Run/model/tool Trace Span、耗时/Token/错误码和 React 调用树时间线。
- 同线程排他、重复请求幂等、共享模型/工具/子任务硬预算。
- 文件虚拟路径、上传、hash 前置写入、不可变 Artifact、Docker Bash。
- 工具审批、持久账本、重放、uncertain 人工处置、取消资源收尾。
- Skill 快照与权限双检、大结果外置、预算触发摘要和失败保留。
- Researcher/Coder 子 Agent、并发/部分失败、私有工作区和父取消。
- 受信任本地 stdio MCP、显式偏好审批/版本冲突/请求时注入。
- React 工作台的消息、事件、审批、任务、账本、上传和安全文件预览。
- 30 个预注册真实任务与 12 Run 单/多 Agent 对照评测。

## 环境

- Windows 10/11；其他系统可运行核心 Python/前端，但 Docker 路径和脚本主要在 Windows 验证。
- Python 3.12、[uv](https://docs.astral.sh/uv/)、Node.js 22、pnpm 12。
- Docker Desktop 仅在使用 Bash 或运行 Docker 集成测试时需要。

项目的 Python 依赖安装在 `backend/.venv`。本机可把缓存放到空间充足的盘：

```powershell
$env:UV_CACHE_DIR = "D:\.uv-cache"
npx --yes pnpm@12.11.2 config set store-dir D:\.pnpm-store
```

## 安装与配置

```powershell
cd D:\Forksourcefolder\agentloom\backend
uv sync --locked
uv run alembic upgrade head

cd ..\frontend
npx --yes pnpm@12.11.2 install --frozen-lockfile
```

可提交配置是 [config.example.yaml](config.example.yaml) 和 [.env.example](.env.example)。程序在没有本机配置时使用 fake 样例；要调用真实模型，复制为被忽略的 `config.yaml`、`.env`：

```powershell
Copy-Item config.example.yaml config.yaml
Copy-Item .env.example .env
```

`config.yaml` 选择 `fake`、`openai_compatible` 或 `anthropic`，并通过 `api_key_env` / `base_url_env` 指向 `.env` 中的变量名。Secret 不写入 YAML、数据库、日志、State 或 checkpoint。

## 启动

终端一，从 `backend` 启动 API：

```powershell
uv run uvicorn agentloom.api:create_app --factory --host 127.0.0.1 --port 8000
```

终端二，从 `frontend` 启动工作台：

```powershell
npx --yes pnpm@12.11.2 dev
```

打开 `http://127.0.0.1:5173`。首次 API 启动会迁移 `.agentloom/app.sqlite`，LangGraph 使用独立的 `.agentloom/checkpoints.sqlite`。HTTP 202 表示 Run 已持久化入场，最终状态通过 REST 或 SSE 获取。

## 验证

后端离线、静态与 Docker：

```powershell
cd backend
uv run pytest -m "not live and not docker" -q
uv run pytest -m docker -q
uv run ruff check . ../scripts/verify_clean_install.py
uv run ruff format --check . ../scripts/verify_clean_install.py
uv lock --check
```

前端：

```powershell
cd frontend
npx --yes pnpm@12.11.2 check
```

M7 故障注入演示：

```powershell
cd backend
uv run python labs/m7_fault_demo.py
```

它生成 `output/m7-fault-demo/report.json` 和 Markdown 报告，验证模型流失败收口、uncertain 写操作不盲重放，以及 Coder 验证失败不修改父工作区。该命令使用确定性 fake 故障；真实模型正常路径仍由 live smoke 单独验证。

干净安装门禁会复制一个不含 `.env`、`config.yaml`、数据库、虚拟环境和 node_modules 的隔离副本，缓存及副本都在当前仓库所在盘的 `output/`：

```powershell
cd backend
uv run python ../scripts/verify_clean_install.py
```

它验证锁定安装、冷导入预热、迁移、正式 uvicorn/API 200、后端离线套件以及前端 lint/test/build。每次 fresh 运行创建 `output/clean-install/workspace-<timestamp>` 并保留现场；`--reuse` 自动选择最近副本续验。Windows 首次扫描新的 Python/Node 依赖可能需要数分钟，因此冷导入和前端安装使用独立的有界超时。

## 真实模型评测

```powershell
cd backend
uv run python -m agentloom.evaluation `
  --tasks evaluations/fixed_tasks.json `
  --expected-count 30 `
  --output ../output/evaluation/m6-live-fixed-30.json `
  --require-live

uv run python -m agentloom.evaluation `
  --tasks evaluations/comparison_tasks.json `
  --repeat 3 `
  --output ../output/evaluation/m6-live-comparison.json `
  --require-live
```

2026-10-15 的真实运行中，30 题有 25 项自动通过、3 项人工复核通过、2 项因同义措辞未命中字面规则而失败，人工复核后为 28/30。对照实验 12/12 通过；短任务中多 Agent 比单 Agent 使用更多时间和 Token。完整数据、限制与失败解释见 [M6 评测报告](docs/M6_EVALUATION.md)。

## 三个演示

1. **数据与 Artifact**：上传 CSV，模型读取、分析、等待文件写入审批，恢复后生成可下载报告。
2. **子 Agent 与 MCP**：Lead 并行委派 Researcher，child 调用只读 reference library，父层消费结构化结果。
3. **偏好与恢复**：审批保存偏好，新线程请求时注入；刷新页面从 REST/SSE 恢复同一 Run。

演示命令和 2～3 分钟讲解顺序见 [DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md)。

## 架构与代码证据

- [架构、数据流和框架边界](docs/ARCHITECTURE.md)
- [能力与代码/测试证据映射](docs/CAPABILITY_EVIDENCE.md)
- [M6 真实评测](docs/M6_EVALUATION.md)
- [M7 故障注入与技术说明](docs/M7_FAULT_DEMO.md)
- [演示流程](docs/DEMO_SCRIPT.md)

## 当前限制

- 只支持本机单用户、单 Gateway worker；没有认证、多租户、远程部署防护和配额系统。
- Bash 必须使用 Docker；Docker 不可用时拒绝执行，不回退到宿主机 shell。
- MCP 首版是配置内受信任的本地只读 stdio Server，没有远程 HTTP/OAuth 或动态市场。
- 偏好是显式审批保存，没有自动记忆抽取、向量 RAG 或跨用户记忆。
- 子 Agent 使用固定角色与工具白名单，不递归委派，Coder 文件先留在私有 task 工作区。
- 评测的字符串条件会受同义表达影响；报告保留了两个语义正确但字面失败的样本。
- 演示录屏脚本已准备，实际视频文件尚未录制。
