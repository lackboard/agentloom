# AgentLoom：当前 DeerFlow 源码学习地图

AgentLoom 参考 [ByteDance DeerFlow](https://github.com/bytedance/deer-flow) 的 Agent Harness 思路，包括技能渐进加载、工具循环、沙箱工作空间、中间件、子任务及上下文管理。

## 当前版本与目录

参考仓库是你当前的 `D:\Forksourcefolder\deer-flow`，2026-10-06 核对的 HEAD 为 `5c3329afadfd8f65fd2fc3f8665069759218b704`。这是本地版本记录，不代表远程最新版；若本地有修改，还需核对相关 diff。新目录中的 Codex 先验证该路径可读，并把实际路径、HEAD 与阅读位置记录到 PROGRESS.md。

下面路径均相对于这个 DeerFlow 根目录。它们是每个学习单元的源码依据；AgentLoom 安装运行不依赖这些文件。路径变化时用 rg 查符号，不把过期行号当作证据。新环境不能读到原仓库时，先说明缺失，不用远程最新代码冒充当前版本。

## 按单元阅读

| 阶段 | 当前仓库入口 / 符号 | 只带着这个问题读 | 精简版对应内容与取舍 |
| --- | --- | --- | --- |
| M0.0 / M1.1 | `backend/packages/harness/deerflow/agents/factory.py`：`create_deerflow_agent`，先看参数与最后的组装调用 | 模型、工具、State、中间件和 checkpointer 怎样组装？ | M0 显式图实验；M1 简单 factory。跳过 feature 组合、delta checkpoint 与批任务兼容分支 |
| M0.0 / M1.2 | `backend/packages/harness/deerflow/agents/thread_state.py`：`ThreadState`，再选读 `merge_artifacts` | 为什么状态要区分替换与合并？ | 本项目的精简 State；先讲 messages/Todo/产物，后续再加技能与子任务 |
| M0.2 | `backend/packages/harness/deerflow/tools/tools.py`：`get_available_tools` | 工具从哪里来，怎样交给 Agent？ | 先两个静态无副作用工具；后续扩展 ToolRegistry，不移植全部配置/插件发现 |
| M0.3 | `backend/packages/harness/deerflow/agents/middlewares/tool_error_handling_middleware.py`：`ToolErrorHandlingMiddleware`、`_build_error_message`；辅助 `agents/middlewares/loop_detection_middleware.py`：`LoopDetectionMiddleware` | 失败工具如何返回同一调用 ID？重复调用怎样有界停止？ | 工具节点返回带 `status=error` 的 ToolMessage；按工具调用预算停止，不移植原版的完整循环指纹策略 |
| M0.4 | `backend/packages/harness/deerflow/agents/factory.py`：`create_deerflow_agent` 的 `create_agent` 组装；辅助 `mcp/tools.py`：`get_mcp_tools` | 当前 SDK 的 Agent、checkpoint、中断恢复、本地 MCP 接口能否离线运行？ | 一个独立 SDK smoke；主教学图仍是显式 StateGraph，暂不实现正式后端 |
| M0.5 | `backend/packages/harness/deerflow/models/factory.py`：`create_chat_model` | 真实模型配置怎样转成可调用模型对象？ | 显式 opt-in 的单模型 smoke；不复制供应商路由和生产计量体系，缺 key 时记 NOT_RUN |
| M1.3 / M1.5 | `backend/packages/harness/deerflow/runtime/runs/manager.py`：`RunManager.create`、`create_or_reject`、`try_start`；对照 `backend/tests/test_run_manager.py` | 运行记录、原子入场与启动由谁负责？ | 单进程 RunManager + SQLite 约束；M1.3 先做提交幂等与线程槽位，启动/取消在后续单元，不复制全部调度策略 |
| M1.4 | `backend/packages/harness/deerflow/runtime/runs/worker.py`：`run_agent`；先读 `backend/packages/harness/deerflow/runtime/AGENTS.md` 定位流处理 | 执行任务与对外事件如何分工？ | 独立任务生命周期、run_events 与 SSE；只追一条事件，暂不展开整个 worker |
| M2.1 / M2.5 | `backend/packages/harness/deerflow/sandbox/tools.py`：`read_file_tool`、`bash_tool`；先读 `backend/packages/harness/deerflow/sandbox/AGENTS.md` | 工具请求怎样到达工作目录与执行环境？ | WorkspaceService + 一种 Docker 执行器；不照搬多个 provider |
| M2.4 | `backend/packages/harness/deerflow/agents/middlewares/clarification_middleware.py`：`ClarificationMiddleware`、`_handle_clarification` | 人工输入如何中断、恢复并处理同批工具？ | 学中断机制；本项目的动作审批、hash 和工具账本需自行实现，不能宣称原文件已提供完整方案 |
| M3.1 | `backend/packages/harness/deerflow/skills/parser.py`：`parse_skill_file` | Markdown/frontmatter 怎样变成可校验的 Skill？ | 本地 SkillLoader，只保留首版需要的元数据 |
| M3.2 | `backend/packages/harness/deerflow/agents/middlewares/skill_activation_middleware.py`：`SkillActivationMiddleware`；辅助 `backend/packages/harness/deerflow/skills/AGENTS.md` | 技能正文何时进入上下文，权限在哪一层执行？ | 一个当前 Skill 快照、显式加载和工具交集策略 |
| M3.3 / M3.4 | `backend/packages/harness/deerflow/agents/middlewares/summarization_middleware.py`：`DeerFlowSummarizationMiddleware`、`compact_state`；对照 `backend/tests/test_summarization_middleware.py` | 缩减模型上下文时怎样保留必要状态？ | 大输出文件引用 + 摘要 + 最近完整消息组；业务历史不删除 |
| M4 | `backend/packages/harness/deerflow/subagents/executor.py`：`SubagentExecutor`、`SubagentResult`；对照 `backend/tests/test_subagent_executor.py` | 子任务身份、独立上下文、结果与失败如何表达？ | 两类角色、有限并发、不递归；不复制耐久批任务/隔离事件循环等完整运行架构 |
| M5.1 | `backend/packages/harness/deerflow/mcp/tools.py`：`get_mcp_tools`；辅助 `backend/packages/harness/deerflow/mcp/AGENTS.md` | 外部工具如何适配到 Agent 的工具集合？ | 一个受信任的本地 stdio server；不做个人 OAuth 和多租户路由 |
| M5.2 | `backend/packages/harness/deerflow/agents/memory/AGENTS.md` | 长期信息与本轮上下文在哪里分工？ | 仅确认后的偏好 CRUD；不移植完整记忆后端 |
| M5.3 / M5.4 | `frontend/AGENTS.md`，按当前指南再定位具体 hook/reducer | 历史消息与流式更新如何合并？ | React/Vite 小型工作台；UI 框架是精简版选择 |
| M6 | `backend/tests/test_thread_state_reducers.py`、`backend/tests/test_run_manager.py` | 一个测试怎样证明状态不变量，而不是只调用一次函数？ | 写自己的行为测试/固定任务评测；不把原仓库测试通过算成本项目成绩 |

## 每次导读的输出

Codex 先读当前函数和必要上下文，输出以下五项；不必先跑起整个 DeerFlow：

1. 原文件路径、符号、当前本地行号与 HEAD；当前单元最多重点导读 1～2 个原文件。
2. 一条输入 → 调用 → 输出的路径；说明调用是框架提供还是 DeerFlow 自己实现。
3. 精简版要保留什么，暂时省去什么，为什么。
4. 对应 AgentLoom 的目标文件；尚不存在就明确写待实现。
5. 一项能观察这种机制的实验/测试；未执行不写通过。

用户不必通读上表所有文件。按 LEARNING 的单元顺序读对应行；原项目的大型函数只定位当前机制，避免把数千行兼容和部署分支变成第一堂课。

## 来源、访问和复用

上表是阅读路线和本项目的简化方案，并不声称逐个模块已经完成用户导读。进度以 PROGRESS 的阅读记录和学习反馈为准。实现不依赖 `deerflow-harness` 安装包。

这些 AGENTS.md 是原项目的架构阅读材料；对独立新目录的实现，以适用于新目录的约定和用户指令为准。如果实际修改 DeerFlow 文件，仍需遵守相应目录的原项目约定。

最终 README 保留上游致谢；实际复制代码片段或资源时按适用许可保留声明并记录来源。只参考设计时如实写“基于当前 DeerFlow 源码学习，独立实现精简版”，并能展示差异与自己的验证。
