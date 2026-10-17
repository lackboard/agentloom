# AgentLoom 开发进度

更新日期：2026-10-15。此文件分别记录实现、验证与学习进度；设计文档描述目标能力。

## 实现与参考目录

- 用户确认：在新目录实现 AgentLoom，当前 DeerFlow 作为源码学习参照。
- 实现根目录：`D:\Forksourcefolder\agentloom`，2026-10-06 核对；交接包已从误嵌套的 `agentloom\` 移至此根目录。
- 参考根目录：`D:\Forksourcefolder\deer-flow`。
- 参考 HEAD：`5c3329afadfd8f65fd2fc3f8665069759218b704`，于 2026-10-15 再次核对；M6 读取 `test_thread_state_reducers.py` 的 reducer/字段接线不变量测试与 `test_run_manager.py` 的故障注入、租约丢失、取消和清理测试。参考仓库另有与本单元无关的未跟踪交接材料。
- M0.0 已完成源码导读；M0.1～M0.5、M1.1～M1.5、M2.1～M2.6、M3.1～M3.4、M4.1～M4.4、M5.1～M5.4 与 M6.1～M6.4 已交付。

## 当前状态

- 项目阶段：M6 IMPLEMENTED；M6-01～04 的代码与技术验收已完成。用户对 M6 的实验与复述仍待反馈。
- 已有内容：M0～M5 的正式执行链、隔离能力与工作台；M6 增加预注册任务契约、正式 API 评测运行器、确定性评分/报告、30 题 live 评测、12 Run 单/多 Agent 对照、干净安装门禁、架构/能力证据和演示脚本。
- 当前范围外：父 Agent 自动接纳 Coder 文件并执行建议、远程 MCP/OAuth、自动记忆抽取、多租户与通用 RAG。演示录屏脚本已完成，实际视频文件尚未录制，记为 NOT_RECORDED。
- 可提交样例默认 fake；本机 `config.yaml` 为 `openai_compatible` / `gpt-5.6-sol` 且启用 MCP。30 题真实评测人工复核后 28/30；两个失败为同义回答没有命中预注册字面条件，原样保留。密钥值和原始评测输出未提交。
- 下一步：留给用户运行一个评测子集、阅读关键代码、回答 M6 理解问题或录制演示；不自动扩展产品范围。

## 里程碑

| 阶段 | 代码状态 | 离线验证 | 环境/真实运行验证 | 证据 |
| --- | --- | --- | --- | --- |
| M0 | IMPLEMENTED（离线范围） | PASS：当前正式链覆盖 M0-01～04；M0-05 为 2026-10-06 历史组合 smoke，M5 已重新锁定并实接 MCP，但旧四合一脚本未恢复 | PASS：M0-LIVE，真实中文 `add` 闭环、usage 与模型增量流 | 2026-10-11 验收审查与历史 M0.4 记录 |
| M1 | IMPLEMENTED（M1.1～M1.5） | PASS：M1-01～06，18 个离线测试 | PASS：真实 API worker 单任务、usage、工具事件和重复请求；NOT_RUN：真实长任务的断线/取消 | 2026-10-11 验收审查 |
| M2 | IMPLEMENTED（M2.1～M2.6） | PASS：M2-01～07；33 个离线测试 | PASS：真实模型及覆盖审批回归；M2-DOCKER 3 项真实容器测试；CSV 容器演示 | M2.1～M2.6 与 2026-10-13 Docker 补验记录 |
| M3 | IMPLEMENTED（M3.1～M3.4） | PASS：M3-01～05；43 个离线测试 | PASS：真实模型兼容/失败/取消回归；上下文边界使用确定性模型；Docker 3 项 PASS | 2026-10-13 单元记录与 2026-10-14 验收审查 |
| M4 | IMPLEMENTED（M4.1～M4.4） | PASS：7 个 M4 确定性测试；全套 50 passed/3 deselected；M4-01～05 PASS | PASS：真实 `gpt-5.6-sol` 双 Researcher 委派，两个 child 工具结果被 Lead 消费；精确取消/重启时点由确定性测试验证 | 2026-10-14 M4.1～M4.4 记录 |
| M5 | IMPLEMENTED（M5.1～M5.4） | PASS：M5-01～05；后端 55 passed/3 skipped，前端 5 passed、lint/build PASS | PASS：真实 `gpt-5.6-sol` API 回归；浏览器完整 UI 使用 fake 模型且真实执行后端链 | 2026-10-14～15 M5 记录 |
| M6 | IMPLEMENTED（M6.1～M6.4） | PASS：评测契约/评分 5 项测试；后端 63 passed；前端 5 passed、lint/build；干净副本 60 passed/3 deselected + API 200 | PASS：真实 30 题保留 25 pass/3 manual/2 fail，人工复核后 28/30；12 Run 对照 12/12；Docker 3 项 PASS | `docs/M6_EVALUATION.md`、干净安装门禁与本节记录 |

代码状态使用 NOT_STARTED / IN_PROGRESS / IMPLEMENTED。验证分别用 PASS / FAIL / NOT_RUN；只有阶段要求的验证完成才写“技术验收完成”。学习状态单独记录。缺少外部环境时可推进当前授权范围内的独立任务，未验项持续保留。

## 当前学习单元

| 单元 | 交付状态 | 用户理解状态 | 原源码 / 验证 / 反馈 |
| --- | --- | --- | --- |
| M0.0 原仓库导读 | DELIVERED | NEEDS_REVIEW | 用户反馈上一轮未理解；M0.1 开始时已用“模型请求工具不等于执行工具”的例子补讲，效果待反馈 |
| M0.1 最小 CLI | DELIVERED | AWAITING_FEEDBACK | Python 3.12.11；fake CLI 可观察 mode/model/input/output；2 个离线测试与 ruff 通过 |
| M0.2 工具循环 | DELIVERED | AWAITING_FEEDBACK | StateGraph 实际执行 add/lookup_note；tool_call_id 配对；M0-01/02 PASS |
| M0.3 失败/停止 | DELIVERED | AWAITING_FEEDBACK | M0-03/04 PASS；错误参数修正、未知工具反馈、重复调用上限均有测试与 CLI 轨迹 |
| M0.4 SDK 预检 | DELIVERED | AWAITING_FEEDBACK | M0-05 PASS；锁定版本下四项离线 smoke 运行成功 |
| M0.5 可选 live | DELIVERED（脚本） | AWAITING_FEEDBACK | M0-LIVE PASS；`openai_compatible` / `gpt-5.6-sol` 调用 `add` 得到 5 并生成最终答案 |
| M1.1 正式 Agent | DELIVERED | AWAITING_FEEDBACK | `create_agent` 经真实工具节点返回 5；磁盘 checkpoint 同线程恢复读到第二次结果 |
| M1.2 数据库/Thread/Run | DELIVERED | AWAITING_FEEDBACK | M1-01 PASS；九表迁移与 schema.sql 对照，二次升级保留数据；app/checkpoints 分库 |
| M1.3 提交/排他/幂等 | DELIVERED | AWAITING_FEEDBACK | M1-02/03 PASS；HTTP 202/409、并发提交、重启后重复提交均通过 |
| M1.4 SSE/断线 | DELIVERED | AWAITING_FEEDBACK | M1-04 PASS；后台任务不属于 SSE，按 seq/Last-Event-ID 从 run_events 补齐且不重复执行 |
| M1.5 取消/计量 | DELIVERED | AWAITING_FEEDBACK | M1-05/06 PASS；取消/完成 CAS 只胜出一次，fake usage 与失败终态有持久化事件 |
| M2.1 工作目录/文件 | DELIVERED | AWAITING_FEEDBACK | M2-01 PASS；虚拟路径、线程隔离、遍历/绝对路径/链接逃逸拒绝，用户实验待反馈 |
| M2.2 产物登记 | DELIVERED | AWAITING_FEEDBACK | M2-07 PASS；上传、outputs 快照、归属/完整性校验与下载，用户实验待反馈 |
| M2.3 工具账本 | DELIVERED | AWAITING_FEEDBACK | 逻辑调用唯一键、参数冲突、结果重放、实际 attempts 与启动时 running→uncertain 已验证；人工处置留 M2.5 |
| M2.4 审批恢复 | DELIVERED | AWAITING_FEEDBACK | M2-03/04 PASS；整批暂停、重启恢复、答复幂等/冲突、拒绝配对与旧 hash 失效已验证 |
| M2.5 Docker/取消恢复 | DELIVERED | AWAITING_FEEDBACK | Docker-only Bash、资源限制/清理、uncertain verify/skip、取消配对已实现；M2-02/05/06 离线 PASS，3 项真实 Docker 测试 PASS |
| M2.6 CSV 演示 | DELIVERED | AWAITING_FEEDBACK | 上传→脚本→审批→Docker→present_files 真实演示 PASS；PNG 与 Markdown 下载内容已校验 |
| M3.1 Skill 解析/发现 | DELIVERED | AWAITING_FEEDBACK | UTF-8/YAML 解析、元数据 API、三个内置 Skill；正文初始不可见，M3-01 PASS |
| M3.2 按需加载/权限 | DELIVERED | AWAITING_FEEDBACK | `load_skill`、`/skill-name`、冻结快照、schema 过滤与执行点拒绝；M3-02/03 PASS |
| M3.3 大输出外置 | DELIVERED | AWAITING_FEEDBACK | 完整结果写入只读 `tool-results`，模型只收有界预览、hash、引用和分页读取提示；M3-04 PASS |
| M3.4 摘要/消息组 | DELIVERED | AWAITING_FEEDBACK | 预算触发、当前任务与最近两组完整工具消息保留、失败不删消息、UI 历史归档和共享调用预算；M3-04/05 PASS |
| M4.1 子任务契约/隔离 | DELIVERED | AWAITING_FEEDBACK | Researcher/Coder 固定白名单、独立消息/State、输入文件快照、Coder 私有目录、child schema 无 `task`/Bash；用户实验待反馈 |
| M4.2 单子任务 | DELIVERED | AWAITING_FEEDBACK | `task` → child graph → 结构化结果 → Lead，子任务状态/事件持久化；离线成功/失败和真实模型成功均 PASS |
| M4.3 并发/部分失败 | DELIVERED | AWAITING_FEEDBACK | 每 Run 最多 4 个、全进程同时 2 个；一个 child 失败不取消兄弟，递归委派与第 5 个任务被拒绝；真实双 Researcher PASS |
| M4.4 取消/共享预算 | DELIVERED | AWAITING_FEEDBACK | 父取消收尾全部 child；重启将活动 child 标为 interrupted，完成结果可复用；Lead/child/摘要共享模型与工具硬预算 |
| M5.1 本地 MCP | DELIVERED | AWAITING_FEEDBACK | 独立 stdio 进程、真实 tools/list/call、来源前缀、启动失败/调用超时隔离与 lifespan 清理；M5-01/02 PASS |
| M5.2 显式偏好 | DELIVERED | AWAITING_FEEDBACK | `remember_preference` 审批、active 偏好请求时注入、CRUD 与乐观版本冲突；M5-03 PASS |
| M5.3 消息/事件页面 | DELIVERED | AWAITING_FEEDBACK | React 三栏工作台、REST 刷新恢复、SSE `(run_id,seq)` 去重、最终消息覆盖增量、Run/usage/轨迹；M5-04 PASS |
| M5.4 审批/任务/文件 | DELIVERED | AWAITING_FEEDBACK | 审批恢复、Todo/子任务/工具账本、附件注入、产物下载、安全 Markdown/隔离 HTML；M5-05/M5-UI PASS |
| M6.1 固定任务与验收 | DELIVERED | AWAITING_FEEDBACK | 30 个预注册任务，分布 10/8/6/6；任务 ID/数量/重复和评分契约有确定性测试 |
| M6.2 完整真实评测 | DELIVERED | AWAITING_FEEDBACK | `gpt-5.6-sol` 30 题真实 Run：25 自动通过、3 人工复核通过、2 字面条件失败；失败未删除或改分 |
| M6.3 对照与归因 | DELIVERED | AWAITING_FEEDBACK | 单/多 Agent 各 6 Run，均 100%；单 8.40±1.64s/1798±74 Token，多 15.53±5.15s/2898±201 Token |
| M6.4 交付与讲解 | DELIVERED | AWAITING_FEEDBACK | README、架构/能力证据/评测/演示脚本、干净安装 PASS；实际演示视频 NOT_RECORDED |

交付状态用 NOT_STARTED / IN_PROGRESS / DELIVERED；纯导读交付不等于写了代码。用户理解状态用 NOT_STARTED / AWAITING_FEEDBACK / NEEDS_REVIEW / VERIFIED。VERIFIED 需要实际复述、实验或定位问题的反馈，不依据 Codex 自己的答案判断。

每个单元结束填写：

```text
单元与范围：
参考源码路径 / 符号 / HEAD：
原版解决的问题：
精简版对应文件、保留/简化内容与理由：
已实现 / 已验证 / 未验证：
用户的预测、实验、复述反馈：（未收到就写待反馈）
仍不理解的概念：
下一步：继续当前单元答疑，或用户安排的下一单元
```

## M0.0 阅读记录

- 单元与范围：只读当前 DeerFlow 的 Agent 组装入口与线程 State；对应学习验收 L-01、L-05。L-02 对纯导读不适用，L-03/L-04 待用户反馈。
- 参考源码路径 / 符号 / HEAD：`D:\Forksourcefolder\deer-flow\backend\packages\harness\deerflow\agents\factory.py`：`create_deerflow_agent`（67–197 行，最终 `create_agent` 在 189–197 行）；`D:\Forksourcefolder\deer-flow\backend\packages\harness\deerflow\agents\thread_state.py`：`ThreadState`（352–369 行）、`merge_artifacts`（93–100 行）、`merge_todos`（120–130 行）。HEAD `5c3329afadfd8f65fd2fc3f8665069759218b704`；目标文件无本地 diff。
- 原版解决的问题：把调用者提供的模型、工具、提示词与可选持久化交给框架；按功能选择中间件并补充工具；以 `ThreadState` 扩展消息状态，定义不同字段的更新规则。此函数内没有手写完整的模型—工具循环。
- 精简版取舍：M0.1 先建最小 fake CLI；M0.2 用手动 StateGraph 展示模型、工具与状态的流转；M1 正式组装再用简单 factory / `create_agent`。保留消息、少量工具与必要 State；暂不做 feature 自动组合、delta checkpoint、子 Agent、完整中间件链与数据库。
- 已实现 / 已验证 / 未验证：本轮仅完成源码定位、导读与文档归位；没有 AgentLoom 应用代码，未运行模型或测试，M0～M6 的验证状态保持 NOT_RUN。
- 用户的预测、实验、复述反馈：待反馈。阅读练习：比较 `merge_artifacts` 与 `merge_todos` 对新列表的处理，并口述一次工具结果回到 State 后由谁决定下一步。
- 仍不理解的概念：待用户指出；本轮只解释函数输入输出、`*` 关键字参数、`Annotated` 合并规则。
- 下一步：先收 M0.0 问题反馈；用户安排后进入 M0.1。
## M0.1 实现与学习记录

- 单元与范围：建立 `backend` 的 Python/uv/pytest 基础目录，实现只调用一次 fake 模型的最小 CLI；不实现工具、State 或循环。
- 与原版对应：保留 `create_deerflow_agent` 参数中的“模型对象接受输入并产生输出”这一最小切片；尚未调用 DeerFlow 使用的 LangChain `create_agent`。
- 精简版文件：`backend/src/agentloom/fake_model.py` 定义 `FakeChatModel.invoke` 的输入输出；`backend/src/agentloom/cli.py` 负责解析和展示；`backend/pyproject.toml` 固定 Python 3.12 与开发工具，`uv.lock` 锁定环境。
- 已实现 / 已验证：uv 使用 CPython 3.12.11；CLI 明确输出 `fake (offline)` 和 `tool_loop: not implemented (planned for M0.2)`；2 个 pytest 测试、ruff lint、ruff format check 通过。
- 修复记录：首次 CLI 子进程测试因 Windows 系统代码页与 UTF-8 解码不一致失败；CLI 标准输出固定为 UTF-8 后复验通过。
- 未验证：M0-01/M0-02 要求的模型 tool call、实际工具执行、ToolMessage 回传和最终回答均未实现；live 模型 NOT_RUN。
- 用户的预测、实验、复述反馈：待反馈。建议实验为更换 `--message` 的值，预测 `input` 和 `output` 哪部分改变，再运行命令观察。
- 后续学习反馈：用户询问了 uv、`pyproject.toml`、`.venv`、缓存位置、Python 安装位置与锁文件的作用，已结合本机实际路径讲解；尚未收到 CLI 实验结果或数据流复述。
- 仍不理解的概念：M0.0 各部件角色的补讲效果待反馈；M0.1 可重点复述 CLI、模型对象、回复对象三者的输入输出。
- 下一步：留给用户运行、实验和提问；只有用户安排后才进入 M0.2。

### M0.1 复验记录（2026-10-05）

- `uv sync --locked`：退出码 0；解析并核对 8 个包。
- `uv run python -m agentloom --mode fake --message "复验 M0.1 输入输出"`：退出码 0；正确展示 mode、model、input、output，并声明工具循环尚未实现。
- `uv run pytest -m "not live and not docker"`：退出码 0；2 passed。
- `uv run ruff check .`：退出码 0；All checks passed。
- `uv run ruff format --check .`：退出码 0；6 files already formatted。
## M0.2 实现与学习记录

- 单元与范围：实现 fake 模型提出工具调用、应用执行工具、ToolMessage 写回 State、模型读取结果后结束的完整离线闭环；对应 M0-01、M0-02。
- 参考源码路径 / 符号 / HEAD：`D:\Forksourcefolder\deer-flow\backend\packages\harness\deerflow\tools\tools.py`：`BUILTIN_TOOLS`（35–39 行）、`get_available_tools`（105–348 行）；HEAD `5c3329afadfd8f65fd2fc3f8665069759218b704`，目标文件无本地 diff。
- 原版解决的问题：从配置、内置、MCP、ACP 与插件来源汇集工具，按授权/功能过滤并按名称去重，再将工具集合交给 Agent。完整模型工具循环由 `create_agent` 生成的框架图负责，不是在 `get_available_tools` 中手写。
- 精简映射：`get_demo_tools` 只返回 `add` 和 `lookup_note` 两个静态无副作用工具；`build_tool_loop` 用教学用 StateGraph 显式展开 model 节点、tools 节点、条件边和消息 reducer；不移植配置发现、MCP、插件、权限、中间件、checkpoint 或正式 ToolRegistry。
- 实际依赖：锁定 LangGraph 1.2.12、LangChain Core 1.6.6；Python 3.12.11。
- 已实现 / 已验证：CLI 标记 `fake (offline)`；真实图产生 tool call、实际执行工具、写回同一 `tool_call_id` 的 ToolMessage，再由 fake 模型读取结果生成最终答案。M0-01 PASS。注入不同笔记数据会改变 ToolMessage 与最终答案，M0-02 PASS。
- 成功轨迹：输入 `请计算 2 + 8` → `add(a=2,b=8,id=call-1)` → ToolMessage `content=10, tool_call_id=call-1` → 最终答案 10。
- 负向轨迹：输入 `读取笔记：不存在` → `lookup_note(topic=不存在,id=call-1)` → ToolMessage 返回“未找到主题”的正常业务结果 → 模型如实输出未找到。错误参数、未知工具和无限循环尚未处理，留到 M0.3。
- 验证命令：`uv run pytest -m "not live and not docker"`（退出码 0，5 passed）；`uv run ruff check .`（退出码 0）；`uv run ruff format --check .`（退出码 0，9 files already formatted）；`uv lock --check`（退出码 0，46 packages）。live 模型 NOT_RUN。
- 用户的预测、实验、复述反馈：待反馈；尚不能写 VERIFIED。建议将输入从 `2 + 3` 改为 `2 + 8`，运行前预测 ToolMessage 和最终答案，再定位相同的 `tool_call_id`。
- 下一步：留给用户运行、回答和提问；只有用户安排后才进入 M0.3。
## M0.3～M0.5 实现与学习记录（2026-10-06）

- 单元与范围：M0.3 在既有教学图中处理错误参数、未知工具和持续调用；M0.4 只检查锁定 SDK 的四种能力；M0.5 提供显式启用的真实模型 smoke。没有启动 M1 后端。
- 参考源码路径 / 符号 / HEAD：`D:\Forksourcefolder\deer-flow\backend\packages\harness\deerflow\agents\middlewares\tool_error_handling_middleware.py`：`ToolErrorHandlingMiddleware`、`_build_error_message`；`agents/middlewares/loop_detection_middleware.py`：`LoopDetectionMiddleware`；`agents/factory.py`：`create_deerflow_agent` 与最终 `create_agent`；`mcp/tools.py`：`get_mcp_tools`；`models/factory.py`：`create_chat_model`。HEAD `5c3329afadfd8f65fd2fc3f8665069759218b704`，目标源码无本地 diff。
- 原版解决的问题：工具失败转为同 ID 的错误 ToolMessage；通过循环检测中间件对重复调用告警/终止；factory 按配置组装模型、工具、中间件并交给 `create_agent`；MCP 和模型工厂分别负责外部工具/真实模型接入。
- 精简映射：`backend/src/agentloom/tool_loop.py` 在教学图的工具节点将参数校验失败、未知工具变为 `status=error` 的 ToolMessage，并用 `max_tool_calls=3` 限制实际调用次数；预算外请求也生成同 ID 的拒绝消息，随后停止。`backend/src/agentloom/fake_model.py` 用固定输入触发纠错、未知工具和重复调用。未移植原版复杂指纹、配置发现和生产中间件链。`backend/labs/02_sdk_smoke.py` 独立预检 SDK；`backend/labs/03_live_smoke.py` 仅在明确开启且配置齐全时请求提供商。
- 实现完成：M0-03/04 的代码和测试；M0-05 的离线 smoke、锁定依赖；M0-LIVE 的可选脚本和配置示例。正式执行链仍留 M1。
- 测试通过：`uv sync --locked`（退出码 0，75 packages）；`uv run pytest -m "not live and not docker"`（退出码 0，8 passed）；`uv run ruff check .`（退出码 0）；`uv run ruff format --check .`（退出码 0，12 files already formatted）；`uv lock --check`（退出码 0，75 packages）；`uv run python labs/02_sdk_smoke.py`（退出码 0，create_agent、async SQLite checkpoint、中断/同线程恢复、本地 stdio MCP echo 均 PASS）。锁定版本包括 LangChain 1.4.3、LangGraph 1.2.12、langchain-mcp-adapters 0.3.2、langgraph-checkpoint-sqlite 3.1.1、langchain-openai 1.6.7。
- 实际成功/失败轨迹：`uv run python -m agentloom --mode fake --message "错误参数"`（退出码 0，`call-1` 参数缺 `b` → error ToolMessage → `call-2` 修正为 `add(2,3)` → success ToolMessage `5` → 最终答案 `5`）；`--message "未知工具"`（退出码 0，`missing_tool` → error ToolMessage `call-1` → 有界结束）；`--message "重复调用"`（退出码 0，`call-1`～`call-3` 实际执行，`call-4` 返回预算拒绝消息，`stop_reason=tool_call_budget`）。受控失败是应用输出，不是进程崩溃。
- 未验证：`uv run python labs/03_live_smoke.py`（退出码 0，输出 `M0-LIVE: NOT_RUN`）；尚无 `AGENTLOOM_LIVE_MODEL` 与 `AGENTLOOM_LIVE_API_KEY`，中文真实工具调用、usage、流式均未验证。M0.4 的 `:memory:` checkpointer 只证明当前 SDK 的异步与恢复接口可运行，不证明磁盘持久化或生产审批语义。
- 用户的预测、实验、复述反馈：待反馈。此前用户询问为何 AI 工具调用与 ToolMessage 都保存 `call-1`，已提供解释；尚未收到用户自己的复述或实验结果，理解状态保持 AWAITING_FEEDBACK。
- 下一步：留给用户运行 M0.3 失败/终止小实验并提问；M1 由用户另行安排。若要 M0-LIVE 验证，需用户在本机环境变量中配置模型 ID 和密钥，可选兼容 endpoint；密钥不写进进度或日志。

## M1.1～M1.3 实现与学习记录（2026-10-06）

- 单元与范围：M1.1 正式 `create_agent` 组装与精简 State；M1.2 一次 Alembic 九表基线、Thread/Run/Message/Event 当前业务映射；M1.3 只做提交、幂等、同线程排他和状态查询。HTTP 提交仅持久化 `pending`，自动执行/SSE/取消留给 M1.4～M1.5。
- 参考源码路径 / 符号 / HEAD：`D:\Forksourcefolder\deer-flow\backend\packages\harness\deerflow\agents\factory.py`：`create_deerflow_agent`（67 行，`create_agent` 189 行）；`agents/thread_state.py`：`merge_artifacts`（93 行）、`merge_todos`（120 行）、`ThreadState`（352 行）；`runtime/runs/manager.py`：`RunManager.create`（617 行）、`try_start`（905 行）、`create_or_reject`（1522 行）。HEAD `5c3329afadfd8f65fd2fc3f8665069759218b704`；目标文件无本地 diff。
- 原版解决的问题：factory 把模型、工具、State、中间件及可选 checkpointer 交给框架；ThreadState 为不同字段定义合并规则；RunManager 的 `create` 注明不是并发生产入口，`create_or_reject` 才是原子入场路径，`try_start` 负责后续启动。原版运行记录的存储与并发实现更复杂；本项目没有复制原实现。
- 精简映射：`backend/src/agentloom/agent_factory.py` 用真实 `create_agent`，离线 `BaseChatModel` 适配 M0 fake 模型，消息由框架 reducer 合并，Todo 按 ID 合并、产物 ID 去重，`current_run_id` 替换；不移植 feature 自动组装和完整中间件链。`backend/migrations/versions/0001_application_baseline.py` 固定 schema.sql 的九表 DDL，应用运行时只执行 Alembic 迁移，不调用 `create_all()`；框架独立管理 checkpoints.sqlite。`backend/src/agentloom/run_manager.py` 用一个短事务持久化 Run、稳定输入消息和 `message.completed` 事件；SQLite 部分唯一索引守住未结束线程槽位，重复 ID 的 body hash 决定重用或 409。
- 实现完成：M1-01/02/03 范围内代码与 API；`POST /api/threads`、`POST /api/threads/{id}/runs`、`GET /api/runs/{id}`、`GET /api/threads/{id}/messages`。HTTP 正常提交返回 202 和 `pending`，不会误称 Agent 已执行。真实 Agent 通过独立演示/测试调用，并在单独 checkpoint 文件保存执行状态。
- 实际轨迹：`uv run python labs/04_m1_demo.py`（退出码 0）显示 `submit: 202 ... status=pending` → 相同提交 `repeat: 202 same_run=True` → 同 ID 改内容 `409 REQUEST_CONFLICT` → 新 ID 同线程 `409 THREAD_BUSY` → `input_messages: 1`；随后明确标记的 `formal_agent_direct` 调用 `call-1` 得到工具结果 `5`、最终回答 `5`。`--second-thread` 复跑（退出码 0）把最后一个新请求发到另一线程，得到 `202 status=pending`。两个 SQLite 文件分开。
- M1-01：`uv run alembic upgrade head`（退出码 0，在项目根 `.agentloom/app.sqlite` 创建基线）；随后读取 `alembic_version=0001` 与九张业务表。迁移测试另在临时目录执行：结构与 schema.sql 的表/索引 SQL 对照，二次升级保留原数据，外键检查为空。应用启动也迁移并初始化独立 checkpoints.sqlite。
- M1-02/03：HTTP 测试与并发异步测试验证重复同 body 得同 Run、不同 body 得 409、不同请求争同线程只有一个入场、不同线程可以入场；数据库只留一条输入消息/事件，重启后重复提交仍返回旧 Run。非法 attachment_ids 为 422，缺失线程为 404。
- 修复记录：正式图首跑发现 `tool_loop.py` 中 `AIMessage` 导入被写成了错误字符，修复后图执行成功。首轮迁移生成时误把 SQL 注释中的分号当作结束符，导致建表失败；去掉注释后重新固定 19 条完整 DDL。首轮 ORM flush 先写引用 Run 的 Message，触发外键失败；改为先 flush Run。修复后复测通过。非唯一约束错误不再被笼统转换为 THREAD_BUSY。
- 验证命令与最终结果：`uv run pytest -m "not live and not docker"`（退出码 0，12 passed）；`uv run ruff check .`（退出码 0）；`uv run ruff format --check .`（退出码 0）；`uv lock --check` 与 `uv sync --locked`（退出码 0，83 packages）；`uv run python labs/04_m1_demo.py`（退出码 0）；`uv run alembic upgrade head`（退出码 0）。M1-04～06 NOT_RUN，M0-LIVE NOT_RUN。
- 用户的预测、实验、复述反馈：待反馈；用户尚未运行 M1 小实验或复述 Thread、Run、Checkpoint 与线程槽位，理解状态保持 AWAITING_FEEDBACK。先前 M0 学习待反馈项继续保留。
- 下一步：由用户运行/提问本单元实验；后续若用户安排 M1.4，连接 Run worker 与事件/SSE，再处理断线重连，不在本轮自动添加。

### M1.1～M1.3 范围复验（2026-10-11）

- 复验原因与范围：用户再次指定 M1.1～M1.3；核对后确认实现早已交付，且后续 M1.4～M2.2 正在复用同一正式执行链。本次只复查正式 Agent、九表迁移、提交幂等与同线程排他，没有重新生成旧架构，也没有新增后续功能。
- 参考源码复核：DeerFlow HEAD 仍为 `5c3329afadfd8f65fd2fc3f8665069759218b704`；复读 `agents/factory.py:create_deerflow_agent`、`agents/thread_state.py:merge_artifacts/merge_todos/ThreadState`、`runtime/runs/manager.py:RunManager.create/try_start/create_or_reject`，目标文件无本地 diff。
- 当前精简映射：`backend/src/agentloom/agents/factory.py:create_loom_agent` 负责 `create_agent` 组装；`agents/state.py:LoomState` 保存可序列化状态；`persistence/database.py:migrate_database` 与 `migrations/versions/0001_application_baseline.py` 管理九表基线；`runtime/manager.py:RunManager.submit` 用 request hash、数据库唯一约束和短事务完成幂等及线程槽位竞争。
- 实现完成：M1.1～M1.3 无需补写功能。顺手修复一次全项目格式门禁发现的 `sandbox/workspace.py` 纯格式偏差，没有改变 M2 行为。
- 测试通过：定向 `uv run pytest tests/test_m1_agent.py tests/test_m1_database.py tests/test_m1_admission.py -q` 为 `7 passed`；全量 `uv run pytest -q` 为 `23 passed`；`uv run ruff check .` 与 `uv run ruff format --check .` 通过；`uv lock --check` 解析 71 个包。
- 真实模型验证：`uv run python labs/live_model_smoke.py` 使用本机 `openai_compatible / gpt-5.6-sol`，真实轨迹为模型提出 `add` → 工具返回 `5` → 模型回答 `2 + 3 = 5`；2 次模型尝试，478 input tokens、33 output tokens，24 个模型流条目/增量块，`LIVE: PASS`。密钥未输出。
- 成功与失败轨迹：`uv run python labs/04_m1_demo.py` 返回首次提交 `202`，相同请求 `same_run=True`；同 request ID 改正文返回 `409 REQUEST_CONFLICT`，没有创建第二个 Run。后台执行、SSE 和取消输出属于已存在的 M1.4～M1.5，本次不据此扩大实现范围。
- 用户理解状态：仍为 AWAITING_FEEDBACK。技术复验不能替代用户对 Thread、Run、checkpoint、幂等键和线程槽位的复述或实验。
- 下一步：留给用户运行本节小实验和提问；不自动回退重做 M1.1～M1.3，也不自动进入新的开发单元。

## M1.4～M1.5 实现与学习记录（2026-10-07）

- 单元与范围：M1.4 将已持久化的 pending Run 交给应用生命周期持有的后台任务，投影消息/工具事件并提供数据库游标 SSE；M1.5 增加幂等取消、终态条件更新和基础模型/工具/token 计量。未进入 M2 的文件、审批、Docker 或子任务清理。
- 参考源码路径 / 符号 / HEAD：`D:\Forksourcefolder\deer-flow\backend\packages\harness\deerflow\runtime\runs\worker.py`：`run_agent`（891 行）、流循环中的 `record.abort_event` 检查（1385～1405 行）、终态分支（1537 行附近）；`runtime/runs/manager.py`：`try_start`（905 行）、`set_status_if_not_cancelled`（1065 行）、`cancel`（1328 行）、`create_or_reject`（1522 行）。HEAD `5c3329afadfd8f65fd2fc3f8665069759218b704`；目标文件无本地 diff。
- 原版解决的问题：RunManager 将原子入场、启动权、持久取消和终态竞争集中管理；`run_agent` 在独立后台任务中驱动 LangGraph stream，循环检查取消信号，发布事件，并在共享 finally 路径收尾。原版还支持多 worker lease、扩展、目标续跑、子任务、工作区回滚和多种 stream mode，本项目没有复制这些分支。
- 精简映射：`runtime/executor.py` 的 `RunExecutor` 由 FastAPI lifespan 持有，使用 semaphore 控制同时运行数；`runtime/manager.py` 用 SQLite 条件 UPDATE 实现 pending→running、running→succeeded/failed、pending/running→cancelling→cancelled；`runtime/events.py` 只提供进程内唤醒，回放事实始终读取 `run_events`；`api/app.py` 提供 after_seq/Last-Event-ID SSE 和 cancel API。
- SSE 取舍：首版只持久化完整 `message.completed`、工具开始/结束、usage 和终态事件，尚不持久化 token 级 `message.delta`。订阅先记通知版本再查 `seq > cursor`，没有事件时才等待通知；超时继续查库。断线只退出订阅生成器，不触碰 Run task。
- 取消/计量取舍：当前没有 M2 容器和子任务，因此取消只关闭 Agent task；未来启用外部资源时必须扩展同一收尾路径。基础计量由一个 run-scoped callback 统计模型尝试、真正开始的工具数及服务商 usage；缺 usage 的尝试将 `usage_complete` 置为 false。复杂重试、价格估算和硬 token 预算仍由后续 ModelService 完善，不在多个层重复累加。
- 实际成功轨迹：`uv run python labs/04_m1_demo.py` 退出码 0。提交得到 202/pending；相同请求得到同 Run，不同 body 得 409；后台 Run 最终 succeeded，fake 计量为 2 次模型、1 次工具、20 input/10 output token；以 cursor=2 重连依次补 seq 3～9，最后为 run.finished。第二个 Run 在模型等待中取消，响应先为 cancelling，最终 cancelled，只有一条 cancelled 的 run.finished。
- 失败与竞争轨迹：受控模型异常进入 failed，保留 `AGENT_EXECUTION_FAILED` 与 failed 终态事件；取消先赢后，即使模型线程晚返回也不能覆盖 cancelled；成功先赢后，晚到 cancel 原样返回 succeeded，且 run.finished 仍只有一条。
- 测试通过：`uv run pytest -m "not live and not docker"` 退出码 0，13 passed；覆盖 M1-04/05/06。`uv run ruff check .`、`uv run ruff format --check .`、`uv lock --check`、`uv sync --locked` 均退出码 0；29 个文件格式通过，锁文件解析 70 个包。完整演示复验退出码 0。
- 修复记录：首轮旧 M1.3 测试仍期待 HTTP Run 永远 pending，现已改为显式 fake 并等待后台终态，避免离线测试读取本机真实 provider。首次 ruff 报告 API import 顺序，最终格式检查要求压缩一处投影构造换行，均已修复并复验。
- 未验证：完整 API worker 尚未用真实模型做长任务/断线/取消评测；当前真实证据仍是独立 live smoke。SQLite 单进程语义已测，多进程 lease 不在首版范围。token 级流式增量未实现。
- 用户的预测、实验、复述反馈：待反馈，理解状态保持 AWAITING_FEEDBACK。
- 下一步：留给用户运行本节小实验并提问；只有用户安排后才进入 M2.1。

## M1 架构与配置整理（2026-10-06）

- 用户要求：按 design.zh-CN.md 整理代码结构、删除已不用的前置实验、补充 ORM 字段中文说明，并准备真实模型本机配置。
- 代码结构：正式代码从包根目录迁入 `api/`、`runtime/`、`agents/`、`models/`、`tools/`、`persistence/`；API、RunManager、AgentFactory、模型适配、工具与数据库职责分开。
- 数据映射：`persistence/models.py` 映射九张业务表；每个映射字段均带中文 `comment` 元数据。SQLite 不原生保存列注释，所以 Navicat 不会从数据库文件显示这些中文说明；源码元数据测试保证没有漏注释，结构仍由 Alembic 基线和 schema.sql 管理。
- 删除内容：移除 M0 手写 StateGraph、旧 CLI、旧 fake/tool-loop 单测、旧 SDK/MCP/live smoke，以及根目录下重复的三份交接文档；同时移除当前无引用的 `langchain-mcp-adapters` 依赖，等 M5 真正接入 MCP 时再安装。正式链继续使用 `create_agent`，离线模型和内置工具已移入正式分层。M0 历史命令与结果继续保留在本文件，未冒充当前入口。
- 配置：新增可提交的 `config.example.yaml`、`.env.example`，以及被根 `.gitignore` 忽略的本机 `config.yaml`、`.env`。本机 provider 后续已切换为原生 `anthropic`；密钥为空，真实请求未执行。配置由 Pydantic 拒绝未知字段；密钥只从配置指定的环境变量读取，缺失时明确 NOT_RUN，不回退 fake。
- SQLite 实况：`D:\Forksourcefolder\agentloom\.agentloom\app.sqlite` 存在，Alembic 版本 0001，九张业务表存在；启动一次 API 生命周期后 `checkpoints.sqlite` 也已创建，包含框架表 `checkpoints`、`writes`。Navicat 浏览业务数据应连接 app.sqlite。
- 验证：重构后 `uv run pytest -m "not live and not docker"` 为 8 passed；`uv run ruff check .`、`uv run ruff format --check .` 与 `uv lock --check` 通过；锁文件解析 67 个包。M1 demo 退出码 0。`uv run python labs/live_model_smoke.py` 输出 provider/model 后因缺少 `MODEL_API_KEY` 返回 `LIVE: NOT_RUN`，没有发出网络请求。
- 用户待操作：当前改用 Anthropic 后，在根 `.env` 填写 `ANTHROPIC_API_KEY`；官方接口保持 `ANTHROPIC_BASE_URL` 为空。在 `config.yaml` 核对账户可用的 `model` 和上下文窗口后运行 live smoke。结果和理解反馈待用户提供。

## Anthropic 原生模型接入（2026-10-07）

- 实现完成：模型 provider 增加 `anthropic`；统一模型工厂使用 `ChatAnthropic`，继续交给现有 `create_agent`，工具与 State 无需增加 Anthropic 专用执行链。新增 `langchain-anthropic==1.7.5`，其传递依赖 `anthropic==1.11.0`，锁文件共解析 70 个包。
- 配置完成：可提交样例说明三种 provider；本机 `config.yaml` 已选择 `anthropic` 和 `claude-sonnet-5`，`temperature: null` 让模型采用服务端默认采样设置。密钥变量为 `ANTHROPIC_API_KEY`，可选代理地址为 `ANTHROPIC_BASE_URL`。本机 `.env` 只保留空值模板，未写入密钥。
- 离线测试通过：`uv run pytest -m "not live and not docker"` 退出码 0，10 passed；覆盖 Anthropic 配置解析、命名密钥缺失、`ChatAnthropic` 参数映射，以及 `add`/`lookup_note` 工具转换。`uv run ruff check .`、`uv run ruff format --check .`、`uv lock --check`、`uv sync --locked` 均退出码 0。
- 修复记录：首次 ruff 检查因模型工厂导入顺序失败，调整顺序后复验通过。
- 真实验证：首次缺少 `ANTHROPIC_API_KEY` 时输出 `LIVE: NOT_RUN`，没有发出网络请求。用户填写后于 2026-10-07 重跑，配置实际解析为 `provider=anthropic`、`model=deepseek-v4-flash`、Base URL 主机 `agentrouter.org`；密钥存在且未输出。请求到达服务端后返回 `AnthropicAuthenticationError` 401，错误类型为 `unauthorized_client_error`、消息为 `unauthorized client detected`，所以记录 `LIVE: FAIL`，未产生工具调用轨迹。
- 后续真实成功：用户改为 `openai_compatible` / `gpt-5.6-sol` 后首次因 `.env` 中 `MODEL_API_KEY` 与 `MODEL_BASE_URL` 的值填反而出现 `OpenAIConnectionError`。交换两项后运行 `uv run python labs/live_model_smoke.py`，退出码 0；轨迹为模型请求 `add` → 工具结果 `5` → 最终答案 `2 + 3 = 5` → `LIVE: PASS`。
- 安全待办：诊断填反配置时，密钥因位于 Base URL 字段而被 URL 路径诊断意外输出；该密钥需要在服务商控制台轮换，并把新密钥仅写入 `MODEL_API_KEY`。
- 学习状态：本次属于 provider 扩展，不推进 M1.4；用户对原生 Anthropic 与 OpenAI 兼容接口差异的复述或实验反馈待提供。

## M0/M1 验收审查与修复（2026-10-11）

- 审查范围：以 `ACCEPTANCE.md` 的 M0-01～M0-LIVE、M1-01～M1-06 为当前已实现范围；检查正式 `create_agent` 链、Run 入场、执行器、事件持久化、SSE、取消及真实 provider。M2～M6 没有借本次审查提前实现。
- 工具结果消费：给 `add` 注入返回 `99` 的替代实现后，真实 ToolNode 生成 `ToolMessage(content="99")`，fake 模型最终回答随之变成“最终答案：99”；M0-02 当前正式链 PASS，不依赖固定成功文案。
- 无效调用与循环：错误参数和未知工具都会得到同 `tool_call_id` 的 `status=error` ToolMessage；`RuntimeConfig.max_tool_executions_per_run` 与 `max_model_attempts_per_run` 现已接入 LangChain 的 Tool/Model Call Limit middleware。重复模型测试只真正执行 1 次工具，在第 3 次模型调用后以 `ModelCallLimitExceededError` 进入 failed，不再无界循环。
- 失败可见性：审查发现原实现虽会把工具异常写成 Run failed，但异常路径没有 `tool.started/tool.failed` 事件。现由 run-scoped callback 收集真实工具生命周期，失败事务按顺序持久化工具事件、usage 和 `run.finished(failed)`；模型异常仍保留 `AGENT_EXECUTION_FAILED`，没有被转成 succeeded。
- 重复请求：增加模型调用计数回归；相同 request ID/body 在执行中及完成后都返回同一 Run，模型调用数保持 2。真实 API smoke 同样得到 `same_run=True`，不同 body 为 409，完成后重发不增加消息或事件。
- 取消：M1 当前取消保持幂等，`cancelling` 与 `succeeded/failed` 通过条件更新竞争，只有一条终态事件；fake 阻塞模型验证取消先赢时晚到完成不能覆盖 cancelled，完成先赢时晚到取消保持 succeeded。同步 fake 调用所在工作线程可能晚返回，但其结果被终态 CAS 丢弃。真实 provider 长调用取消尚未做可控注入，因此为 NOT_RUN。
- 审批与恢复边界：九表中已有 `approvals`、`tool_executions` 结构，但当前没有 Approval middleware、审批 API、interrupt/resume、工具重放账本或 `/recover`；`GET run.pending_approval_id` 仍固定为 null。这些属于 M2，M2-02～06 保持 NOT_RUN，不能把建表算成功能实现。当前也没有容器和子 Agent，取消尚无这些外部资源可清理。
- 当前 M0-05 边界：2026-10-06 曾在当时锁定环境跑过 create_agent/checkpoint/interrupt/MCP smoke；M1 架构整理后删除了临时脚本和未使用的 MCP 依赖。当前 create_agent 与磁盘 checkpoint 有持续测试，interrupt/MCP 的当前环境完整复验为 NOT_RUN，后续按 M2/M5 恢复正式实现与验证。
- 实际失败案例：工具 `add` 在收到 `{a: 2, b: 3}` 后抛出 `RuntimeError("planned tool failure")`。修复后轨迹为 `tool.started(call-1)` → `tool.failed(call-1)` → `usage.updated(model=1, tool=1)` → `run.finished(status=failed)`；Run 保留异常文本且没有 assistant 成功消息。另一次测试首跑因测试模型把列表交给 `sum()` 而报 `TypeError`，已改为布尔计数后复验通过，未将该测试代码错误误判为产品预算结果。
- 离线验证：在 `backend` 执行 `uv run pytest -q`，退出码 0，18 passed；`uv run ruff check .`、`uv run ruff format --check .`、`uv lock --check` 均退出码 0。
- 真实模型验证：`uv run python labs/live_model_smoke.py` 退出码 0；`openai_compatible/gpt-5.6-sol` 两次模型调用完成中文 `add`，结果 5，usage 为 190 input/33 output token，收到 24 个模型增量条目。`uv run python labs/live_api_smoke.py` 退出码 0；Run succeeded，2 次模型、1 次工具、usage complete=true，4 条消息、9 条事件，相同请求复用、冲突请求 409。
- 学习状态：本次只完成技术审查与修复；M0.0～M1.5 的用户理解状态原样保留 NEEDS_REVIEW/AWAITING_FEEDBACK，没有自动改成 VERIFIED。

## M2.1～M2.2 实现与学习记录（2026-10-11）

- 单元与范围：M2.1 实现每线程工作目录、统一虚拟路径与 list/read/new-write 文件工具；M2.2 实现上传、`present_files`、不可变文件快照、artifacts 表登记、元数据和内容下载。没有开始 M2.3 工具账本、M2.4 审批恢复或 M2.5 Docker。
- 参考源码路径 / 符号 / HEAD：`D:\Forksourcefolder\deer-flow\backend\packages\harness\deerflow\sandbox\tools.py` 的 `validate_local_tool_path`（985 行）、`_resolve_and_validate_user_data_path`（1071 行）、`read_file_tool`（2788 行）；`tools/builtins/present_file_tool.py` 的 `_normalize_presented_filepath`（33 行）、`present_file_tool`（84 行）。HEAD `5c3329afadfd8f65fd2fc3f8665069759218b704`，目标文件无本地 diff。
- 原版解决的问题：DeerFlow 先限制 `/mnt/user-data/...` 等允许的虚拟路径，再把路径解析到当前线程的物理根并复核解析结果；`present_files` 只接受 outputs 中的路径并通过 State reducer 展示。原版还处理多 sandbox provider、技能/ACP/自定义挂载、远程文件和多用户身份，本单元没有复制这些分支。
- 精简映射：`sandbox/workspace.py::WorkspaceService` 固定 `.agentloom/threads/{thread_id}/{workspace,uploads,outputs,artifacts}` 布局，模型只看到 `/mnt/user-data/{workspace,uploads,outputs}`。词法检查拒绝 `..`、空段、宿主机绝对路径和 Windows 不安全名称；解析后再次检查真实路径及 symlink/junction。`runtime/context.py::LoomContext` 持有服务对象并由 RunExecutor 逐 Run 注入，不进入 State/checkpoint。
- 文件操作取舍：`list_dir/read_file/write_file` 已作为正式 Agent 工具；`write_file` 只原子创建新文件，已有文件明确返回 `FILE_ALREADY_EXISTS`。`replace_text` 的 hash 比较和原子替换底层能力已实现并测试，但没有作为模型工具开放，必须等 M2.4 审批层提供可信授权，防止提前绕过覆盖审批。
- 产物设计：`ArtifactService.register_outputs` 只读取当前线程 outputs 下已经稳定的普通文件，先捕获字节、大小和 SHA-256，再复制到隐藏的 `artifacts/{artifact_id}/` 不可变快照并写 artifacts 表。下载重新核对大小与 hash；outputs 原文件随后变化不会改变已登记快照。上传直接写入线程只读 uploads 快照并登记 `kind=upload`。API 从不返回宿主机绝对路径或数据库 `relative_path`。
- API 与 Agent 链：新增 `POST /api/threads/{id}/uploads`、`GET /api/artifacts/{id}`、`GET /api/artifacts/{id}/content`；正式工具集合新增 `list_dir/read_file/write_file/present_files`。`present_files` 成功后返回真实 artifact ID，并通过 LangGraph `Command` 更新 `LoomState.artifact_ids`；失败返回同 tool_call_id 的 error ToolMessage。
- 实际成功轨迹（fake）：用户输入 → `write_file(/mnt/user-data/outputs/report.txt)` → 文件 SHA/大小结果 → `present_files` → 快照与 artifacts 行 → ToolMessage 返回 artifact ID → assistant 完成；API 下载内容与写入内容一致。之后修改 outputs 原文件，下载内容保持原快照。
- 实际失败轨迹：`/mnt/user-data/workspace/../uploads/secret.txt`、宿主机绝对路径、双斜线和指向线程外的符号链接均抛出 `PATH_OUT_OF_SCOPE`，没有返回目标内容；用错误 `expected_sha256` 替换文件得到 `FILE_CONTENT_MISMATCH`；篡改上传快照后下载返回 409 `ARTIFACT_INTEGRITY_FAILED`；以另一线程查询 artifact ID 得到 `ARTIFACT_NOT_FOUND`。
- 离线验证：`uv run pytest -q` 退出码 0，23 passed；新增 5 项测试覆盖上述路径和产物行为。`uv run ruff check .`、`uv run ruff format --check .`、`uv lock --check` 均退出码 0；锁文件为 71 packages，新增 `python-multipart 0.0.32` 用于 multipart 上传。
- 真实模型验证：`uv run python labs/live_files_smoke.py` 退出码 0；`openai_compatible/gpt-5.6-sol` 实际按顺序调用 `write_file`、`present_files`，Run succeeded，3 次模型、2 次工具、1212 input/105 output token，usage complete=true；下载 24 字节并核对为要求内容。测试使用临时数据目录，没有写入本机正式 app.sqlite。
- 未验证/后续：上传 artifact 尚未通过 `attachment_ids` 自动注入模型上下文；该链与 CSV/Docker 演示在 M2.6 完成。覆盖已有文件的模型工具、账本、审批恢复、Docker 执行与取消清理仍为 NOT_RUN。
- 用户的预测、实验、复述反馈：待反馈；M2.1/M2.2 理解状态保持 AWAITING_FEEDBACK。
- 下一步：留给用户运行文件小实验、回答理解问题和提问；只有用户安排后才进入 M2.3。

## M2.3～M2.4 实现与学习记录（2026-10-11）

- 单元与范围：M2.3 启用 `tool_executions` 账本，按 `(run_id, scope, tool_call_id)` 约束逻辑调用并保存规范参数、重放等级、状态、结果和 attempts；M2.4 实现 `replace_file` 整批审批、LangGraph interrupt、持久化审批 API、重启后同 Run 恢复和旧文件 hash 前置检查。没有实现 Bash/Docker、uncertain 人工处置或取消补齐，M2.5/M2.6 未提前开始。
- 参考源码路径 / 符号 / HEAD：`D:\Forksourcefolder\deer-flow\backend\packages\harness\deerflow\agents\middlewares\clarification_middleware.py` 的 `ClarificationMiddleware`（75 行）、`_drop_parallel_non_clarification_tools`（395 行）、`_handle_clarification`（474 行）；对照其同批工具阻断、人工输入 ToolMessage 和 `Command(update=..., goto=END)`。HEAD `5c3329afadfd8f65fd2fc3f8665069759218b704`，目标文件无本地 diff。当前 DeerFlow 这里结束本轮澄清流，并不是本项目所需的持久化 `interrupt/Command(resume)` 动作审批，也不提供审批 hash、SQLite 工具账本或文件旧 hash 方案。
- 精简映射：`runtime/ledger.py::ToolLedgerService` 管理 prepared/running/terminal 状态、参数冲突和结果反序列化；`agents/middleware.py::ApprovalMiddleware/ToolLedgerMiddleware` 分别在模型后暂停整批和在执行点登记结果；`runtime/approvals.py::ApprovalService` 把 `run_id + scope + tool calls + canonical args + old hash + policy_version` 绑定为审批快照；`RunExecutor.resume` 只接受数据库 `ApprovalRecord` 生成的 `Command(resume=...)`。
- 两层授权：middleware 发现批次含 `replace_file` 就在任何工具执行前创建账本 prepared 记录并 interrupt；`replace_file` 工具内部再次按可信 `LoomContext` 查询 approved 记录，核对 tool_call_id、完整参数和当前文件 SHA。模型 schema 中没有 `approved=true` 一类可伪造授权字段。
- interrupt 重入修复：首轮旧 hash 测试发现恢复会从 middleware 节点开头重跑；若重读文件就会在恢复阶段改变批准对象。修复后 `suspend_key` 只由稳定提案身份生成，首次审批冻结 precondition，恢复重入复用数据库快照；实际工具执行点才重新读取当前 SHA。
- 账本和事件取舍：相同逻辑键且参数一致的 succeeded/failed 结果直接重放，不增加 attempts；相同键换参数返回 `TOOL_CALL_CONFLICT`。进程启动把遗留 running 置为 uncertain，不自动重做。审批拒绝把整批记录写成 denied/attempts=0，并为每个 tool call 生成失败 ToolMessage；事件改用真实工具 callback，拒绝批次不再产生虚假的 tool.started。
- API：新增 `GET /api/runs/{id}/tool-executions`、`GET /api/runs/{id}/approvals`、`POST /api/approvals/{id}/resolve`；`GET /api/runs/{id}` 返回真实 `pending_approval_id`。resolve DTO 禁止额外字段，只接受 payload hash、approve/reject 和原因；相同答复幂等，不同答复或 hash 冲突为 409。
- 离线成功轨迹：`uv run python labs/m2_approval_demo.py` 显示 `waiting_input`；批准前 note 仍为第一版且 sibling `side.txt` 不存在；批准后同一 Run succeeded，note 为第二版，sibling 存在；账本 `replace_file/write_file` 均为 succeeded、attempts=1。
- 失败轨迹：审批后、恢复前把 note 改成“外部修改”，`replace_file` 得到 `APPROVAL_PRECONDITION_FAILED`，账本为 failed，外部修改未被覆盖；重复相同审批答复为 200，换 reject 或 payload hash 为 409；拒绝整批后两条账本均 denied/attempts=0 且没有任何 tool.* 执行事件。
- 离线验证：新增 4 项 M2.3/M2.4 测试；`uv run pytest -q` 为 27 passed，`uv run ruff check .`、`uv run ruff format --check .`、`uv lock --check` 通过，锁文件仍为 71 packages。
- 真实模型验证：`uv run python labs/live_approval_smoke.py` 使用 `openai_compatible/gpt-5.6-sol`；真实模型依次调用 `read_file` 和 `replace_file`，Run 进入 waiting_input，脚本对临时固定文件批准后同 Run succeeded，内容从第一版变成第二版；两条账本均 succeeded/attempts=1，`LIVE APPROVAL: PASS`。密钥未输出，正式数据库未使用。
- 验收状态：M2-03、M2-04 PASS。M2-02 指定 Bash 与普通工具同批；当前 Bash 必须等 M2.5 Docker 才能开放，因此该原样用例仍为 NOT_RUN，本轮只用 `replace_file + write_file` 证明通用整批暂停机制。M2-05 uncertain 人工处置、M2-06 取消补齐与 M2-DOCKER 均 NOT_RUN。
- 用户的预测、实验、复述反馈：待反馈；M2.3/M2.4 理解状态为 AWAITING_FEEDBACK，不能由技术测试自动改成 VERIFIED。
- 下一步：留给用户运行离线审批实验、检查账本并提问；只有用户安排后才进入 M2.5。

## M2.5～M2.6 实现与学习记录（2026-10-12）

- 单元与范围：M2.5 新增只经 Docker 执行的 `bash`、整批审批、容器超时/取消/启动清理、`uncertain` 的 verify/skip 和 interrupted Run 恢复；取消 Run 时把未响应工具写成明确失败 ToolMessage 并同步 checkpoint。M2.6 新增上传 CSV → 写分析脚本 → 审批 Bash → 容器生成 Markdown/PNG → `present_files` 登记下载的演示。没有进入 M3。
- 参考源码路径 / 符号 / HEAD：`D:\Forksourcefolder\deer-flow\backend\packages\harness\deerflow\sandbox\tools.py` 的 `bash_tool`（2380 行）、`_execute_bash_command`（1889 行）和 `read_file_tool`（2788 行）；辅助阅读 `sandbox/AGENTS.md` 的 provider、环境变量与取消清理约束。HEAD `5c3329afadfd8f65fd2fc3f8665069759218b704`，目标目录无本地 diff。
- 原版解决的问题：DeerFlow 将 bash/read/write 工具路由到可配置 Sandbox provider，处理线程目录、身份、环境变量、输出截断和 provider 生命周期；当前版本还包含多 provider、跨实例租约、远程容器与 Skill 隔离。AgentLoom 只保留单用户单进程所需的 Docker 执行、线程挂载、有限输出和取消清理，不复制租约/多 provider/远程控制面。
- Docker 精简实现：`sandbox/docker.py::DockerCommandService` 每个 Bash 调用创建一个容器，固定 `network=none`、非 root、只读根、`cap-drop ALL`、`no-new-privileges`、CPU/内存/PID/超时与 `/tmp` 限制；只挂当前线程 workspace、只读 uploads 和 outputs，不注入模型密钥。Docker 缺失时返回 `DOCKER_UNAVAILABLE`，绝不回退宿主机 shell。`docker/Dockerfile` 固定 Python 3.12、pandas、matplotlib、tabulate。
- 审批与取消：`ApprovalMiddleware` 现在把 `bash` 和 `replace_file` 都视为受保护动作，一批中只要有一个就整批 interrupt；工具执行点由 `authorize_bash` 再核对 tool_call_id 和完整参数。显式 cancel 先强制删除 Run 已登记的容器，再把 prepared/running/uncertain 账本改为 cancelled，生成 `RUN_CANCELLED` ToolMessage，写入 LangGraph checkpoint 和 UI 消息后才结束 Run；下一轮不会携带悬空 tool call。
- 崩溃恢复：启动时把遗留 running 工具转为 uncertain，并把对应 running Run 转为 interrupted。`POST /api/tool-executions/{id}/resolve` 支持 `skip`（保存 `TOOL_RESULT_ABANDONED` 失败结果）或 `verify`（只接受工具事先声明的文件路径，服务端重新读取并核对 SHA-256）；未解决 uncertain 时 `/api/runs/{id}/recover` 返回 409。全部处理后从原 checkpoint 恢复，账本结果被重放给模型，attempts 不增加，Bash 不重做。
- 实际成功轨迹（离线故障注入）：Bash 写出 `outputs/bash.txt` 后在 `ledger.finish` 前模拟进程退出，账本停在 running/attempts=1；重启后 Run=interrupted、工具=uncertain；服务端用实际文件 SHA 验证为 succeeded；`/recover` 从原 checkpoint 继续并最终 succeeded，新 Docker 执行次数为 0、账本 attempts 仍为 1。
- 实际失败轨迹：uncertain 的 verify 提交错误 SHA 返回 409 `TOOL_EVIDENCE_MISMATCH`；未处理 uncertain 就 recover 返回 409 `RUN_RECOVERY_BLOCKED`；另一个 uncertain 选择 skip 后保存 failed/`TOOL_RESULT_ABANDONED`。等待 Bash 审批时取消会生成 `RUN_CANCELLED` ToolMessage；随后同线程新 Run succeeded，证明旧 tool call 已配对。
- M2-02/M2-06：确定性模型同批提出 `bash + write_file`，waiting_input 时两个输出均不存在且账本均 prepared/attempts=0；批准后两者各执行一次。另一个用例在等待审批时取消，账本和 checkpoint 都补齐失败结果，然后同线程下一轮正常完成。两项为离线编排行为 PASS，未把 FakeDocker 当成容器隔离证据。
- M2.6 演示：`labs/m2_csv_demo.py` 使用确定性模型提出真实工具调用，只有工具结果能推进阶段；脚本已覆盖上传、分析脚本、审批、Docker、产物登记与下载。`uv run python labs/m2_csv_demo.py` 退出码 0，但明确输出 `NOT_RUN - 本机没有 docker 命令`，因此没有宣称 CSV 容器演示通过。
- 离线验证：`uv run pytest -m "not live and not docker"` 退出码 0，33 passed/1 deselected；`uv run ruff check .`、`uv run ruff format --check .`、`uv lock --check` 均通过。`uv run pytest -m docker -q` 退出码 0但结果为 1 skipped/33 deselected，按约定记 M2-DOCKER NOT_RUN。
- 真实模型回归：`uv run python labs/live_model_smoke.py` 与 `uv run python labs/live_approval_smoke.py` 均退出码 0；`openai_compatible/gpt-5.6-sol` 的 add 工具流、流式 usage，以及 read_file → waiting_input → replace_file 恢复均 PASS。真实模型本轮未执行 Bash/CSV，因为本机没有 Docker；密钥未输出。
- 验收状态：M2-02、M2-05、M2-06 PASS（离线可控故障/编排）；M2-DOCKER NOT_RUN；M2.6 代码 DELIVERED、真实容器演示 NOT_RUN。Docker 环境可用后需要构建 `agentloom-python:v1` 并补跑 docker marker 与 CSV 演示。
- 用户的预测、实验、复述反馈：待反馈；M2.5/M2.6 理解状态保持 AWAITING_FEEDBACK，技术测试不能自动改为 VERIFIED。
- 下一步：留给用户运行实验和提问，不自动进入 M3。

## M2 Docker 环境补验（2026-10-13）

- 环境修复：清理缺少 `BasePath` 的孤立 `docker-desktop` WSL 注册记录，WSL 从 2.3.24.0 更新到 3.0.3.0；Docker Desktop 4.95.0 使用 WSL2 后端，程序位于 `E:\Apps\DockerDesktop`，数据位于 `E:\DockerData`，Docker Engine 为 29.8.2。
- 镜像构建：`docker build -t agentloom-python:v1 -f docker/Dockerfile docker` 退出码 0，真实构建 Python 3.12、pandas、matplotlib、tabulate 沙箱镜像。
- Docker 集成测试：首次扩展测试时因测试文件漏导入 `Path` 得到 1 failed/2 passed，补齐导入后 `uv run pytest -m docker -vv` 退出码 0，3 passed/33 deselected；真实验证输出挂载、只读根、无网络、内存/CPU/PID 限额、挂载边界、密钥与 Docker socket 不进入容器、超时和取消后容器删除，M2-DOCKER 从 NOT_RUN 更新为 PASS。
- M2.6 真实容器演示：`uv run python labs/m2_csv_demo.py` 退出码 0，最终 Run `084eb9b3-1ebc-4642-a01a-e03e7f863551` 为 succeeded，登记两个 artifact，下载内容通过 PNG 文件边界和 Markdown 字段检查，输出 `M2.6 CSV DEMO: PASS`。M2.6 的真实容器演示从 NOT_RUN 更新为 PASS。
- 用户的预测、实验、复述反馈仍待反馈；M2.5/M2.6 学习状态保持 AWAITING_FEEDBACK，技术补验不等于理解已验证。
- 下一步：留给用户检查 Docker 空间、运行实验和提问，不自动进入 M3。

## 异步执行复核（2026-10-13）

- 当前正式链已经是异步后台执行：提交 Run 的 HTTP 接口返回 202 后调用 `RunExecutor.start()`，由 `asyncio.create_task()` 持有任务；执行器使用 `await agent.ainvoke()`，SSE 连接只订阅数据库事件，断线不会取消或重启 Agent。
- 锁定版 LangChain 的 `BaseChatModel._agenerate()` 会用 `run_in_executor()` 包装只实现同步 `_generate()` 的离线 fake；OpenAI/Anthropic 正式适配器走异步调用，因此 fake 也不会阻塞主事件循环。
- DeerFlow 对照：`runtime/runs/worker.py::run_agent` 是 `async def`，使用 `agent.astream()` 和 `async for` 消费 `values`、`messages`、`custom` 等图流并逐项发布到 bridge。AgentLoom 当前用 `ainvoke()` 等本次图暂停或结束后取得完整状态，尚未实现模型 token/图 chunk 的实时持久化与 SSE 推送；这是“流式粒度”差异，不是同步执行。
- 验证：`uv run pytest tests/test_m1_runtime.py -vv` 退出码 0，5 passed；覆盖后台 Run 不归 SSE 连接所有、断线续传不重启、取消竞争和失败终态。由于用户的修改条件“如果仍为同步”不成立，本次没有改生产代码。
- 用户对异步执行与实时流式的区别仍待反馈，学习状态不自动改为 VERIFIED。

## M3.1～M3.2 实现与学习记录（2026-10-13）

- 单元与范围：M3.1 实现本地 `SKILL.md` 的 UTF-8/YAML frontmatter 解析、启动发现、元数据 API 和三个内置 Skill；M3.2 实现模型 `load_skill`、用户 `/skill-name`、单个活动 Skill 快照、模型 schema 收窄和执行点二次拒绝。没有实现 M3.3 大工具输出外置，也没有实现 M3.4 摘要/消息组压缩。
- 参考源码路径 / 符号 / HEAD：`D:\Forksourcefolder\deer-flow\backend\packages\harness\deerflow\skills\parser.py::parse_skill_file`；`agents/middlewares/skill_activation_middleware.py::SkillActivationMiddleware`；为核对权限双层执行，辅助阅读 `agents/middlewares/skill_tool_policy_middleware.py::SkillToolPolicyMiddleware` 与 `skills/AGENTS.md`。HEAD `5c3329afadfd8f65fd2fc3f8665069759218b704`，这些目标文件无本地 diff。
- 原版与精简映射：DeerFlow 解析 name/description/allowed-tools，并处理多类别存储、用户范围、Secret 绑定、多 Skill context 和授权提供器；AgentLoom 的 `skills/loader.py::SkillLoader` 只扫描开发者维护的一级目录，`skills/policy.py` 只保存一个活动快照，去掉多用户、安装市场、Secret 和多 Skill 合并分支。保留了路径边界、UTF-8、安全 YAML、正文按需进入模型、内容 hash 和权限两层校验。
- 渐进加载：启动目录只产生 `SkillMetadata`；初始 system context 只有 name/description。模型调用 `load_skill` 或首条用户消息用 `/skill-name` 后，完整正文、`allowed_tools`、SHA-256、逻辑 `snapshot_ref`、激活来源和 run_id 一起写入 `LoomState.active_skill`。新 Run 显式清空旧快照；审批恢复/崩溃恢复不提供新图输入，因此继续使用 checkpoint 中的旧正文与策略。
- 权限执行：有效 schema 是本次 Agent 基础工具集合与活动 Skill `allowed-tools` 的交集，`list_skills/load_skill` 始终保留。`SkillToolPolicyMiddleware.wrap_model_call` 隐藏不允许的 schema；`wrap_tool_call` 使用同一冻结快照再次拒绝猜测调用。`ToolLedgerMiddleware` 包在策略外层，因此正式 Run 的越权尝试会记录为 failed。审批中间件只为 Skill 实际允许的 `bash/replace_file` 创建审批，避免隐藏工具先生成无意义审批。
- 内置能力：新增 `skills/research`、`skills/coding`、`skills/data-analysis` 三个中文 Skill；新增 `GET /api/skills`，响应只有元数据，不含正文。`config.skills.max_active_per_agent` 限定为 0 或 1，符合首版单 Skill 设计。
- 实际成功轨迹：`uv run python labs/m3_skills_demo.py` 发现 coding/data-analysis/research；模型三轮正文可见性为 `[False, True, True]`；加载前 schema 含 `dangerous`，加载 research 后该工具消失；活动快照打印稳定 SHA-256，最终输出 `M3.1/M3.2 DEMO: PASS`。
- 实际失败轨迹：同一演示让模型在 schema 已隐藏后仍硬编码调用 `dangerous`，返回 `SKILL_TOOL_DENIED`，`dangerous 实际执行次数: 0`。解析测试另验证缺少 YAML frontmatter 会抛 `SkillValidationError`，不会静默加入目录。
- 离线验证：`uv run pytest tests/test_m3_skills.py -vv` 退出码 0，4 passed；覆盖元数据不泄露正文、API、显式 load、slash 激活、schema 过滤、执行点拒绝、旧快照与新 Run 新版本。`uv run pytest -m "not live and not docker" -q` 退出码 0，37 passed/3 deselected；`uv run ruff check .`、`uv run ruff format --check .`、`uv lock --check` 通过。
- 真实模型回归：`uv run python labs/live_model_smoke.py` 使用 `openai_compatible/gpt-5.6-sol`，真实 add 工具结果为 5、两次模型尝试、usage 和增量流均可用，输出 `LIVE: PASS`。M3 的恶意猜工具验收使用确定性模型，避免把提供商偶然选择当作权限证明。
- 验收状态：M3-01、M3-02 PASS。M3-03 的核心快照语义已通过“旧状态继续使用 BODY_V1、新 Run 读取 BODY_V2”测试，但尚未按验收原文跑“waiting_input 中改磁盘再恢复”的 API 组合场景，记为 NOT_RUN；M3-04、M3-05 属于 M3.3～M3.4，未开始。
- 用户的预测、实验、复述反馈：待反馈；M3.1/M3.2 理解状态为 AWAITING_FEEDBACK，技术测试通过不能改成 VERIFIED。
- 下一步：留给用户运行 `labs/m3_skills_demo.py`、添加一个本地 Skill 并提问；不自动进入 M3.3。

## M3.3～M3.4 实现与学习记录（2026-10-13）

- 单元与范围：M3.3 将超过 `context.tool_preview_bytes` 的完整工具文本外置，并给模型保留有界预览、SHA-256、大小、只读虚拟路径和 `read_file` 分页提示；M3.4 按上下文预算摘要旧消息，同时保存业务 UI 历史。没有实现子 Agent、前端或 M4 功能。
- 参考源码路径 / 符号 / HEAD：`D:\Forksourcefolder\deer-flow\backend\packages\harness\deerflow\agents\middlewares\summarization_middleware.py::DeerFlowSummarizationMiddleware`、`_prepare_compaction`、`compact_state`、`acompact_state`、`_preserve_required_context`，并对照 `backend/tests/test_summarization_middleware.py`。HEAD `5c3329afadfd8f65fd2fc3f8665069759218b704`；目标文件无本地 diff。
- 原版与精简映射：DeerFlow 保留“先划分旧消息/保留消息、摘要成功后才删除、救回当前用户消息”的关键语义，并另有模型选择、fallback、记忆、PII、遥测和更完整的任务连续性处理。AgentLoom 只保留单模型、近似 token 预算、最近两组完整 AI tool calls + 对应 ToolMessages、当前用户任务与业务 State；增加适合本项目的 `tool-results` 引用和压缩前 UI 归档。
- 大输出数据流：`ToolResultMiddleware` 在工具真正返回后检查 UTF-8 字节数；超限内容由 `WorkspaceService.store_tool_result` 原子写入 `/mnt/user-data/tool-results/<run_id>/...`，该命名空间不能由普通文件工具写入，Docker 中也只读。进入 checkpoint、账本和下一轮模型的是 JSON 预览与引用；`read_file(start_char,max_chars<=512)` 可继续分页消费完整内容。单文件上限 10 MiB，超过时返回明确工具错误。
- 压缩数据流：`ContextCompactionMiddleware` 把消息、工具 schema、既有摘要、Todo、artifact IDs 和活动 Skill 快照一起估算；达到比例阈值后，只摘要可安全移除的旧单元。AI 工具调用及其连续 ToolMessages 是不可拆单元，重复 ToolMessage 也随所属组一起处理；保留当前 Human 和最近两组完整工具消息。摘要成功后才发出 `RemoveMessage(REMOVE_ALL_MESSAGES)` 并写入新摘要；摘要失败保留原消息。
- UI 与状态：将从 checkpoint 上下文移出的 assistant/tool 消息先通过 `RunManager.archive_messages` 幂等写入 `app.sqlite`，因此模型上下文变短不等于删除 UI 历史。`summary_text` 由 Skill context 注入下一轮 system prompt；Todo、artifact IDs、活动 Skill 正文/hash 仍是独立 State 字段，不依赖被摘要的消息文本。
- 共享预算与终止：摘要直接使用正式模型对象，并写入 LangChain `ModelCallLimit` 使用的 `run_model_call_count/thread_model_call_count`。达到 Run 上限后不会再发起摘要；摘要失败若仍低于硬窗口，保留消息继续，若已无法容纳下一次请求则显式让 Run 失败。摘要不递归触发自身。
- 实际成功轨迹：`uv run python labs/m3_context_demo.py` 退出码 0；4 次大工具结果均被外置，预览为 256 字节，摘要调用 2 次，总模型尝试 7 次，UI 仍含 1 user + 5 assistant + 4 tool，4 个完整文件存在，输出 `M3.3/M3.4 DEMO: PASS`。
- 实际失败轨迹：确定性 API 测试让摘要固定抛出 `planned summary failure`。前三次正式调用后，失败摘要计作第 4 次，下一次正式调用计作第 5 次；再进入压缩时因共享预算耗尽而停止，Run 为 `failed`、`usage.model_attempts=5`，原消息未被摘要删除。开发中还实际发现 Windows 临时路径过长导致外置失败，已把同目录临时文件改为短随机名并通过回归。
- 离线验证：`uv run pytest tests/test_m3_context.py -q` 退出码 0，5 passed；覆盖完整结果经 `read_file` 真正消费、重复结果组边界、失败不删消息、共享预算终止、API UI 历史与计量。`uv run pytest -m "not live and not docker" -q` 退出码 0，42 passed/3 deselected；`uv run ruff check .`、`uv run ruff format --check .`、`uv lock --check` 均通过。
- 环境/真实验证：`uv run python labs/live_model_smoke.py` 退出码 0，当前 `openai_compatible/gpt-5.6-sol` 真实 add 工具结果 5、两次模型尝试、usage 与模型增量流可用，输出 `LIVE: PASS`。该 smoke 是正式链兼容回归，不伪装成强制压缩评测；M3-04/05 的边界使用可重复的确定性模型。`uv run pytest -m docker -q` 为 3 skipped/42 deselected，因为当前 shell 找不到 `docker` 命令，本轮 Docker 挂载实测记 NOT_RUN；离线创建参数契约已验证 `tool-results` 只读挂载。
- 验收状态：M3-04、M3-05 PASS。M3-03 仍保持上一单元记录的 NOT_RUN，不因本轮技术通过而改写。M3.3/M3.4 实现状态 DELIVERED。
- 用户的预测、实验、复述反馈：待反馈；M3.3/M3.4 理解状态为 AWAITING_FEEDBACK，技术测试通过不能改成 VERIFIED。
- 下一步：留给用户运行 `labs/m3_context_demo.py`，修改预览阈值或调用次数后观察；不自动进入 M4。

## M0～M3 验收审查与修复（2026-10-14）

- 审查范围：按 `ACCEPTANCE.md` 复核当前已经实现的 M0～M3；重点追踪工具结果是否进入下一轮模型、结构化失败是否保留、HTTP/账本幂等、审批暂停/恢复、崩溃恢复和取消资源收尾。M4～M6 未实现，保持 NOT_RUN。
- 实际缺陷与修复：`runtime/ledger.py::tool_result_error_code` 原先先检查 `ToolMessage.status == "error"`，导致正文已有 `SKILL_TOOL_DENIED` 时仍降级为 `TOOL_RETURNED_ERROR`。现改为先解析结构化 `{ok:false,error:{code}}`，只有缺少具体 code 才回退通用错误。越权调用此前没有执行，但错误原因确实被吞掉；修复后账本保留 `SKILL_TOOL_DENIED`。
- M3-03 补验：新增完整 API 场景。旧 Run 激活允许 `replace_file` 的 `BODY_V1` 后进入 `waiting_input`；磁盘 Skill 改为 `BODY_V2` 并移除权限；恢复旧 Run 仍按 checkpoint 快照成功执行一次。新 Run 重新加载 V2，同一工具在执行点被拒绝、没有审批卡、文件不再变化，账本为 `failed / SKILL_TOOL_DENIED / attempts=1`。M3-03 从 NOT_RUN 更新为 PASS。
- 工具消费与失败：真实 `gpt-5.6-sol` 调用 `add` 得到工具结果 5 后回答“2 + 3 = 5”；真实缺失文件场景调用 `read_file`，账本为 `failed / FILE_NOT_FOUND`、事件含 `tool.failed`，模型明确回答文件不存在，Run 在模型处理失败后正常 `succeeded`。这与“工具本身成功”是两种状态，没有把失败写成成功工具执行。
- 请求幂等：真实 API 使用同一 `client_request_id` 和正文并发/重复提交得到同一 Run；不同正文为 409。完成后再次提交没有增加消息或事件，实际只有 1 次工具执行。
- 审批与恢复：真实模型先 `read_file` 获取 hash，再提出 `replace_file`，Run 进入 `waiting_input`；批准后沿同一 Run/checkpoint 完成，文件从“第一版”变为“第二版”，两个工具各执行一次。进程崩溃后的 `uncertain`、证据 verify/skip 和不盲重放仍使用确定性故障注入验证，因为真实 provider 不能可靠制造“副作用完成但账本提交前崩溃”的精确时点。
- 取消：真实模型提出 `bash sleep 30`，批准后真实容器进入运行；取消得到 Run `cancelled`，账本 `cancelled / RUN_CANCELLED / attempts=1`，按 run_id 查询无遗留容器。确定性测试另验证等待审批时取消会补齐 ToolMessage，下一 Run 可正常开始。
- Docker：CLI 为 `E:\Apps\DockerDesktop\resources\bin\docker.exe`，Client/Engine `29.8.2`，镜像 `agentloom-python:v1` 存在。首次把 Docker 与完整 API 套件并行跑时，另一个应用 lifespan 的单进程遗留容器清理提前删除了超时测试容器，造成 1 项假失败；按产品的单用户单进程约束串行复验为 3 passed，覆盖真实写入、1 秒超时清理、资源/挂载/Secret 边界与取消。
- 离线/静态验证：`uv run pytest -m "not live and not docker" -q` 退出码 0，43 passed/3 deselected；`uv run pytest -m docker -q` 退出码 0，3 passed/43 deselected；`uv run ruff check .`、`uv run ruff format --check .`、`uv lock --check` 均通过。
- 真实验证：`live_model_smoke.py`、`live_api_smoke.py`、`live_files_smoke.py`、`live_approval_smoke.py`、`live_failure_smoke.py`、`live_cancel_smoke.py` 全部 PASS。provider 为 `openai_compatible`，模型为 `gpt-5.6-sol`；密钥值未输出，临时数据目录已清理。
- 未实现/未冒充：Run 提交仍禁止非空 `attachment_ids`，上传文件自动注入尚未实现；M4 子 Agent、M5 MCP/偏好/UI、M6 固定任务评测未实现。真实模型没有用于可重复的竞态、进程崩溃时点和上下文极限断言，这些继续由确定性模型/真实 Docker 验证。
- 学习状态：所有既有单元仍按用户实际反馈保持 `AWAITING_FEEDBACK` 或 `NEEDS_REVIEW`；本次技术验收没有自动改为 VERIFIED。

## M4.1～M4.2 实现与学习记录（2026-10-14）

- 单元与范围：M4.1 只建立 `task(agent_type, prompt, expected_outputs, input_files)` 契约、Researcher/Coder 两个固定角色和隔离边界；M4.2 只跑通一个子任务并把结果交还 Lead。没有实现 M4.3 的两个任务并发/部分失败，也没有实现 M4.4 的父取消收尾与共享硬预算。
- 参考源码路径 / 符号 / HEAD：`D:\Forksourcefolder\deer-flow\backend\packages\harness\deerflow\subagents\executor.py` 的 `SubagentStatus`（97 行）、`SubagentResult`（118 行）、`_filter_tools`（768 行）、`SubagentExecutor`（801 行）、`_create_agent`（991 行）、`_aexecute`（1530 行）与 `execute/execute_async`（2057/2087 行）；对照 `backend/tests/test_subagent_executor.py` 的真实 child graph、工具过滤、后台任务与隔离上下文测试。HEAD 为 `5c3329afadfd8f65fd2fc3f8665069759218b704`。
- 原版解决的问题：DeerFlow 为每个子 Agent 组装过滤后的工具和独立初始 State，以 `checkpointer=False` 创建 child graph，记录状态/结果/usage/工具证据，并处理授权、扩展、后台任务、超时、取消和进程级并发。它的持久隔离事件循环、动态 MCP/Skill/扩展、复杂授权和证据收集没有复制到当前精简单元。
- 精简映射：`subagents/contracts.py` 固定请求与结构化结果；`subagents/executor.py::SubagentExecutor.execute` 构造只含任务描述、期望输出和输入快照的新消息列表，用角色白名单过滤真实工具对象，并明确不向 child 提供 `task`、Bash、审批、账本或父可变 State；`subagents/repository.py` 用 `(run_id,parent_tool_call_id)` 持久化 queued→running→succeeded/failed 及三条事件；`tools/task.py::task` 把有界结果作为同一 tool_call_id 的 ToolMessage 和 `delegations` 摘要送回 Lead。
- 工作区隔离：输入文件先复制为 task 内只读 `uploads/{hash-prefix}/...` 快照；Coder 的 `/mnt/user-data/workspace` 实际映射到父线程的 `tasks/{task_id}/workspace`。Coder 可新建文件并使用 `replace_task_file` 做 hash 前置替换，但没有 `replace_file`、`present_files` 或 `bash`；生成文件仍是私有候选，不冒充已发布 Artifact。
- 状态与可信度：`LoomState.delegations` 按 task ID 合并并最多保留 4 条；普通新 Run 显式清空，审批恢复沿 checkpoint 保留。即使 child 文本声称“测试已经通过”，结果契约也固定 `acceptance.tests_passed=unverified`；M4-04 PASS。
- 确定性成功轨迹：Lead `task(delegate-1)` → Coder 只读父文件快照 → child 内部 `list_dir/list_dir/read_file/write_file` → `subagent_tasks=succeeded` → Lead 只收到一条 `task` ToolMessage 并汇总。`child.txt` 实际位于 `threads/{thread_id}/tasks/{task_id}/workspace/`，父 `workspace/child.txt` 不存在；child 内部四条工具消息没有进入父 UI 历史。
- 确定性失败轨迹：child 模型抛出 `RuntimeError("injected child failure")` → 执行器生成 `status=failed`、结构化错误并写入数据库 → `task` 返回 error ToolMessage → Lead 明确读到失败后正常结束。父 Run `succeeded` 只表示 Lead 已正确处理失败，不会把子任务行改成成功。
- 测试通过：`uv run pytest -q tests/test_m4_subagents.py` 退出码 0，2 passed；`uv run pytest -q` 退出码 0，48 passed；`uv run ruff check .`、`uv run ruff format --check .`、`uv lock --check` 均退出码 0；`python -m compileall` 退出码 0。
- 真实模型：`uv run python labs/live_subagent_smoke.py` 退出码 0；`openai_compatible/gpt-5.6-sol` 实际完成 `Lead → task → Researcher → add(21,21) → 结果 42 → Lead`，父工具历史只有 `task`，子任务事件为 queued/started/finished，Run usage 为 4 次模型尝试、1 次父层工具执行、2211 input/207 output token，输出 `LIVE SUBAGENT: PASS`。
- 尚未验收：M4-01 的“两任务并发、并发上限和每 Run 委派总量”、M4-02 的“一成功一失败兄弟任务”、M4-03 中结构化 `requires_parent_action` 完整流程以及 M4-05 的父取消/重启清理都留给 M4.3～M4.4。当前 usage 已能记录 child token，但 child 工具执行尚未纳入共享硬工具预算，不能提前声称完整 M4 通过。
- 用户的预测、实验、复述反馈：待反馈；M4.1/M4.2 保持 AWAITING_FEEDBACK，技术测试和真实模型通过不能改成 VERIFIED。
- 下一步：留给用户运行 `uv run python labs/live_subagent_smoke.py` 或修改确定性实验，并回答本单元理解问题；不自动进入 M4.3。

## M4.3～M4.4 实现与学习记录（2026-10-14）

- 单元与范围：M4.3 完成并发、部分失败和子任务总量控制；M4.4 完成父取消、进程重启收尾、完成结果复用及 Lead/child/摘要共享模型与工具硬预算。本轮没有实现 M5 的 MCP、偏好或前端。
- 参考源码路径 / 符号 / HEAD：`D:\Forksourcefolder\deer-flow\backend\packages\harness\deerflow\subagents\executor.py` 的 `SubagentExecutor`（801 行）、`_create_agent`（991 行）、`_aexecute`（1530 行）、`execute_async`（2087 行）及取消/后台任务清理段（2181 行起）；对照 `backend/tests/test_subagent_executor.py` 的容量、超时与取消测试。HEAD `5c3329afadfd8f65fd2fc3f8665069759218b704`。
- 原版与精简映射：DeerFlow 使用进程级 admission controller、独立持久事件循环、sandbox lease、动态扩展/MCP/Auth 和更完整的 trace/evidence。AgentLoom 保留同一事件循环的 async child、全进程 semaphore、排队计入超时、兄弟失败隔离、父取消传播和结构化结果；继续使用两个固定角色、SQLite 业务行和单进程边界，不复制原版的扩展系统。
- 并发与总量：`SubagentExecutor` 在进入 child graph 前登记活动任务，`asyncio.Semaphore(2)` 限制全进程同时运行数；`SubagentTaskRepository.prepare` 在短事务中按 Run 计数，超过 4 个返回稳定错误 `SUBAGENT_LIMIT_EXCEEDED`。child schema 没有 `task`，模型猜出名称也只得到未知工具错误，不会创建嵌套子任务。
- Coder 边界：Coder 在 task 私有 workspace 内写文件成功；路径逃逸在真实执行点返回 `PATH_OUT_OF_SCOPE`，schema 中没有 Bash。需要验证时只能调用 `request_parent_action` 形成 `{"tool":"bash","command":"pytest -q"}`，由 Lead 后续决定是否进入正常审批；子 Agent 的“测试通过”自述仍固定为 `unverified`。
- 取消与重启：HTTP 取消先把 Run CAS 为 `cancelling` 并取消父图，接口无需持有完整执行过程；取消沿工具任务传播到所有 child，后台等待子任务写入 `cancelled` 后统一清理账本/容器，最后写 `cancelled`。应用启动时 queued/running child 统一转为 `interrupted / PROCESS_RESTARTED`，对应父 Run 转为 interrupted；相同 `(run_id,parent_tool_call_id)` 的已完成结果直接复用，不再次请求模型。
- 共享硬预算：`RunBudgetController` 在真实模型请求和业务工具处理器入口原子预留名额；同一实例通过 `LoomContext` 传入 Lead、child 和摘要中间件。达到上限时在调用前抛出 `RUN_BUDGET_EXCEEDED`，不会再请求供应商或执行工具；usage 使用该共享计数，Token 仍由 callback 汇总。
- 实际失败与修复：首次并行测试触发 `UNIQUE constraint failed: run_events.run_id, run_events.seq`，因为两个 SQLite 短事务读到相同事件序号；现由 repository 的短写锁串行分配子任务生命周期事件，模型/工具执行仍并发。首次取消测试还停在 `cancelling`，原因是先取消 child 后父 Task 可能已经结束并漏掉最终收尾；现正常路径只取消父 Task，由 `_execute` 后台收尾，父 Task 已消失的竞态使用受 lifespan 管理的补偿清理 Task。
- 确定性轨迹：Lead 同轮提出 NEST/FAIL/OK-2/OK-3，峰值活动 child 为 2；FAIL 保存 failed，三个兄弟 succeeded，NEST 的 child 无 `task` 权限；随后第 5 个委派返回 `SUBAGENT_LIMIT_EXCEEDED`，父历史只有五条 `task` ToolMessage，没有 child 内部消息。另一个测试取消两个阻塞 child 后，两个数据库行和父 Run 均为 cancelled，活动任务与开放工具账本为 0。
- 测试通过：`uv run pytest -q tests/test_m4_subagents.py` 退出码 0，7 passed；`uv run pytest -m "not live and not docker" -q` 退出码 0，50 passed/3 deselected；`uv run pytest -q` 退出码 0，53 passed（包含 3 项 Docker 集成回归）；`uv run ruff check .`、`uv run ruff format --check .`、`uv lock --check` 均退出码 0。M4-01～M4-05 均有确定性证据；精确重启/取消时点由 fake 故障注入验证。
- 真实模型：`uv run python labs/live_subagent_parallel_smoke.py` 退出码 0；`openai_compatible/gpt-5.6-sol` 实际完成两个 Researcher 委派和两个 child `add`，摘要分别含 21/42；事件为两个 queued、两个 started、两个 finished；共享 usage 为 6 次模型尝试、4 次工具执行、2944 input/299 output token，`complete=true`。
- 用户的预测、实验、复述反馈：待反馈；M4.3/M4.4 记录为 AWAITING_FEEDBACK。以上技术验收通过不代表用户理解已验证。
- 下一步：留给用户运行实验、阅读关键代码和提问；不自动进入 M5。

## M5.1～M5.2 实现与学习记录（2026-10-14）

- 单元与范围：M5.1 实现一个仓库内受信任、只读的 `reference_library` stdio MCP Server，并把发现出的工具接入现有 Agent/工具账本；M5.2 启用显式偏好审批、仓储、API、请求时注入和版本控制。本轮没有创建 React 前端，也没有实现 M5.3～M5.4。
- 参考源码路径 / 符号 / HEAD：`D:\Forksourcefolder\deer-flow\backend\packages\harness\deerflow\mcp\tools.py::_make_session_pool_tool`（534 行）、`get_mcp_tools`（841 行）、`MultiServerMCPClient/load_mcp_tools` 加载段（858 行起）和逐 Server 发现段（914 行起）；辅助阅读 `mcp/AGENTS.md`。偏好对照 `agents/memory/AGENTS.md` 的 manager/middleware/tools 分工、用户作用域与 409 冲突约定。HEAD `5c3329afadfd8f65fd2fc3f8665069759218b704`；参考仓库只有与本单元无关的未跟踪交接材料。
- 原版与精简映射：DeerFlow 支持多 Server、stdio/SSE/HTTP、会话池、用户凭证/OAuth、动态缓存、MCP Tasks、多个 memory backend、自动捕获和多用户隔离。AgentLoom 只保留一个启动时配置的本地 stdio Server、一个持久 `ClientSession`、有界发现/调用、稳定来源和关闭清理；偏好只保存 `scope_key=local/category=preference` 的用户确认内容，不复制自动记忆抽取、语义搜索和远程 backend。
- MCP 数据流：FastAPI lifespan 先准备 checkpoint，再由 `McpManager.start()` 启动当前 uv Python 的独立子进程，执行 MCP initialize/tools/list，并用锁定的 `langchain-mcp-adapters` 转成 LangChain tools。公开名称固定为 `mcp__reference_library__<tool>`；调用结果带 `source=mcp:reference_library`，再经过既有 ToolNode、预算、账本、大结果外置与模型第二轮消费。`GET /api/tools` 只返回名称、描述、来源与有限诊断，不返回命令、环境或宿主路径。
- MCP 失败与生命周期：初始化失败/超时使该来源状态变为 `unavailable`，应用仍保留内置工具；单次调用受 `call_timeout_seconds` 约束，返回结构化 `MCP_TIMEOUT` 并由账本记为 failed。关闭 lifespan 会退出 `ClientSession/stdio_client` 并终止子进程。MCP 工具当前按只读登记；首版不接受聊天提供任意启动命令，也不实现远程动态 Server 和 OAuth。
- 偏好数据流：模型调用 `remember_preference(memory_key,content,expected_version)` 后，`ApprovalMiddleware` 在任何工具执行前把整批参数/hash 写入 app.sqlite 并进入 `waiting_input`。用户批准后恢复同一 Run；工具执行点再次按 run、tool_call_id 和规范化完整参数核对批准记录，才由 `MemoryService` 新建或按版本更新 active 记录。拒绝时没有偏好写入。用户也可通过 `POST /api/memories` 明确创建。
- 注入与删除：`PreferenceContextMiddleware` 在每次模型请求前只查询 active 且未过期记录，以带边界的 JSON system 段注入；该投影不写入 LangGraph State/checkpoint，也明确不能授予工具权限。`PATCH/DELETE` 必须提交 `expected_version`；成功递增版本，过期版本返回 409 `MEMORY_VERSION_CONFLICT`，删除是软删除且后续请求不再注入。
- 实际失败与修复：第一次定向测试的四个 Run 全部在模型调用前失败，错误为 `PydanticUndefinedAnnotation: name 'MemoryService' is not defined`。原因是 `LoomContext` 的前向类型只在 `TYPE_CHECKING` 导入，Pydantic 运行时生成 context schema 时仍会解析它；现把这种仅由服务端注入且不进入工具参数 schema 的句柄保持为不展开的运行时类型。随后全套收集又暴露 `memory.__init__` 同时导入 middleware/tools 造成循环导入，已收窄公开包入口并改为具体模块导入。修复后对应测试和全套回归均通过。
- 确定性成功/失败轨迹：真实独立进程 `tools/list` 发现 `search_references/get_reference`；Agent 调用 `mcp__reference_library__search_references(query=mcp,limit=1)`，模型收到包含 `local://reference-library/mcp-protocol` 的 ToolMessage，账本 `succeeded/attempts=1`。缺失 Server 脚本产生 `MCP_UNAVAILABLE` 后同一应用的 `add` 仍成功；慢 Server 调用在 50ms 返回 `MCP_TIMEOUT`，下一线程 `add` 成功，TestClient 退出后子进程 PID 不再存活。偏好测试验证批准前列表为空、批准后 version=1、新线程注入、更新 version=2、旧 version 更新 409、删除 version=3 且再开线程不注入。
- 离线/静态验证：`uv run pytest -q tests/test_m5_mcp_memory.py` 退出码 0，4 passed；`uv run pytest -q -m "not live and not docker"` 退出码 0，54 passed/3 deselected；`uv run ruff check src tests labs`、`uv run ruff format --check src tests labs`、`uv lock --check` 均通过。M5-01、M5-02、M5-03 为 PASS。
- 真实模型验证：`uv run python labs/live_mcp_memory_smoke.py` 退出码 0；本机 `openai_compatible/gpt-5.6-sol` 实际调用 `mcp__reference_library__search_references` 并消费受控来源，随后提出 `remember_preference`、进入审批、批准后保存 version=1，新线程成功复述简体中文偏好，输出 `LIVE M5: PASS`。密钥值未输出，数据使用临时目录并已清理。
- 未实现/未冒充：M5.3 消息/事件页面、M5.4 审批/任务/文件面板、M5-04/05/M5-UI 均为 NOT_RUN；当前没有远程 MCP、动态管理、OAuth、自动抽取记忆、RAG 或多用户记忆。
- 用户的预测、实验、复述反馈：待反馈；M5.1/M5.2 均保持 AWAITING_FEEDBACK，技术测试和真实模型通过不能改成 VERIFIED。
- 下一步：留给用户运行 `uv run python labs/live_mcp_memory_smoke.py`、修改一条偏好并观察 version/新线程行为，或继续提问；不自动进入 M5.3。

## M5.3～M5.4 实现与学习记录（2026-10-15）

- 单元与范围：M5.3 完成消息、Run 状态、usage 与事件时间线；M5.4 完成审批、Todo、子任务、工具账本、上传、产物预览与下载。为让页面完整任务真正消费上传文件，同时补齐线程/文件/子任务 REST 读取接口和 attachment 注入；没有进入 M6 评测、图编辑器、模型市场或设置中心。
- 参考源码路径 / 符号 / HEAD：`D:\Forksourcefolder\deer-flow\frontend\src\core\threads\hooks.ts::useThreadStream`（1862 行起及 2169 行 task_id 归属）、`core/threads/stream-state.ts::reduceThreadStateUpdates`（108 行，明确让 SDK `messages-tuple` 管理同 ID 覆盖）、`components/workspace/messages/subtask-card.tsx::SubtaskCard`（48 行）、`components/workspace/artifacts/artifact-file-preview.tsx` 的 sandbox iframe（256 行）及 `core/streamdown/plugins.ts::rehypeSanitizeStep`（87 行）。HEAD `5c3329afadfd8f65fd2fc3f8665069759218b704`。
- 原版与精简映射：DeerFlow 是 Next.js/React 19 大型前端，依赖 LangGraph SDK 管消息块合并、兼容多种流事件、sidecar 和复杂产物渲染。AgentLoom 保留同消息 ID 最终覆盖、子任务按 task_id 归属、事件可回放、刷新走 REST 和不可信内容隔离；改用 Vite、TanStack Query、原生 EventSource 与一个小型 reducer，不复制 Next.js 路由、旧事件兼容层、图编辑器或扩展市场。
- 消息与事件数据流：`App.tsx` 首次按 URL 中 thread ID 请求线程、消息和最新 Run；`use-run-events.ts` 订阅当前 Run 的持久 SSE；`run-state.ts` 以 `(run_id,seq)` 去重，`message.delta` 只追加 partial，`message.completed` 按 message_id 覆盖，completed 后的迟到 delta 被忽略。刷新时 URL 和 REST 完整投影恢复页面，不调用 submit；SSE 只回放事件。工具原始消息不重复堆在对话区，完整结果从工具账本卡查看。
- 审批、任务与文件：审批卡展示数据库冻结的 action/args/hash，`checkpoint_ready=false` 时按钮禁用，批准/拒绝只提交 decision 和原 payload_hash。右栏从 REST 恢复 Todo、子任务和工具账本；上传先成为当前线程 upload artifact，提交时后端复核 artifact 归属和 kind，再把虚拟路径元数据加入模型 HumanMessage 上下文，原始 UI 消息只保留正文和 attachment_ids。输出必须经 present_files 成为不可变 artifact 才进入文件列表。
- 安全预览：Markdown 使用 `react-markdown + remark-gfm + rehype-sanitize`，没有启用原始 HTML 解析；HTML 只进入 `sandbox=""` 且无 `allow-scripts/allow-same-origin` 的 iframe，并保留下载入口。单测验证 Markdown script 不进入工作台 DOM、HTML 脚本只存在于不可信 `srcdoc` 且无法取得工作台同源权限。
- 后端补充：`GET /api/threads`、`GET /api/threads/{id}`、`GET /api/threads/{id}/artifacts`、`GET /api/runs/{id}/subagents` 提供刷新恢复；上传响应统一含 content_url。`RunManager.submit` 将 attachment_ids 纳入幂等 hash，拒绝不存在/跨线程/非 upload ID，并冻结名称、虚拟路径、MIME 与 SHA-256；`RunExecutor` 只把这份服务端元数据注入模型输入。
- 实际失败与修复：pnpm 12 第一次安装因供应链策略拒绝 `esbuild` 安装脚本（`ERR_PNPM_IGNORED_BUILDS`），现由 workspace `allowBuilds` 只批准 esbuild；第一次构建因 Vitest 3 间接带入 Vite 7，与 Vite 8 plugin 类型冲突，升级到支持 Vite 8 的 Vitest 5.0.4 后恢复。浏览器首轮还发现 favicon 404 和工具原始消息挤满主对话，已补 data favicon，并把工具结果保留在账本/时间线而不重复渲染为聊天正文。
- 确定性 UI 轨迹：Playwright CLI 上传 `sales.csv`（2 行、数值合计 100）并发送“分析附件并生成报告”；fake 模型经真实图依次调用 `read_file`、`write_file`，页面在 `replace_file` 前显示参数并进入 waiting_input；批准后同一 Run 恢复，执行 `replace_file`、`present_files`，最终状态 succeeded，5 次模型尝试/4 次工具执行。页面预览并下载 `report.md`，reload 后从 REST 恢复同一消息、10 条轨迹、4 条工具账本和产物，没有创建第二个 Run。截图为 `output/playwright/m5-workbench-final.png`，下载内容保存为 `.playwright-cli/report.md`。
- 离线/静态验证：后端 `uv run pytest -q` 为 55 passed/3 skipped；跳过的 3 项是当前 Docker Engine 未运行导致的既有恢复集成项，历史 Docker PASS 仍保留。`uv run ruff check .` 与 `uv run ruff format --check .` 通过。前端 `npx --yes pnpm@12.11.2 test` 为 5 passed，`build` 生成 438.52 kB JS/16.24 kB CSS，`lint` 通过。M5-04、M5-05 为 PASS。
- 真实模型与 M5-UI：`uv run python labs/live_api_smoke.py` 使用 `openai_compatible/gpt-5.6-sol`，真实 Run succeeded、重复请求 same_run、冲突 409、2 次模型尝试/1 次工具执行、1662 input/33 output token，输出 `LIVE API: PASS`。完整浏览器数据分析/审批/下载使用 `labs/m5_ui_demo_server.py` 的可预测 fake 模型，但 API、SQLite、LangGraph、工具、审批恢复、SSE 和产物服务均为正式实现，M5-UI 记为 fake 模式 PASS，没有冒充 live UI。
- 原版与精简版的取舍：保留 DeerFlow 的三栏工作形态、消息稳定 ID、任务归属、刷新恢复和安全产物入口；精简为单用户/单进程、两种右栏 tab 和已知事件白名单。首版 EventSource 不实现任意插件事件动态注册；未知事件仍在数据库中，但不会进入前端 reducer，后续新增事件类型时必须同步白名单和测试。
- 用户的预测、实验、复述反馈：待反馈；M5.3/M5.4 均保持 AWAITING_FEEDBACK。技术验收和浏览器轨迹不能把用户理解改成 VERIFIED。
- 下一步：留给用户按 frontend README 启动、上传自己的 CSV、在审批页观察 Run 暂停/恢复并刷新页面；本轮停在 M5.4，不自动进入 M6。

## M6.1～M6.4 实现与学习记录（2026-10-15）

- 单元与范围：M6.1 建立固定任务与预注册验收；M6.2 跑完整真实评测并保留失败/人工复核；M6.3 用相同模型、工具 schema、MCP 数据和预算做单/多 Agent 三次重复对照；M6.4 完成干净安装、README、架构/能力证据和演示讲稿。本轮没有增加业务模块或进入新的里程碑。
- 参考源码路径 / 符号 / HEAD：`D:\Forksourcefolder\deer-flow\backend\tests\test_thread_state_reducers.py` 的 reducer 行为和 `get_type_hints(..., include_extras=True)` 字段接线断言；`D:\Forksourcefolder\deer-flow\backend\tests\test_run_manager.py` 的 `FlakyStatusRunStore`、`LostLeaseRunStore`、取消/租约/清理故障注入。HEAD `5c3329afadfd8f65fd2fc3f8665069759218b704`。
- 原版解决的问题：DeerFlow 测试预先声明状态不变量，再制造重复、冲突、租约丢失和取消交错；它验证 reducer 确实挂到 State 字段、失败时资源与业务错误仍符合约定，而不是只调用一次函数看是否报错。AgentLoom 没有复制原测试，而把同一方法用于任务验收、失败保留、干净安装和既有恢复回归。
- 精简映射：`evaluation/schema.py` 定义严格任务/观察/检查契约；`runner.py::EvaluationRunner` 逐题走正式 HTTP/后台执行链并自动处理已就绪审批；`grading.py` 只按运行前条件评分并聚合完成率、Artifact、工具账本、wall/active time、Token 和波动；`report.py` 输出 Markdown。任务文件与报告分离，原始 live 输出放在被忽略的 `output/`。
- 任务集：`fixed_tasks.json` 恰好 30 项，文件/代码 10、数据 8、检索/MCP 6、委派 6，SHA-256 为 `5df9127b7197e30794f834a7921c94f5e668ef09a728542f8d5ddd9225ad5b4b`。每项在模型运行前声明文本、工具、产物、子任务数或人工复核条件；runner exception 只把该项记为 error 并继续整批。
- 真实完整结果：`openai_compatible/gpt-5.6-sol` 运行 30 个独立 Run，25 自动通过、3 待人工复核、2 自动失败；Artifact 交付率 100%，工具账本接纳率 100%，总 wall/active 616.11s，input/output Token 145,364/8,484，usage complete=true。FC-09、DA-08、AG-06 人工复核均通过，因此最终任务完成 28/30（93.3%）。
- 失败保留：RT-02 回答“只能有 1 个写者”但条件要求“一个写者”；RT-06 回答“未找到任何匹配项”但条件只列四种其他表达。事实语义正确但字面评分失败；本次没有看完输出后改条件或覆盖结果，记录为评分规则敏感性。
- 对照与归因：`comparison_tasks.json` 两对任务、每种策略三次，共 12 个 live Run，全部通过。single 6 Run 为 8.40±1.64s、1798±74 Token；multi 6 Run 为 15.53±5.15s、2898±201 Token。对这组短任务，委派增加约 85% 延迟和 61% Token，没有提升完成率；不能外推到复杂并行任务。
- 实际失败与修复：首次三题 live 冒烟 Run 均 succeeded 且工具已执行，但最终文本为空。原因是 provider 返回内容块列表，`runtime/projection.py` 只保存 blocks，fake 字符串测试未覆盖。现同时保存 `message.text` 与原始 blocks，增加回归测试；同三题重跑由 0/3 变为 3/3。修复前后 JSON 均保留在本机 `output/evaluation/`。
- 干净安装失败与修复：隔离副本不含本机配置时，旧 `test_local_files_are_ignored` 强制要求 `config.yaml/.env` 存在，得到 59 pass/1 fail；现改为要求可提交 example 存在且本机文件被忽略。新复制 `.venv` 的首次 `import agentloom.api` 因本机安全扫描耗时约 376 秒，旧 300 秒 uvicorn 探针错误归因为启动失败；现先用 900 秒有界 import 预热，再单独给应用 300 秒。pnpm 首次安装也改为 900 秒，日志写文件避免 PIPE 阻塞。
- 干净安装 PASS：fresh 命令创建并安装独立 Python 3.12 副本，修正门禁后用 `--reuse` 在同一无 Secret 副本完成 Alembic、显式 import、正式 uvicorn lifespan及 `/api/threads` 200；后端 60 passed/3 Docker 标记项按该命令排除；前端 lint、5 tests、生产 build PASS。证据目录为 `output/clean-install/workspace-1792074795`，不包含本机配置或原数据库。以后 fresh 运行创建带时间戳目录，不同步删除旧 node_modules。
- 最终回归：`uv run pytest -q` 为 63 passed，包含当前可用 Docker Engine 的 3 项真实容器测试；`ruff check`、`ruff format --check`、`uv lock --check` 通过。前端 `pnpm check` 为 lint + 5 passed + build；文档链接检查 PASS。
- 文档交付：根 README 已覆盖安装、配置、启动、测试、评测、三个演示与限制；`docs/M6_EVALUATION.md` 保存可提交结果，`ARCHITECTURE.md` 区分框架/协议与自主实现，`CAPABILITY_EVIDENCE.md` 映射可陈述能力，`DEMO_SCRIPT.md` 固定 2～3 分钟录制步骤。实际视频文件没有生成，状态为 NOT_RECORDED，未冒充交付。
- 用户的预测、实验、复述反馈：待反馈；M6.1～M6.4 保持 AWAITING_FEEDBACK。技术验收和真实模型数据不能自动把用户理解改为 VERIFIED。
- 下一步：用户可用 `--ids FC-01,RT-01,AG-01` 运行三个 live 子集，观察 JSON 中 observation/checks，再回答本轮问题或按演示脚本录屏；不自动增加 M7 或扩展产品范围。

## 已验证的交接材料

- schema.sql 在内存 SQLite 中可以建立九张业务表。
- 检查同线程未结束 Run 唯一、request ID 唯一、事件序号、tool call 去重、审批 checkpoint 前置条件、跨线程消息/跨 Run 产物外键。
- 包内文档使用相互引用；UPSTREAM.md 中的原项目代码路径作为学习依据，不参与构建。
- 2026-10-05 已核对当前仓库 HEAD、factory 的实际组装调用与 State 定义，以及阅读地图相关入口；这不代表用户已经阅读或理解。
- 2026-10-05 文档检查通过：十文件清单、37 个包内相对链接、22 个原仓库路径、19 个源码符号；未修改的 DDL 再次在内存 SQLite 建立九表，外键检查通过。

这些是交接包检查，不是 M0～M6 应用测试通过记录。

## 当前任务清单

- [x] 核对新目录位置和参考目录可读性；记录当前代码版本。
- [x] M0.0 带读 create_deerflow_agent / ThreadState，保留理解问题待反馈。
- [x] M0.1 检查 Python、uv、网络并实现最小 CLI。
- [x] M0.2 实现图与工具循环；用户修改输入的学习验证待反馈。
- [x] M0.3 增加失败/终止并运行相关验收；用户实验待反馈。
- [x] M0.4 记录依赖兼容性 smoke 与锁文件；M0.5 脚本已备，真实模型运行待配置。
- [x] M1.1 用 `create_agent` 组装正式离线 Agent，磁盘 checkpoint 与精简 State 已验证。
- [x] M1.2 一次 Alembic 九表基线迁移，先启用四张业务表的映射和提交读写。
- [x] M1.3 Run 提交、幂等、同线程排他与 HTTP 查询；用户实验待反馈。
- [x] M1.4 Run 自动执行、事件读取与可重连 SSE；用户实验待反馈。
- [x] M1.5 幂等取消、终态竞争与基础计量；用户实验待反馈。
- [x] 复审当前 M0/M1 验收：接入运行预算、补工具失败事件、加强幂等回归，并完成真实模型与真实 API smoke。
- [x] M2.1 线程工作目录与受控文件访问；M2-01 PASS，用户实验待反馈。
- [x] M2.2 上传、产物快照、登记和下载；M2-07 PASS，用户实验待反馈。
- [x] M2.3 工具执行账本、参数冲突与结果重放；用户实验待反馈。
- [x] M2.4 整批审批、重启恢复和文件旧 hash 前置检查；M2-03/04 PASS，用户实验待反馈。
- [x] M2.5 Docker/Bash、uncertain 人工处置与取消资源收尾；离线行为与真实 Docker 隔离/超时/取消均通过，用户实验待反馈。
- [x] M2.6 CSV 完整演示；真实容器生成并下载 Markdown/PNG，用户实验待反馈。
- [x] M3.1 本地 Skill 解析/发现、元数据 API 与三个内置 Skill；用户实验待反馈。
- [x] M3.2 按需加载、slash 激活、单 Skill 快照与工具权限双层校验；M3-01/02 PASS，用户实验待反馈。
- [x] M3.3 大工具结果外置、只读引用和分页读取；M3-04 PASS，用户实验待反馈。
- [x] M3.4 预算摘要、完整工具组、失败保留、UI 归档和共享模型预算；M3-04/05 PASS，用户实验待反馈。
- [x] M4.1 子任务契约、两种角色、输入快照、独立消息/State 与 Coder 私有 task 目录；用户实验待反馈。
- [x] M4.2 单子任务的持久化执行、结构化成功/失败结果与 Lead 消费；真实模型 PASS，用户实验待反馈。
- [x] M4.3 两子任务并发、总量/并发限制与部分失败；离线和真实模型 PASS，用户实验待反馈。
- [x] M4.4 父取消/重启清理与共享预算；确定性验收 PASS，用户实验待反馈。
- [x] M5.1 受信任本地 stdio MCP 的发现、调用、来源、超时隔离与进程清理；离线和真实模型 PASS，用户实验待反馈。
- [x] M5.2 显式偏好审批、active 注入、CRUD 与版本冲突；离线和真实模型 PASS，用户实验待反馈。
- [x] M5.3 消息/事件页面、SSE 去重、最终覆盖与 REST 刷新恢复；M5-04 PASS，用户实验待反馈。
- [x] M5.4 审批/任务/文件面板、附件注入、安全预览和完整 fake 浏览器轨迹；M5-05/M5-UI PASS，用户实验待反馈。
- [x] M6.1 固定 30 题、严格契约和预注册验收；失败/人工复核保留，用户实验待反馈。
- [x] M6.2 真实完整评测；25 自动通过、3 人工复核通过、2 字面规则失败，人工复核后 28/30。
- [x] M6.3 单/多 Agent 各 6 Run 对照；完成率、延迟、Token 和波动已报告并限定结论范围。
- [x] M6.4 干净安装、README、架构/能力证据和演示脚本；技术验收 PASS，实际录屏 NOT_RECORDED，用户理解待反馈。

## 测试与演示记录模板

每条记录填写：日期、阶段/验收 ID、工作目录、精确命令、退出码、PASS/FAIL/NOT_RUN、关键结果、相关文件或相对证据路径。命令未执行时不得填写成功输出。

```text
日期：
阶段 / 验收 ID：
工作目录：
命令：
状态与退出码：
结果摘要：
相关文件：
未验证项与原因：
```

## 设计决定与调整

| 日期 | 决定 | 原因 |
| --- | --- | --- |
| 2026-10-04 | 独立命名 AgentLoom，包名 agentloom | 新项目身份与可移植实现 |
| 2026-10-04 | 使用 fake/live 显式模式 | 不依赖密钥开展测试，同时不混淆模拟与真实能力 |
| 2026-10-04 | M1 一次创建九表基线 | artifacts 对 subagent_tasks 的外键要求目标表存在 |
| 2026-10-04 | Codex 按阶段实现，用户运行并理解关键行为 | 支持 AI 辅助开发与校招讲解 |
| 2026-10-04 | Coder 仅可直接修改自有 task 目录；执行交 Lead | 避免跨子图审批，同时保持代码迭代能力 |
| 2026-10-05 | 用户确认新目录实现、当前 DeerFlow 为源码参照 | 保留独立项目，同时把学习锚定在实际原实现 |
| 2026-10-05 | 默认一轮一个学习单元，取代一次完成整个里程碑 | 用户希望边学边做，留出实验与提问时间 |
| 2026-10-05 | 实现/技术验证/理解分开记录 | 防止生成代码或测试通过被当作已经学会 |
| 2026-10-06 | M0 教学图用工具调用预算终止重复请求；另设 SDK smoke | 让停止条件和真实接口兼容性可观察，避免提前建立正式执行链 |
| 2026-10-06 | 正式执行链使用 `create_agent`；M0 StateGraph 留在实验入口 | 避免在业务中长期维护两套模型工具循环 |
| 2026-10-06 | 九表 DDL 固定在 Alembic 基线，运行时与设计稿分离；app/checkpoint 分库 | 保持可重跑迁移与框架数据边界，先只启用四张业务表 |
| 2026-10-06 | 先持久化 pending Run，M1.4 再接自动 worker | 本轮只验证原子入场、幂等和排他；202 不表示模型执行完成 |
| 2026-10-06 | 正式代码按设计拆成六个职责包并移除 M0 临时执行链 | M1 已有唯一 `create_agent` 正式链，避免旧 CLI/手写图与生产结构并存 |
| 2026-10-06 | YAML 保存非敏感配置，根 `.env` 只保存本机密钥 | 配置可审查且密钥不进入仓库、State、数据库或 checkpoint |
| 2026-10-07 | Anthropic 使用 `langchain-anthropic` 原生适配器，并复用统一模型工厂与正式 Agent 链 | 保留 Anthropic Messages API 与工具调用语义，不要求服务商提供 OpenAI 兼容接口 |
| 2026-10-07 | Run task 由 FastAPI lifespan 持有，SSE 只按数据库 cursor 订阅 | 浏览器断线不应取消任务；数据库事件可以在重连后补齐 |
| 2026-10-07 | 取消与成功/失败都使用状态条件 UPDATE，事件与状态在同一短事务提交 | 保证取消和完成竞争时只有一个终态，晚到写入不能覆盖胜者 |
| 2026-10-13 | 活动 Skill 的正文、hash 与 allowed-tools 作为一个快照写入 checkpoint；新 Run 清空，恢复沿用 | 防止等待审批期间磁盘修改悄悄改变旧 Run 的指令或权限 |
| 2026-10-13 | Skill 权限同时过滤模型 schema 并在工具执行点复核；发现工具恒可用 | schema 节约上下文并减少误选，执行点阻止模型猜名绕过 |
| 2026-10-14 | 子 Agent 使用独立 child graph、固定角色白名单和 task 私有工作区；`task` 不进入 child schema | 隔离父聊天与可变 State，从结构上阻止递归委派和直接修改父工作区 |
| 2026-10-14 | 子 Agent 自述不能把 `tests_passed` 提升为已验证 | 验收事实必须来自后续真实执行证据，M4.2 尚不执行 Bash |
| 2026-10-14 | 子任务数据库生命周期只串行化短写事务，模型与工具执行由全进程 semaphore 并发 | SQLite 没有行级锁；防止并发分配重复事件序号，同时保留实际 child 并发 |
| 2026-10-14 | Lead、child 与摘要共享一个 RunBudgetController | 在真实请求/处理器入口实施每 Run 硬上限，避免每个子图各自获得一整份预算 |
| 2026-10-14 | 首版 MCP 只允许启动时配置的本地只读 stdio Server，统一加 `mcp__server__tool` 前缀 | 保留真实协议/独立进程/生命周期，同时阻止聊天注入命令并避免与内置工具重名 |
| 2026-10-14 | Agent 保存偏好必须经审批；偏好从 app.sqlite 按请求投影，不进入 checkpoint | 用户确认是长期记忆的权限边界，删除/更新可立即影响后续请求且不会污染历史图状态 |
| 2026-10-14 | 偏好更新和删除使用递增 version 与 `expected_version` | 防止旧页面静默覆盖更新后的用户偏好，冲突稳定映射为 HTTP 409 |
| 2026-10-15 | 前端用 REST 恢复完整投影、SSE 只追加当前 Run 事件，并以 `(run_id,seq)` 去重 | 刷新和断线不重新提交任务，数据库仍是可回放事实来源 |
| 2026-10-15 | Markdown 不解析 raw HTML；HTML 产物只在无脚本、无同源权限的 sandbox iframe 中预览 | 不可信文件不能在工作台 origin 执行任意脚本 |
| 2026-10-15 | 上传附件在 Run 入场时校验并冻结服务端虚拟路径元数据，再注入模型输入 | 页面选择的文件必须被模型真实消费，同时阻止跨线程 ID 或客户端伪造路径 |
| 2026-10-15 | 评测条件与原始任务集版本化，失败和人工复核不因看过输出而修改 | 防止只保留成功样本或用同义词事后放宽标准，真实显示评分器局限 |
| 2026-10-15 | 干净安装门禁复制到当前盘 output，并排除本机配置/数据/依赖 | 验证 README 可复现，同时避免 Secret 和 C 盘缓存压力进入验收环境 |

以后每次改变 API、表结构、状态语义或重要技术选择，在这里写理由，并同步相应设计和验收。不能只修改进度文件以“覆盖”冲突设计。

## 发现、阻塞与交接

系统 `python` 是 3.9.0，uv 为项目使用 CPython 3.12.11。`openai_compatible` 的真实工具、文件、审批、失败、取消、子 Agent、MCP、显式偏好和 M6 评测已通过对应路径。2026-10-15 最终检查时 Docker Client/Engine 均为 29.8.2，全套 63 项后端测试包含 3 项真实 Docker 隔离/超时/取消回归。前端 pnpm store 位于 `D:\.pnpm-store`，干净门禁另用 `output/clean-cache`；本机 Corepack shim 损坏，文档使用 `npx --yes pnpm@12.11.2`。当前安全待办仍是确认此前诊断时意外输出的旧密钥已在服务商控制台轮换。M6 技术范围完成，实际演示视频 NOT_RECORDED；下一精确起点是用户运行 M6 小实验、复述评分/对照边界或按脚本录屏，本轮不自动增加功能。

后续在此保留：未解决的问题、复现方式、已经排除的原因、可以继续的工作、需要用户补充的信息，以及下一次会话的精确起点。
