# 2～3 分钟演示脚本

实际录屏尚未生成；本文件固定演示步骤和要讲的证据，避免录制时临时改变口径。

## 0:00～0:25 启动与边界

1. 后端执行 `uv run uvicorn agentloom.api:create_app --factory --host 127.0.0.1 --port 8000`。
2. 前端执行 `npx --yes pnpm@12.11.2 dev`，打开 `http://127.0.0.1:5173`。
3. 说明 app.sqlite 保存业务事实，checkpoints.sqlite 保存图恢复状态；页面断线不拥有后台 Run。

## 0:25～1:15 数据与审批

1. 上传一个两列 CSV，要求“计算总计，生成 `report.md` 并展示”。
2. 指出模型先得到服务端冻结的附件虚拟路径，文件读取进入工具账本。
3. 写文件调用暂停在 `waiting_input`，展示冻结参数与 hash；批准后恢复同一个 Run。
4. 打开 Artifact 预览并下载，刷新页面，说明 REST 恢复同一消息和账本，没有重新提交。

可预测离线版本：`cd backend; uv run python labs/m5_ui_demo_server.py`。真实模型版本使用普通 API 启动命令和本机 live 配置。

## 1:15～2:05 子 Agent、MCP 与偏好

1. 请求两个 Researcher 分别计算和查询 reference library。
2. 展示两个 child 卡片、父层唯一 `task` ToolMessage、MCP 来源 URI。
3. 请求保存一条偏好，展示审批后才进入 memories；新线程观察偏好注入。
4. 说明 child 没有 `task` 和 Bash 权限，不能递归委派或触发嵌套审批。

命令证据：`uv run python labs/live_subagent_parallel_smoke.py`、`uv run python labs/live_mcp_memory_smoke.py`。

## 2:05～2:45 评测与失败

1. 打开 `docs/M6_EVALUATION.md`：30 题人工复核后 28/30。
2. 展示两条语义正确但字面规则失败，说明没有删失败样本或事后改答案。
3. 展示修复前真实内容块被投影为空、修复后同三题 3/3 的回归。
4. 展示单/多 Agent 对照：短任务完成率相同，委派增加延迟和 Token，因此按任务复杂度选择。

录制时应隐藏 `.env`、`config.yaml`、请求头和供应商控制台。视频文件不进入 Git；如需公开，可在 README 中加入发布地址和录制日期。

## M7 故障与证据演示（额外 2 分钟）

先执行 `cd backend; uv run python labs/m7_fault_demo.py`，打开根目录的 `output/m7-fault-demo/report.md`：

1. 展示模型流异常后 Run 与 model/root Span 全部 failed 且已关闭。
2. 展示写文件后的进程退出被恢复为 uncertain，recover/replay 被阻止，hash 核验后 attempts 仍为 1。
3. 展示 Coder Docker exit 1 后提案 failed，而父文件没有接纳候选内容。

演示时明确说明这是 deterministic fake 故障注入；真实模型正常路径使用 `uv run python labs/live_api_smoke.py` 单独证明。
