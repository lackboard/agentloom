import type {
  Approval,
  Artifact,
  MessageItem,
  RunDetail,
  RunTrace,
  SubagentTask,
  ThreadItem,
  ToolExecution,
} from "./types";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as {
      error?: { code?: string; message?: string };
    } | null;
    throw new ApiError(response.status, body?.error?.code ?? "HTTP_ERROR", body?.error?.message ?? response.statusText);
  }
  return response.json() as Promise<T>;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  listThreads: () => request<{ items: ThreadItem[] }>("/api/threads"),
  createThread: (title = "新任务") => request<{ thread_id: string }>("/api/threads", json({ title })),
  getThread: (threadId: string) =>
    request<ThreadItem & { todos: Array<{ id: string; text: string; status: string }> }>(`/api/threads/${threadId}`),
  getMessages: (threadId: string) => request<{ items: MessageItem[] }>(`/api/threads/${threadId}/messages`),
  getArtifacts: (threadId: string) => request<{ items: Artifact[] }>(`/api/threads/${threadId}/artifacts`),
  getRun: (runId: string) => request<RunDetail>(`/api/runs/${runId}`),
  getTrace: (runId: string) => request<RunTrace>(`/api/runs/${runId}/trace`),
  getApprovals: (runId: string) => request<{ items: Approval[] }>(`/api/runs/${runId}/approvals`),
  getTools: (runId: string) => request<{ items: ToolExecution[] }>(`/api/runs/${runId}/tool-executions`),
  getSubagents: (runId: string) => request<{ items: SubagentTask[] }>(`/api/runs/${runId}/subagents`),
  createCoderChange: (taskId: string) =>
    request(`/api/subagents/${taskId}/change-proposals`, json({})),
  submitRun: (threadId: string, text: string, attachmentIds: string[]) =>
    request<{ run_id: string; status: string }>(
      `/api/threads/${threadId}/runs`,
      json({ text, attachment_ids: attachmentIds, client_request_id: crypto.randomUUID() }),
    ),
  cancelRun: (runId: string) => request(`/api/runs/${runId}/cancel`, json({})),
  resolveApproval: (approval: Approval, decision: "approve" | "reject") =>
    request(`/api/approvals/${approval.approval_id}/resolve`,
      json({ payload_hash: approval.payload_hash, decision }),
    ),
  upload: async (threadId: string, file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request<Artifact>(`/api/threads/${threadId}/uploads`, { method: "POST", body });
  },
};
