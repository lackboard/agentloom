import { emptyRunState, hydrateMessages, reduceRunEvent } from "./run-state";
import type { RunEvent } from "./types";
import { expect, test } from "vitest";

function event(seq: number, type: string, data: Record<string, unknown>, scope = "lead"): RunEvent {
  return { version: 1, run_id: "run-1", seq, type, scope, timestamp: "2026-01-01T00:00:00Z", data };
}

test("重复 SSE 只应用一次，最终消息按稳定 ID 覆盖增量", () => {
  let state = emptyRunState("run-1");
  const delta = event(2, "message.delta", { message_id: "m1", role: "assistant", delta: "半" });
  state = reduceRunEvent(state, delta);
  state = reduceRunEvent(state, delta);
  expect(state.messages.m1.content.text).toBe("半");
  expect(state.timeline).toHaveLength(1);

  state = reduceRunEvent(state, event(3, "message.completed", { message_id: "m1", role: "assistant", content: { text: "完整答案" } }));
  expect(state.messages.m1.content.text).toBe("完整答案");
  expect(state.messages.m1.status).toBe("completed");

  state = reduceRunEvent(state, event(4, "message.delta", { message_id: "m1", delta: "不应追加" }));
  expect(state.messages.m1.content.text).toBe("完整答案");
});

test("子任务按 task_id 归属，刷新后的 REST 完整消息覆盖 partial", () => {
  let state = emptyRunState("run-1");
  state = reduceRunEvent(state, event(2, "subagent.queued", { task_id: "task-a", agent_type: "researcher", status: "queued" }, "subagent:task-a"));
  state = reduceRunEvent(state, event(3, "subagent.started", { task_id: "task-a", status: "running" }, "subagent:task-a"));
  state = reduceRunEvent(state, event(4, "subagent.finished", { task_id: "task-b", agent_type: "coder", status: "succeeded" }, "subagent:task-b"));
  expect(state.subtasks["task-a"].status).toBe("running");
  expect(state.subtasks["task-b"].agent_type).toBe("coder");

  state = reduceRunEvent(state, event(5, "message.delta", { message_id: "m2", delta: "旧" }));
  state = hydrateMessages(state, [{ id: "m2", seq: 9, role: "assistant", content: { text: "数据库完整投影" }, status: "completed" }]);
  expect(state.messages.m2.content.text).toBe("数据库完整投影");
});
