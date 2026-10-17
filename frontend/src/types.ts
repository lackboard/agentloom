export type RunStatus =
  | "pending"
  | "running"
  | "waiting_input"
  | "cancelling"
  | "interrupted"
  | "succeeded"
  | "failed"
  | "cancelled";

export interface RunSummary {
  run_id: string;
  status: RunStatus;
  stop_reason: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface ThreadItem {
  thread_id: string;
  title: string;
  agent_profile: string;
  created_at: string;
  updated_at: string;
  latest_run: RunSummary | null;
}

export interface MessageItem {
  id: string;
  seq: number;
  role: "user" | "assistant" | "tool";
  content: { text?: string; attachment_ids?: string[]; [key: string]: unknown };
  status: "partial" | "completed";
}

export interface RunDetail {
  run_id: string;
  thread_id: string;
  status: RunStatus;
  stop_reason: string | null;
  error: { code: string; message: string } | null;
  usage: Usage;
  pending_approval_id: string | null;
}

export interface Usage {
  model_attempts: number;
  tool_executions: number;
  input_tokens: number;
  output_tokens: number;
  complete: boolean;
}

export interface Approval {
  approval_id: string;
  run_id: string;
  kind: string;
  payload_hash: string;
  payload: Record<string, unknown>;
  status: string;
  response: Record<string, unknown> | null;
  checkpoint_ready: boolean;
  created_at: string;
}

export interface Artifact {
  artifact_id: string;
  thread_id: string;
  run_id: string | null;
  kind: "upload" | "output" | "tool_output";
  display_name: string;
  virtual_path: string;
  sha256: string;
  size_bytes: number;
  mime_type: string;
  created_at: string;
  content_url: string;
}

export interface ToolExecution {
  id: string;
  scope: string;
  tool_call_id: string;
  tool_name: string;
  args: Record<string, unknown>;
  status: string;
  result: unknown;
  error_code: string | null;
}

export interface SubagentTask {
  task_id: string;
  run_id: string;
  agent_type: string;
  status: string;
  prompt: string;
  result: Record<string, unknown> | null;
  deadline_at: string;
}

export interface RunEvent {
  version: number;
  run_id: string;
  seq: number;
  type: string;
  scope: string;
  timestamp: string;
  data: Record<string, unknown>;
}
