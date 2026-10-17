# AgentLoom Web

M5.3～M5.4 的 React 工作台。页面通过 REST 恢复线程、消息、Run、审批和文件，通过 SSE 追加当前 Run 的实时事件；刷新页面不会重新 `POST Run`。

```powershell
# 终端 1
cd backend
uv run uvicorn agentloom.api:create_app --factory --host 127.0.0.1 --port 8000

# 终端 2
cd frontend
pnpm install
pnpm dev
```

打开 <http://127.0.0.1:5173>。若本机尚未把 pnpm 放进 PATH，可以把前端命令写成 `npx --yes pnpm@12.11.2 <命令>`；本仓库的 pnpm store 位于 `D:\.pnpm-store`。

## 验证

```powershell
pnpm lint
pnpm test
pnpm build
```

`src/run-state.ts` 负责 `(run_id, seq)` 去重、同消息 ID 的最终覆盖和按 `task_id` 归属子任务。Markdown 不解析原始 HTML；HTML 产物只进入没有 `allow-scripts`、没有 `allow-same-origin` 的 sandbox iframe。

不依赖真实模型的完整 UI 演示可把后端启动命令改为：

```powershell
uv run uvicorn m5_ui_demo_server:app --app-dir labs --host 127.0.0.1 --port 8000
```

该演示仍使用真实 FastAPI、SQLite、LangGraph、工具账本、审批恢复、SSE 和产物服务，只把模型替换为可预测 fake。上传 CSV 后输入“分析附件并生成报告”，批准文件替换，即可下载 `report.md`。
