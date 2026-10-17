import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity, Bot, ChevronRight, CircleStop, Clock3, FileUp, ListTodo, LoaderCircle,
  Menu, MessageSquareText, PanelRight, Paperclip, Plus, Send, Sparkles, Wrench, X,
} from "lucide-react";
import { api } from "./api";
import { ArtifactPanel } from "./components/ArtifactPanel";
import { ApprovalCard } from "./components/ApprovalCard";
import { SafeMarkdown } from "./components/SafeMarkdown";
import { TraceTimeline } from "./components/TraceTimeline";
import { emptyRunState, hydrateMessages, reduceRunEvent } from "./run-state";
import type { Approval, Artifact, RunEvent, RunStatus } from "./types";
import { useRunEvents } from "./use-run-events";

const ACTIVE: RunStatus[] = ["pending", "running", "waiting_input", "cancelling", "interrupted"];

function shortTime(value?: string | null) {
  if (!value) return "";
  return new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

function statusLabel(status?: string | null) {
  return ({ pending: "排队中", running: "执行中", waiting_input: "等待确认", cancelling: "正在取消", interrupted: "待恢复", succeeded: "已完成", failed: "失败", cancelled: "已取消" } as Record<string, string>)[status ?? ""] ?? "尚未运行";
}

function JsonBlock({ value }: { value: unknown }) {
  return <pre className="json-block">{JSON.stringify(value, null, 2)}</pre>;
}

export default function App() {
  const queryClient = useQueryClient();
  const [threadId, setThreadIdState] = useState(() => new URLSearchParams(location.search).get("thread"));
  const [runIdOverride, setRunIdOverride] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [attachments, setAttachments] = useState<Artifact[]>([]);
  const [mobileMenu, setMobileMenu] = useState(false);
  const [rightOpen, setRightOpen] = useState(true);
  const [rightTab, setRightTab] = useState<"tasks" | "files">("tasks");
  const fileRef = useRef<HTMLInputElement>(null);

  const setThreadId = (value: string | null) => {
    setThreadIdState(value);
    setRunIdOverride(null);
    const url = new URL(location.href);
    if (value) url.searchParams.set("thread", value);
    else url.searchParams.delete("thread");
    history.replaceState(null, "", url);
  };

  const threads = useQuery({ queryKey: ["threads"], queryFn: api.listThreads });
  useEffect(() => {
    if (!threadId && threads.data?.items[0]) setThreadId(threads.data.items[0].thread_id);
  }, [threadId, threads.data]);

  const thread = useQuery({ queryKey: ["thread", threadId], queryFn: () => api.getThread(threadId!), enabled: !!threadId });
  const messages = useQuery({ queryKey: ["messages", threadId], queryFn: () => api.getMessages(threadId!), enabled: !!threadId });
  const artifacts = useQuery({ queryKey: ["artifacts", threadId], queryFn: () => api.getArtifacts(threadId!), enabled: !!threadId });
  const runId = runIdOverride ?? thread.data?.latest_run?.run_id ?? null;
  const run = useQuery({ queryKey: ["run", runId], queryFn: () => api.getRun(runId!), enabled: !!runId });
  const trace = useQuery({ queryKey: ["trace", runId], queryFn: () => api.getTrace(runId!), enabled: !!runId });
  const approvals = useQuery({ queryKey: ["approvals", runId], queryFn: () => api.getApprovals(runId!), enabled: !!runId });
  const tools = useQuery({ queryKey: ["tools", runId], queryFn: () => api.getTools(runId!), enabled: !!runId });
  const subtasks = useQuery({ queryKey: ["subagents", runId], queryFn: () => api.getSubagents(runId!), enabled: !!runId });
  const [view, setView] = useState(() => emptyRunState());

  useEffect(() => setView(emptyRunState(runId)), [runId]);
  useEffect(() => { if (messages.data) setView((current) => hydrateMessages(current, messages.data.items)); }, [messages.data]);
  useEffect(() => {
    if (run.data) setView((current) => ({ ...current, status: run.data.status, usage: run.data.usage, pendingApprovalId: run.data.pending_approval_id }));
  }, [run.data]);

  const refreshRunData = (event?: RunEvent) => {
    if (!runId) return;
    queryClient.invalidateQueries({ queryKey: ["run", runId] });
    if (!event || event.type.startsWith("approval.")) queryClient.invalidateQueries({ queryKey: ["approvals", runId] });
    if (!event || event.type.startsWith("tool.")) queryClient.invalidateQueries({ queryKey: ["tools", runId] });
    if (!event || event.type.startsWith("subagent.")) queryClient.invalidateQueries({ queryKey: ["subagents", runId] });
    if (!event || event.type.startsWith("trace.") || event.type === "run.finished") queryClient.invalidateQueries({ queryKey: ["trace", runId] });
    if (!event || event.type === "run.started" || event.type.startsWith("approval.")) {
      queryClient.invalidateQueries({ queryKey: ["thread", threadId] });
      queryClient.invalidateQueries({ queryKey: ["threads"] });
    }
    if (!event || event.type === "run.finished") {
      queryClient.invalidateQueries({ queryKey: ["messages", threadId] });
      queryClient.invalidateQueries({ queryKey: ["artifacts", threadId] });
      queryClient.invalidateQueries({ queryKey: ["thread", threadId] });
      queryClient.invalidateQueries({ queryKey: ["threads"] });
    }
  };

  useRunEvents(runId, !!runId && ACTIVE.includes(view.status ?? "pending"), (event) => {
    setView((current) => reduceRunEvent(current, event));
    if (event.type !== "message.delta") refreshRunData(event);
  });

  const createThread = useMutation({
    mutationFn: () => api.createThread(),
    onSuccess: (created) => { queryClient.invalidateQueries({ queryKey: ["threads"] }); setThreadId(created.thread_id); setMobileMenu(false); },
  });
  const submit = useMutation({
    mutationFn: async () => {
      let activeThread = threadId;
      if (!activeThread) activeThread = (await api.createThread()).thread_id;
      const result = await api.submitRun(activeThread, draft.trim(), attachments.map((item) => item.artifact_id));
      return { ...result, threadId: activeThread };
    },
    onSuccess: (result) => {
      if (threadId !== result.threadId) setThreadId(result.threadId);
      setRunIdOverride(result.run_id);
      setDraft("");
      setAttachments([]);
      queryClient.invalidateQueries({ queryKey: ["messages", result.threadId] });
      queryClient.invalidateQueries({ queryKey: ["threads"] });
    },
  });
  const cancel = useMutation({ mutationFn: () => api.cancelRun(runId!), onSuccess: () => refreshRunData() });
  const resolve = useMutation({
    mutationFn: ({ approval, decision }: { approval: Approval; decision: "approve" | "reject" }) => api.resolveApproval(approval, decision),
    onSuccess: () => refreshRunData(),
  });
  const proposeCoderChange = useMutation({
    mutationFn: (taskId: string) => api.createCoderChange(taskId),
    onSuccess: () => refreshRunData(),
  });
  const upload = useMutation({
    mutationFn: async (file: File) => {
      let activeThread = threadId;
      if (!activeThread) activeThread = (await api.createThread()).thread_id;
      const artifact = await api.upload(activeThread, file);
      return { artifact, threadId: activeThread };
    },
    onSuccess: ({ artifact, threadId: selectedThread }) => {
      if (threadId !== selectedThread) setThreadId(selectedThread);
      setAttachments((current) => [...current.filter((item) => item.artifact_id !== artifact.artifact_id), artifact]);
      queryClient.invalidateQueries({ queryKey: ["artifacts", selectedThread] });
    },
  });

  const currentApproval = approvals.data?.items.find((item) => item.status === "pending") ?? null;
  const displayMessages = view.messageOrder
    .map((id) => view.messages[id])
    .filter((message) => message && message.role !== "tool" && String(message.content.text ?? "").trim());
  const running = ACTIVE.includes(view.status ?? "succeeded");
  const eventGroups = useMemo(() => view.timeline.filter((item) => !item.type.startsWith("message.") && !item.type.startsWith("trace.")), [view.timeline]);

  const onSubmit = () => {
    if (!draft.trim() || submit.isPending || running) return;
    submit.mutate();
  };

  return (
    <main className="app-shell">
      <aside className={`sidebar ${mobileMenu ? "mobile-open" : ""}`}>
        <div className="brand"><span className="brand-mark"><Sparkles size={19} /></span><div><strong>AgentLoom</strong><small>织能工作台</small></div><button className="icon-button mobile-only" onClick={() => setMobileMenu(false)}><X size={18} /></button></div>
        <button className="new-thread" onClick={() => createThread.mutate()} disabled={createThread.isPending}><Plus size={17} />新建任务</button>
        <div className="section-label">最近任务</div>
        <nav className="thread-list">
          {threads.data?.items.map((item) => (
            <button key={item.thread_id} className={`thread-row ${threadId === item.thread_id ? "active" : ""}`} onClick={() => { setThreadId(item.thread_id); setMobileMenu(false); }}>
              <MessageSquareText size={16} /><span><strong>{item.title}</strong><small>{statusLabel(item.latest_run?.status)} · {shortTime(item.updated_at)}</small></span><ChevronRight size={15} />
            </button>
          ))}
        </nav>
        <div className="sidebar-foot"><span className="health-dot" /> 本地服务已连接</div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <button className="icon-button mobile-only" onClick={() => setMobileMenu(true)}><Menu size={20} /></button>
          <div className="title-block"><small>当前任务</small><h1>{thread.data?.title ?? "新任务"}</h1></div>
          <div className="run-meta">
            {view.usage && <span className="usage-chip">{view.usage.input_tokens + view.usage.output_tokens} tokens</span>}
            <span className={`status-chip status-${view.status ?? "idle"}`}><i />{statusLabel(view.status)}</span>
            <button className="icon-button" onClick={() => setRightOpen((value) => !value)} title="切换详情栏"><PanelRight size={19} /></button>
          </div>
        </header>

        <div className="conversation" aria-live="polite">
          {displayMessages.length === 0 && (
            <div className="welcome"><span><Sparkles size={26} /></span><h2>把任务交给 AgentLoom</h2><p>上传资料、描述目标，然后观察模型、工具、审批和子任务如何协作。</p></div>
          )}
          {displayMessages.map((message) => (
            <article key={message.id} className={`message message-${message.role}`}>
              <div className="avatar">{message.role === "user" ? "你" : message.role === "assistant" ? <Bot size={17} /> : <Wrench size={16} />}</div>
              <div className="message-body"><div className="message-label">{message.role === "user" ? "你" : message.role === "assistant" ? "AgentLoom" : "工具结果"}{message.status === "partial" && <span>生成中…</span>}</div><SafeMarkdown>{String(message.content.text ?? JSON.stringify(message.content))}</SafeMarkdown></div>
            </article>
          ))}
          {currentApproval && <ApprovalCard approval={currentApproval} busy={resolve.isPending} onDecision={(decision) => resolve.mutate({ approval: currentApproval, decision })} />}
          <TraceTimeline spans={trace.data?.spans ?? []} />
          {eventGroups.length > 0 && (
            <section className="timeline"><div className="timeline-title"><Activity size={16} />持久事件</div>{eventGroups.map((event) => (
              <details key={event.key} className="event-row"><summary><span className="event-dot" /><strong>{event.type}</strong><small>{event.scope} · {shortTime(event.timestamp)}</small></summary><JsonBlock value={event.data} /></details>
            ))}</section>
          )}
          {run.data?.error && <div className="error-card"><strong>{run.data.error.code}</strong><p>{run.data.error.message}</p></div>}
        </div>

        <footer className="composer-shell">
          {attachments.length > 0 && <div className="attachment-strip">{attachments.map((item) => <span key={item.artifact_id}><Paperclip size={13} />{item.display_name}<button onClick={() => setAttachments((rows) => rows.filter((row) => row.artifact_id !== item.artifact_id))}><X size={12} /></button></span>)}</div>}
          <div className="composer">
            <textarea aria-label="任务内容" value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); onSubmit(); } }} placeholder="描述你希望完成的任务…" rows={2} />
            <div className="composer-actions">
              <input ref={fileRef} type="file" hidden onChange={(event) => { const file = event.target.files?.[0]; if (file) upload.mutate(file); event.target.value = ""; }} />
              <button className="icon-button" onClick={() => fileRef.current?.click()} disabled={upload.isPending} title="上传附件">{upload.isPending ? <LoaderCircle className="spin" size={18} /> : <FileUp size={18} />}</button>
              <span className="composer-hint">Enter 发送 · Shift + Enter 换行</span>
              {running ? <button className="send-button stop" onClick={() => cancel.mutate()} disabled={cancel.isPending}><CircleStop size={17} />停止</button> : <button className="send-button" onClick={onSubmit} disabled={!draft.trim() || submit.isPending}><Send size={17} />发送</button>}
            </div>
          </div>
          {(submit.error || upload.error) && <p className="inline-error">{String(submit.error?.message ?? upload.error?.message)}</p>}
        </footer>
      </section>

      {rightOpen && <aside className="inspector">
        <div className="inspector-tabs"><button className={rightTab === "tasks" ? "active" : ""} onClick={() => setRightTab("tasks")}><ListTodo size={16} />任务</button><button className={rightTab === "files" ? "active" : ""} onClick={() => setRightTab("files")}><Paperclip size={16} />文件</button></div>
        {rightTab === "files" ? <ArtifactPanel artifacts={artifacts.data?.items ?? []} /> : <div className="task-panel">
          <section className="panel-section"><h3><ListTodo size={16} />计划</h3>{thread.data?.todos.length ? thread.data.todos.map((todo) => <div className="todo-row" key={todo.id}><span className={`todo-check ${todo.status}`} /> <span>{todo.text}</span><small>{todo.status}</small></div>) : <p className="empty-copy">Agent 建立计划后会显示在这里。</p>}</section>
          <section className="panel-section"><h3><Bot size={16} />子任务</h3>{subtasks.data?.items.length ? subtasks.data.items.map((task) => <article className="subtask-card" key={task.task_id}><div><strong>{task.agent_type}</strong><span className={`mini-status ${task.status}`}>{task.status}</span></div><p>{task.prompt}</p>{task.result && <JsonBlock value={task.result} />}{task.agent_type === "coder" && task.status === "succeeded" && <button className="button ghost" disabled={proposeCoderChange.isPending} onClick={() => proposeCoderChange.mutate(task.task_id)}>生成变更提案</button>}</article>) : <p className="empty-copy">尚未委派子 Agent。</p>}{proposeCoderChange.error && <p className="inline-error">{proposeCoderChange.error.message}</p>}</section>
          <section className="panel-section"><h3><Wrench size={16} />工具</h3>{tools.data?.items.length ? tools.data.items.map((tool) => <details className="tool-card" key={tool.id}><summary><strong>{tool.tool_name}</strong><span className={`mini-status ${tool.status}`}>{tool.status}</span></summary><JsonBlock value={{ args: tool.args, result: tool.result, error: tool.error_code }} /></details>) : <p className="empty-copy">工具调用会按真实账本显示。</p>}</section>
          <section className="panel-section run-facts"><h3><Clock3 size={16} />本次用量</h3><div><span>模型请求</span><strong>{view.usage?.model_attempts ?? 0}</strong><span>工具执行</span><strong>{view.usage?.tool_executions ?? 0}</strong></div></section>
        </div>}
      </aside>}
    </main>
  );
}
