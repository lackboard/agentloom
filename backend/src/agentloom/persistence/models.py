"""SQLAlchemy mappings for AgentLoom application tables.

The Alembic baseline remains the schema source of truth. Chinese ``comment``
values document field meaning in Python metadata; SQLite itself does not store
column comments for Navicat to display.
"""

from sqlalchemy import ForeignKey, ForeignKeyConstraint, Index, PrimaryKeyConstraint, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class shared by all application-table mappings."""


class ThreadRow(Base):
    """一段连续对话及其工作空间的业务身份。"""

    __tablename__ = "threads"

    id: Mapped[str] = mapped_column(primary_key=True, comment="服务端生成的线程 UUID")
    title: Mapped[str] = mapped_column(default="New thread", comment="用户可修改的会话标题")
    agent_profile: Mapped[str] = mapped_column(default="default", comment="该线程使用的 Agent 配置档名称")
    created_at: Mapped[str] = mapped_column(comment="线程创建时间，UTC ISO 8601 字符串")
    updated_at: Mapped[str] = mapped_column(comment="线程最后更新时间，UTC ISO 8601 字符串")
    archived_at: Mapped[str | None] = mapped_column(comment="归档时间；为空表示仍可使用")


class RunRow(Base):
    """一次用户任务从提交到终止的生命周期记录。"""

    __tablename__ = "runs"
    __table_args__ = (UniqueConstraint("thread_id", "client_request_id"), UniqueConstraint("id", "thread_id"))

    id: Mapped[str] = mapped_column(primary_key=True, comment="服务端生成的 Run UUID")
    trace_id: Mapped[str] = mapped_column(unique=True, comment="服务端生成的端到端 Trace 标识")
    thread_id: Mapped[str] = mapped_column(ForeignKey("threads.id"), comment="所属 Thread UUID")
    client_request_id: Mapped[str] = mapped_column(comment="客户端生成的幂等请求 UUID")
    request_hash: Mapped[str] = mapped_column(comment="规范化请求体的 SHA-256，用于发现同 ID 不同内容")
    input_json: Mapped[str] = mapped_column(comment="经过 Pydantic 校验的原始提交内容 JSON")
    input_message_id: Mapped[str] = mapped_column(comment="本 Run 稳定的用户输入消息 UUID")
    status: Mapped[str] = mapped_column(default="pending", comment="Run 状态机的当前状态")
    stop_reason: Mapped[str | None] = mapped_column(comment="正常结束、预算耗尽或取消等停止原因")
    model_name: Mapped[str] = mapped_column(comment="创建 Run 时冻结的模型名称")
    config_snapshot_json: Mapped[str] = mapped_column(comment="不含密钥的运行配置快照 JSON")
    budget_json: Mapped[str] = mapped_column(comment="模型、工具及子任务预算快照 JSON")
    start_checkpoint_id: Mapped[str | None] = mapped_column(comment="Run 开始时对应的框架 checkpoint ID")
    last_checkpoint_id: Mapped[str | None] = mapped_column(comment="最近一次已确认持久化的 checkpoint ID")
    model_attempts: Mapped[int] = mapped_column(default=0, comment="模型请求尝试次数，包含失败与重试")
    tool_executions_count: Mapped[int] = mapped_column(default=0, comment="已经实际开始的工具执行次数")
    input_tokens: Mapped[int] = mapped_column(default=0, comment="服务商已报告的输入 token 小计")
    output_tokens: Mapped[int] = mapped_column(default=0, comment="服务商已报告的输出 token 小计")
    usage_complete: Mapped[int] = mapped_column(default=1, comment="1 表示所有模型尝试均有 usage，0 表示统计不完整")
    estimated_cost_usd: Mapped[float | None] = mapped_column(comment="按已知用量估算的美元成本；未知时为空")
    next_event_seq: Mapped[int] = mapped_column(default=1, comment="下一条 RunEvent 应使用的单调递增序号")
    error_code: Mapped[str | None] = mapped_column(comment="最终或当前错误的稳定机器码")
    error_message: Mapped[str | None] = mapped_column(comment="供诊断和界面展示的错误说明")
    created_at: Mapped[str] = mapped_column(comment="Run 提交时间，UTC ISO 8601 字符串")
    started_at: Mapped[str | None] = mapped_column(comment="Run 获得执行容量的时间")
    finished_at: Mapped[str | None] = mapped_column(comment="Run 进入 succeeded/failed/cancelled 的时间")


class MessageRow(Base):
    """供 UI 展示的完整消息投影，不替代 LangGraph 执行状态。"""

    __tablename__ = "messages"
    __table_args__ = (
        ForeignKeyConstraint(("run_id", "thread_id"), ("runs.id", "runs.thread_id")),
        UniqueConstraint("thread_id", "seq"),
        UniqueConstraint("run_id", "scope", "graph_message_id"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, comment="展示消息 UUID")
    thread_id: Mapped[str] = mapped_column(ForeignKey("threads.id"), comment="所属 Thread UUID")
    run_id: Mapped[str] = mapped_column(comment="产生该消息的 Run UUID")
    seq: Mapped[int] = mapped_column(comment="线程内严格递增的展示顺序")
    scope: Mapped[str] = mapped_column(default="lead", comment="消息来源范围，如 lead 或子任务范围")
    graph_message_id: Mapped[str] = mapped_column(comment="LangGraph 消息稳定 ID，用于幂等投影")
    role: Mapped[str] = mapped_column(comment="消息角色：user、assistant 或 tool")
    content_json: Mapped[str] = mapped_column(comment="结构化消息正文 JSON")
    status: Mapped[str] = mapped_column(default="completed", comment="partial 表示流式中，completed 表示完整消息")
    created_at: Mapped[str] = mapped_column(comment="消息首次创建时间，UTC ISO 8601 字符串")


class RunEventRow(Base):
    """Run 的可回放事件，用于后续 SSE 断线续传。"""

    __tablename__ = "run_events"
    __table_args__ = (PrimaryKeyConstraint("run_id", "seq"),)

    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), comment="所属 Run UUID")
    seq: Mapped[int] = mapped_column(comment="Run 内严格递增的事件序号，也是 SSE id")
    event_type: Mapped[str] = mapped_column(comment="稳定事件类型，如 message.completed")
    scope: Mapped[str] = mapped_column(default="lead", comment="事件所属 Agent 或子任务范围")
    payload_json: Mapped[str] = mapped_column(comment="按事件类型校验后的载荷 JSON")
    created_at: Mapped[str] = mapped_column(comment="事件持久化时间，UTC ISO 8601 字符串")


class TraceSpanRow(Base):
    """一次 Run 内可组成父子调用树的安全追踪片段。"""

    __tablename__ = "trace_spans"
    __table_args__ = (
        Index("ix_trace_spans_run_started", "run_id", "started_at"),
        Index("ix_trace_spans_trace", "trace_id"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, comment="Span 稳定标识；模型和工具优先复用回调 Run ID")
    trace_id: Mapped[str] = mapped_column(comment="所属 Trace 标识，与 runs.trace_id 对应")
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), comment="所属 Agent Run UUID")
    parent_span_id: Mapped[str | None] = mapped_column(
        ForeignKey("trace_spans.id"), comment="父 Span；为空表示调用树根节点"
    )
    kind: Mapped[str] = mapped_column(comment="片段类型：run、model 或 tool")
    name: Mapped[str] = mapped_column(comment="安全的模型名、工具名或运行名称")
    status: Mapped[str] = mapped_column(default="running", comment="running、succeeded、failed 或 cancelled")
    attributes_json: Mapped[str] = mapped_column(default="{}", comment="不含提示词、工具正文和密钥的结构化元数据")
    started_at: Mapped[str] = mapped_column(comment="Span 开始时间，UTC ISO 8601 字符串")
    finished_at: Mapped[str | None] = mapped_column(comment="Span 完成时间；执行中为空")
    duration_ms: Mapped[int | None] = mapped_column(comment="完成后计算的墙钟耗时毫秒")
    error_code: Mapped[str | None] = mapped_column(comment="失败时的稳定错误类型；成功时为空")


class RunReplayRow(Base):
    """从一个终态 Run 冻结出的历史证据回放。"""

    __tablename__ = "run_replays"
    __table_args__ = (UniqueConstraint("source_run_id", "evidence_hash"),)

    id: Mapped[str] = mapped_column(primary_key=True, comment="回放 UUID")
    source_run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), comment="证据来源 Run UUID")
    evidence_hash: Mapped[str] = mapped_column(comment="规范化回放证据的 SHA-256")
    evidence_json: Mapped[str] = mapped_column(comment="冻结的消息、事件及工具结果证据 JSON")
    status: Mapped[str] = mapped_column(default="completed", comment="回放状态；当前仅 completed")
    created_at: Mapped[str] = mapped_column(comment="回放创建时间")


class ToolExecutionRow(Base):
    """一次逻辑工具调用的执行账本。"""

    __tablename__ = "tool_executions"
    __table_args__ = (UniqueConstraint("run_id", "scope", "tool_call_id"),)

    id: Mapped[str] = mapped_column(primary_key=True, comment="工具执行记录 UUID")
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), comment="所属 Run UUID")
    scope: Mapped[str] = mapped_column(default="lead", comment="发起调用的 Agent 范围")
    tool_call_id: Mapped[str] = mapped_column(comment="模型生成的工具调用 ID，用于请求和结果配对")
    tool_name: Mapped[str] = mapped_column(comment="实际解析到的工具名称")
    args_hash: Mapped[str] = mapped_column(comment="规范化工具参数的 SHA-256")
    args_json: Mapped[str] = mapped_column(comment="已校验且不含密钥的工具参数 JSON")
    replay_class: Mapped[str] = mapped_column(comment="重放等级：read_only、idempotent 或 manual")
    status: Mapped[str] = mapped_column(default="prepared", comment="工具执行生命周期状态")
    result_json: Mapped[str | None] = mapped_column(comment="成功结果或受控错误结果 JSON")
    precondition_json: Mapped[str | None] = mapped_column(comment="写操作执行前的文件 hash 等前置条件")
    error_code: Mapped[str | None] = mapped_column(comment="工具失败的稳定错误码")
    attempts: Mapped[int] = mapped_column(default=0, comment="该逻辑调用的实际尝试次数")
    created_at: Mapped[str] = mapped_column(comment="记录准备时间")
    started_at: Mapped[str | None] = mapped_column(comment="开始产生外部副作用的时间")
    finished_at: Mapped[str | None] = mapped_column(comment="获得确定结果的时间；uncertain 可为空")


class ApprovalRow(Base):
    """工具批次审批或澄清问题的持久化记录。"""

    __tablename__ = "approvals"
    __table_args__ = (UniqueConstraint("run_id", "suspend_key"),)

    id: Mapped[str] = mapped_column(primary_key=True, comment="审批记录 UUID")
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), comment="被暂停的 Run UUID")
    suspend_key: Mapped[str] = mapped_column(comment="可信运行时生成的稳定暂停键")
    kind: Mapped[str] = mapped_column(comment="tool_batch 工具审批或 clarification 澄清")
    payload_hash: Mapped[str] = mapped_column(comment="审批载荷的 SHA-256，防止答复后替换参数")
    payload_json: Mapped[str] = mapped_column(comment="展示给用户的审批或澄清内容 JSON")
    checkpoint_id: Mapped[str | None] = mapped_column(comment="对应中断已持久化后的 checkpoint ID")
    status: Mapped[str] = mapped_column(default="pending", comment="审批当前状态")
    response_json: Mapped[str | None] = mapped_column(comment="用户的批准、拒绝或澄清答复 JSON")
    created_at: Mapped[str] = mapped_column(comment="审批准备时间")
    resolved_at: Mapped[str | None] = mapped_column(comment="用户完成答复的时间")
    consumed_at: Mapped[str | None] = mapped_column(comment="恢复流程消费该答复的时间")


class SubagentTaskRow(Base):
    """Lead Agent 委派给 Researcher 或 Coder 的独立子任务。"""

    __tablename__ = "subagent_tasks"
    __table_args__ = (UniqueConstraint("id", "run_id"), UniqueConstraint("run_id", "parent_tool_call_id"))

    id: Mapped[str] = mapped_column(primary_key=True, comment="子任务 UUID")
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), comment="所属父 Run UUID")
    parent_tool_call_id: Mapped[str] = mapped_column(comment="父 Agent 发起 task 工具调用的稳定 ID")
    agent_type: Mapped[str] = mapped_column(comment="子 Agent 类型：researcher 或 coder")
    status: Mapped[str] = mapped_column(default="queued", comment="子任务生命周期状态")
    prompt: Mapped[str] = mapped_column(comment="父 Agent 提供的子任务说明")
    result_json: Mapped[str | None] = mapped_column(comment="子任务结果或失败摘要 JSON")
    acceptance_json: Mapped[str | None] = mapped_column(comment="验收命令、证据与结论 JSON")
    input_tokens: Mapped[int] = mapped_column(default=0, comment="子任务输入 token 小计")
    output_tokens: Mapped[int] = mapped_column(default=0, comment="子任务输出 token 小计")
    usage_complete: Mapped[int] = mapped_column(default=1, comment="子任务 usage 是否完整")
    created_at: Mapped[str] = mapped_column(comment="子任务创建时间")
    started_at: Mapped[str | None] = mapped_column(comment="子任务开始运行时间")
    finished_at: Mapped[str | None] = mapped_column(comment="子任务进入终态的时间")
    deadline_at: Mapped[str] = mapped_column(comment="子任务必须停止等待的 UTC 截止时间")


class CoderChangeProposalRow(Base):
    """Coder 私有工作区向父工作区提交的冻结变更提案。"""

    __tablename__ = "coder_change_proposals"
    __table_args__ = (UniqueConstraint("task_id", "manifest_hash"),)

    id: Mapped[str] = mapped_column(primary_key=True, comment="变更提案 UUID")
    task_id: Mapped[str] = mapped_column(ForeignKey("subagent_tasks.id"), comment="来源 Coder 子任务 UUID")
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), comment="来源父 Run UUID")
    thread_id: Mapped[str] = mapped_column(ForeignKey("threads.id"), comment="待接纳文件所属 Thread UUID")
    approval_id: Mapped[str] = mapped_column(ForeignKey("approvals.id"), unique=True, comment="绑定的审批 UUID")
    status: Mapped[str] = mapped_column(
        default="pending", comment="pending、rejected、verifying、accepted、failed 或 conflict"
    )
    manifest_hash: Mapped[str] = mapped_column(comment="文件 hash、diff 和验证命令的整体 SHA-256")
    manifest_json: Mapped[str] = mapped_column(comment="冻结的文件清单、diff 与 Docker 命令 JSON")
    verification_json: Mapped[str | None] = mapped_column(comment="Docker 退出码及截断后的标准输出证据 JSON")
    error_code: Mapped[str | None] = mapped_column(comment="验证或接纳失败的稳定错误码")
    error_message: Mapped[str | None] = mapped_column(comment="供用户诊断的失败说明")
    created_at: Mapped[str] = mapped_column(comment="提案创建时间")
    resolved_at: Mapped[str | None] = mapped_column(comment="拒绝或接纳完成时间")


class ArtifactRow(Base):
    """上传或生成文件的不可变、可校验快照。"""

    __tablename__ = "artifacts"
    __table_args__ = (
        ForeignKeyConstraint(("run_id", "thread_id"), ("runs.id", "runs.thread_id")),
        ForeignKeyConstraint(("subagent_task_id", "run_id"), ("subagent_tasks.id", "subagent_tasks.run_id")),
        UniqueConstraint("thread_id", "relative_path"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, comment="产物 UUID")
    thread_id: Mapped[str] = mapped_column(ForeignKey("threads.id"), comment="拥有该文件的 Thread UUID")
    run_id: Mapped[str | None] = mapped_column(comment="生成该文件的 Run；上传文件可为空")
    subagent_task_id: Mapped[str | None] = mapped_column(comment="生成该文件的子任务；Lead 生成时为空")
    kind: Mapped[str] = mapped_column(comment="文件类型：upload、output 或 tool_output")
    display_name: Mapped[str] = mapped_column(comment="界面展示和下载使用的文件名")
    relative_path: Mapped[str] = mapped_column(comment="线程工作区内的受控相对路径")
    sha256: Mapped[str] = mapped_column(comment="文件内容 SHA-256，用于完整性和审批前置检查")
    size_bytes: Mapped[int] = mapped_column(comment="快照文件字节数")
    mime_type: Mapped[str] = mapped_column(comment="服务端判定的 MIME 类型")
    created_at: Mapped[str] = mapped_column(comment="不可变快照登记时间")


class MemoryRow(Base):
    """用户明确确认的少量长期偏好或事实。"""

    __tablename__ = "memories"
    __table_args__ = (UniqueConstraint("scope_key", "category", "memory_key"),)

    id: Mapped[str] = mapped_column(primary_key=True, comment="记忆 UUID")
    scope_key: Mapped[str] = mapped_column(default="local", comment="记忆作用域；首版固定为 local")
    category: Mapped[str] = mapped_column(comment="记忆分类：preference 或 fact")
    memory_key: Mapped[str] = mapped_column(comment="作用域和分类内稳定的业务键")
    content: Mapped[str] = mapped_column(comment="用户确认后的记忆正文")
    status: Mapped[str] = mapped_column(default="candidate", comment="candidate、active 或 deleted")
    source_run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"), comment="提出该记忆的来源 Run")
    version: Mapped[int] = mapped_column(default=1, comment="乐观并发控制版本号")
    created_at: Mapped[str] = mapped_column(comment="记忆首次创建时间")
    updated_at: Mapped[str] = mapped_column(comment="最近一次确认、修改或删除时间")
    expires_at: Mapped[str | None] = mapped_column(comment="可选过期时间；为空表示不过期")
