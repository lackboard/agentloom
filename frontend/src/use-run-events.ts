import { useEffect, useRef } from "react";
import type { RunEvent } from "./types";

const EVENT_TYPES = [
  "message.delta",
  "message.completed",
  "tool.started",
  "tool.finished",
  "tool.failed",
  "approval.required",
  "approval.resolved",
  "subagent.queued",
  "subagent.started",
  "subagent.finished",
  "subagent.failed",
  "usage.updated",
  "run.started",
  "run.waiting_input",
  "run.finished",
];

export function useRunEvents(runId: string | null, active: boolean, onEvent: (event: RunEvent) => void) {
  const handler = useRef(onEvent);
  useEffect(() => { handler.current = onEvent; }, [onEvent]);

  useEffect(() => {
    if (!runId || !active) return;
    const source = new EventSource(`/api/runs/${runId}/events?after_seq=0`);
    const receive = (raw: Event) => {
      try {
        handler.current(JSON.parse((raw as MessageEvent<string>).data) as RunEvent);
      } catch {
        // 单条畸形事件不能终止后续 SSE；服务端 REST 仍可用于恢复。
      }
    };
    for (const type of EVENT_TYPES) source.addEventListener(type, receive);
    return () => source.close();
  }, [runId, active]);
}
