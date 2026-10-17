import type { MessageItem, RunEvent, RunStatus, SubagentTask, Usage } from "./types";

export interface TimelineItem {
  key: string;
  seq: number;
  type: string;
  scope: string;
  timestamp: string;
  data: Record<string, unknown>;
}

export interface RunViewState {
  runId: string | null;
  status: RunStatus | null;
  seen: Set<string>;
  messages: Record<string, MessageItem>;
  messageOrder: string[];
  timeline: TimelineItem[];
  subtasks: Record<string, Partial<SubagentTask>>;
  pendingApprovalId: string | null;
  usage: Usage | null;
}

export function emptyRunState(runId: string | null = null): RunViewState {
  return {
    runId,
    status: null,
    seen: new Set(),
    messages: {},
    messageOrder: [],
    timeline: [],
    subtasks: {},
    pendingApprovalId: null,
    usage: null,
  };
}

export function hydrateMessages(state: RunViewState, rows: MessageItem[]): RunViewState {
  const messages = { ...state.messages };
  const messageOrder = [...state.messageOrder];
  for (const row of rows) {
    const current = messages[row.id];
    // REST 中的 completed 投影是事实来源，可以覆盖 SSE 尚未完成的增量。
    if (!current || row.status === "completed") messages[row.id] = row;
    if (!messageOrder.includes(row.id)) messageOrder.push(row.id);
  }
  messageOrder.sort((a, b) => (messages[a]?.seq ?? Number.MAX_SAFE_INTEGER) - (messages[b]?.seq ?? Number.MAX_SAFE_INTEGER));
  return { ...state, messages, messageOrder };
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}

export function reduceRunEvent(state: RunViewState, event: RunEvent): RunViewState {
  const identity = `${event.run_id}:${event.seq}`;
  if (state.seen.has(identity)) return state;

  const next: RunViewState = {
    ...state,
    runId: event.run_id,
    seen: new Set(state.seen).add(identity),
    messages: { ...state.messages },
    messageOrder: [...state.messageOrder],
    subtasks: { ...state.subtasks },
    timeline: [...state.timeline, { key: identity, ...event }],
  };
  const data = event.data;

  if (event.type === "message.delta" || event.type === "message.completed") {
    const id = stringValue(data.message_id);
    if (id) {
      const existing = next.messages[id];
      if (event.type === "message.delta") {
        if (existing?.status !== "completed") {
          const previous = stringValue(existing?.content.text);
          next.messages[id] = {
            id,
            seq: existing?.seq ?? event.seq,
            role: (data.role as MessageItem["role"]) ?? existing?.role ?? "assistant",
            content: { ...(existing?.content ?? {}), text: previous + stringValue(data.delta) },
            status: "partial",
          };
        }
      } else {
        next.messages[id] = {
          id,
          seq: existing?.seq ?? event.seq,
          role: (data.role as MessageItem["role"]) ?? existing?.role ?? "assistant",
          content: (data.content as MessageItem["content"]) ?? { text: "" },
          status: "completed",
        };
      }
      if (!next.messageOrder.includes(id)) next.messageOrder.push(id);
    }
  }

  if (event.type.startsWith("subagent.")) {
    const taskId = stringValue(data.task_id);
    if (taskId) {
      next.subtasks[taskId] = {
        ...next.subtasks[taskId],
        task_id: taskId,
        run_id: event.run_id,
        agent_type: stringValue(data.agent_type) || next.subtasks[taskId]?.agent_type,
        status: stringValue(data.status) || event.type.slice("subagent.".length),
        result: (data.result as Record<string, unknown>) ?? next.subtasks[taskId]?.result,
      };
    }
  }

  if (event.type === "approval.required") next.pendingApprovalId = stringValue(data.approval_id) || null;
  if (event.type === "approval.resolved") next.pendingApprovalId = null;
  if (event.type === "usage.updated") next.usage = data as unknown as Usage;
  if (event.type === "run.started") next.status = "running";
  if (event.type === "run.waiting_input") next.status = "waiting_input";
  if (event.type === "run.finished") next.status = (data.status as RunStatus) ?? next.status;
  return next;
}
