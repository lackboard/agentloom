-- AgentLoom V1 application schema (design artifact).
-- Execute only in a new database belonging to the future AgentLoom project.
-- M1 created the nine-table baseline; M7 adds tracing, replay and Coder change review tables.
-- Enable repositories/features by milestone; do not run this script at app startup.
-- LangGraph owns checkpoints.sqlite; its private schema is intentionally absent.
-- IDs: server-generated UUID strings. Timestamps: UTC ISO 8601 strings.
-- Enable foreign_keys for EVERY connection. Enable WAL when opening an on-disk DB.
-- JSON is validated by Pydantic before insertion as well as json_valid below.
PRAGMA foreign_keys = ON;

CREATE TABLE threads (
    id TEXT PRIMARY KEY NOT NULL,
    title TEXT NOT NULL DEFAULT 'New thread',
    agent_profile TEXT NOT NULL DEFAULT 'default',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archived_at TEXT
);
CREATE INDEX ix_threads_updated ON threads(updated_at DESC, id);

CREATE TABLE runs (
    id TEXT PRIMARY KEY NOT NULL,
    trace_id TEXT NOT NULL UNIQUE,
    thread_id TEXT NOT NULL REFERENCES threads(id) ON DELETE RESTRICT,
    client_request_id TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    input_json TEXT NOT NULL CHECK (json_valid(input_json)),
    input_message_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN (
        'pending', 'running', 'waiting_input', 'interrupted', 'cancelling',
        'succeeded', 'failed', 'cancelled'
    )),
    stop_reason TEXT,
    model_name TEXT NOT NULL,
    config_snapshot_json TEXT NOT NULL CHECK (json_valid(config_snapshot_json)),
    budget_json TEXT NOT NULL CHECK (json_valid(budget_json)),
    start_checkpoint_id TEXT,
    last_checkpoint_id TEXT,
    model_attempts INTEGER NOT NULL DEFAULT 0 CHECK (model_attempts >= 0),
    tool_executions_count INTEGER NOT NULL DEFAULT 0 CHECK (tool_executions_count >= 0),
    -- Known usage subtotal. usage_complete=0 means some attempts had missing usage.
    input_tokens INTEGER NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
    output_tokens INTEGER NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
    usage_complete INTEGER NOT NULL DEFAULT 1 CHECK (usage_complete IN (0, 1)),
    estimated_cost_usd REAL CHECK (estimated_cost_usd IS NULL OR estimated_cost_usd >= 0),
    next_event_seq INTEGER NOT NULL DEFAULT 1 CHECK (next_event_seq > 0),
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    UNIQUE (id, thread_id),
    UNIQUE (thread_id, client_request_id),
    CHECK (
        (status IN ('succeeded', 'failed', 'cancelled') AND finished_at IS NOT NULL)
        OR
        (status NOT IN ('succeeded', 'failed', 'cancelled') AND finished_at IS NULL)
    )
);
CREATE UNIQUE INDEX uq_runs_one_unfinished_per_thread ON runs(thread_id)
WHERE status IN ('pending', 'running', 'waiting_input', 'interrupted', 'cancelling');
CREATE INDEX ix_runs_thread_created ON runs(thread_id, created_at DESC, id);
CREATE INDEX ix_runs_status ON runs(status, created_at);

CREATE TABLE messages (
    id TEXT PRIMARY KEY NOT NULL,
    thread_id TEXT NOT NULL REFERENCES threads(id) ON DELETE RESTRICT,
    run_id TEXT NOT NULL,
    seq INTEGER NOT NULL CHECK (seq > 0),
    scope TEXT NOT NULL DEFAULT 'lead',
    graph_message_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'tool')),
    content_json TEXT NOT NULL CHECK (json_valid(content_json)),
    status TEXT NOT NULL DEFAULT 'completed' CHECK (status IN ('partial', 'completed')),
    created_at TEXT NOT NULL,
    FOREIGN KEY (run_id, thread_id) REFERENCES runs(id, thread_id) ON DELETE RESTRICT,
    UNIQUE (thread_id, seq),
    UNIQUE (run_id, scope, graph_message_id)
);

CREATE TABLE run_events (
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE RESTRICT,
    seq INTEGER NOT NULL CHECK (seq > 0),
    event_type TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'lead',
    payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, seq)
);
CREATE INDEX ix_run_events_scope ON run_events(run_id, scope, seq);

CREATE TABLE trace_spans (
    id TEXT PRIMARY KEY NOT NULL,
    trace_id TEXT NOT NULL,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE RESTRICT,
    parent_span_id TEXT REFERENCES trace_spans(id) ON DELETE RESTRICT,
    kind TEXT NOT NULL CHECK (kind IN ('run', 'model', 'tool')),
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running' CHECK (status IN (
        'running', 'waiting_input', 'succeeded', 'failed', 'cancelled'
    )),
    -- 只保存模型名、工具名、usage 等安全元数据，不保存提示词、工具正文或密钥。
    attributes_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(attributes_json)),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    duration_ms INTEGER CHECK (duration_ms IS NULL OR duration_ms >= 0),
    error_code TEXT,
    CHECK (
        (status IN ('succeeded', 'failed', 'cancelled') AND finished_at IS NOT NULL)
        OR (status IN ('running', 'waiting_input') AND finished_at IS NULL)
    )
);
CREATE INDEX ix_trace_spans_run_started ON trace_spans(run_id, started_at);
CREATE INDEX ix_trace_spans_trace ON trace_spans(trace_id);

CREATE TABLE run_replays (
    id TEXT PRIMARY KEY NOT NULL,
    source_run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE RESTRICT,
    evidence_hash TEXT NOT NULL,
    evidence_json TEXT NOT NULL CHECK (json_valid(evidence_json)),
    status TEXT NOT NULL DEFAULT 'completed' CHECK (status = 'completed'),
    created_at TEXT NOT NULL,
    UNIQUE (source_run_id, evidence_hash)
);

CREATE TABLE tool_executions (
    id TEXT PRIMARY KEY NOT NULL,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE RESTRICT,
    scope TEXT NOT NULL DEFAULT 'lead',
    tool_call_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    args_hash TEXT NOT NULL,
    -- No credentials here. Secret configuration is resolved server-side at execution.
    args_json TEXT NOT NULL CHECK (json_valid(args_json)),
    replay_class TEXT NOT NULL CHECK (replay_class IN ('read_only', 'idempotent', 'manual')),
    status TEXT NOT NULL DEFAULT 'prepared' CHECK (status IN (
        'prepared', 'running', 'succeeded', 'failed', 'denied', 'cancelled', 'uncertain'
    )),
    result_json TEXT CHECK (result_json IS NULL OR json_valid(result_json)),
    precondition_json TEXT CHECK (precondition_json IS NULL OR json_valid(precondition_json)),
    error_code TEXT,
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    UNIQUE (run_id, scope, tool_call_id)
);
CREATE INDEX ix_tool_executions_status ON tool_executions(run_id, status);

CREATE TABLE approvals (
    id TEXT PRIMARY KEY NOT NULL,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE RESTRICT,
    -- Stable key for one proposed batch/question, generated by trusted runtime.
    suspend_key TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('tool_batch', 'clarification', 'coder_change')),
    payload_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
    -- NULL while prepared; not answerable until the matching interrupt is durable.
    checkpoint_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN (
        'pending', 'approved', 'rejected', 'answered', 'expired'
    )),
    response_json TEXT CHECK (response_json IS NULL OR json_valid(response_json)),
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    consumed_at TEXT,
    UNIQUE (run_id, suspend_key),
    CHECK (
        (status = 'pending' AND resolved_at IS NULL)
        OR (status <> 'pending' AND resolved_at IS NOT NULL)
    ),
    CHECK (
        status NOT IN ('approved', 'rejected', 'answered')
        OR (checkpoint_id IS NOT NULL AND response_json IS NOT NULL)
    ),
    CHECK (kind <> 'tool_batch' OR status <> 'answered'),
    CHECK (kind <> 'clarification' OR status NOT IN ('approved', 'rejected')),
    CHECK (consumed_at IS NULL OR status IN ('approved', 'rejected', 'answered'))
);
CREATE INDEX ix_approvals_pending ON approvals(run_id, status);

CREATE TABLE subagent_tasks (
    id TEXT PRIMARY KEY NOT NULL,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE RESTRICT,
    parent_tool_call_id TEXT NOT NULL,
    agent_type TEXT NOT NULL CHECK (agent_type IN ('researcher', 'coder')),
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN (
        'queued', 'running', 'succeeded', 'failed', 'cancelled', 'interrupted'
    )),
    prompt TEXT NOT NULL,
    result_json TEXT CHECK (result_json IS NULL OR json_valid(result_json)),
    acceptance_json TEXT CHECK (acceptance_json IS NULL OR json_valid(acceptance_json)),
    input_tokens INTEGER NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
    output_tokens INTEGER NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
    usage_complete INTEGER NOT NULL DEFAULT 1 CHECK (usage_complete IN (0, 1)),
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    deadline_at TEXT NOT NULL,
    UNIQUE (id, run_id),
    UNIQUE (run_id, parent_tool_call_id)
);
CREATE INDEX ix_subagent_tasks_run_status ON subagent_tasks(run_id, status);

CREATE TABLE coder_change_proposals (
    id TEXT PRIMARY KEY NOT NULL,
    task_id TEXT NOT NULL REFERENCES subagent_tasks(id) ON DELETE RESTRICT,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE RESTRICT,
    thread_id TEXT NOT NULL REFERENCES threads(id) ON DELETE RESTRICT,
    approval_id TEXT NOT NULL UNIQUE REFERENCES approvals(id) ON DELETE RESTRICT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN (
        'pending', 'rejected', 'verifying', 'accepted', 'failed', 'conflict'
    )),
    manifest_hash TEXT NOT NULL,
    manifest_json TEXT NOT NULL CHECK (json_valid(manifest_json)),
    verification_json TEXT CHECK (verification_json IS NULL OR json_valid(verification_json)),
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    UNIQUE (task_id, manifest_hash)
);

CREATE TABLE artifacts (
    id TEXT PRIMARY KEY NOT NULL,
    thread_id TEXT NOT NULL REFERENCES threads(id) ON DELETE RESTRICT,
    -- Uploads may predate a Run; generated artifacts always have run_id.
    run_id TEXT,
    subagent_task_id TEXT,
    kind TEXT NOT NULL CHECK (kind IN ('upload', 'output', 'tool_output')),
    display_name TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    sha256 TEXT NOT NULL CHECK (length(sha256) = 64),
    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
    mime_type TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (run_id, thread_id) REFERENCES runs(id, thread_id) ON DELETE RESTRICT,
    FOREIGN KEY (subagent_task_id, run_id) REFERENCES subagent_tasks(id, run_id) ON DELETE RESTRICT,
    UNIQUE (thread_id, relative_path),
    CHECK (kind = 'upload' OR run_id IS NOT NULL),
    CHECK (subagent_task_id IS NULL OR run_id IS NOT NULL)
);
CREATE INDEX ix_artifacts_thread_created ON artifacts(thread_id, created_at DESC, id);

CREATE TABLE memories (
    id TEXT PRIMARY KEY NOT NULL,
    scope_key TEXT NOT NULL DEFAULT 'local',
    category TEXT NOT NULL CHECK (category IN ('preference', 'fact')),
    memory_key TEXT NOT NULL,
    content TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'candidate' CHECK (status IN ('candidate', 'active', 'deleted')),
    source_run_id TEXT REFERENCES runs(id) ON DELETE RESTRICT,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT,
    UNIQUE (scope_key, category, memory_key)
);
CREATE INDEX ix_memories_active ON memories(scope_key, status, updated_at DESC);

-- State transitions, path ownership, argument hashes, approval consumption,
-- and budget reservations require repository/service checks in addition to DDL.
-- In particular, no SQL constraint can make an arbitrary external tool exactly-once.
