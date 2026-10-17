import { Activity, Bot, Wrench } from "lucide-react";
import type { TraceSpan } from "../types";

function SpanIcon({ kind }: { kind: TraceSpan["kind"] }) {
  if (kind === "model") return <Bot size={14} />;
  if (kind === "tool") return <Wrench size={14} />;
  return <Activity size={14} />;
}

function SpanRow({ span, depth }: { span: TraceSpan; depth: number }) {
  const tokens = Number(span.attributes.input_tokens ?? 0) + Number(span.attributes.output_tokens ?? 0);
  return (
    <div className="trace-row" style={{ paddingLeft: `${14 + depth * 22}px` }} data-kind={span.kind}>
      <span className={`trace-icon trace-${span.kind}`}><SpanIcon kind={span.kind} /></span>
      <div className="trace-copy">
        <strong>{span.name}</strong>
        <small>
          {span.kind} · {span.status}
          {tokens ? ` · ${tokens} tokens` : ""}
          {span.error_code ? ` · ${span.error_code}` : ""}
        </small>
      </div>
      <span className="trace-duration">{span.duration_ms == null ? "执行中" : `${span.duration_ms} ms`}</span>
    </div>
  );
}

export function TraceTimeline({ spans }: { spans: TraceSpan[] }) {
  const children = new Map<string | null, TraceSpan[]>();
  const ids = new Set(spans.map((span) => span.span_id));
  for (const span of spans) {
    const parent = span.parent_span_id && ids.has(span.parent_span_id) ? span.parent_span_id : null;
    children.set(parent, [...(children.get(parent) ?? []), span]);
  }
  const rows: Array<{ span: TraceSpan; depth: number }> = [];
  const visit = (parent: string | null, depth: number) => {
    for (const span of children.get(parent) ?? []) {
      rows.push({ span, depth });
      visit(span.span_id, depth + 1);
    }
  };
  visit(null, 0);
  if (!rows.length) return null;
  return (
    <section className="trace-timeline">
      <div className="timeline-title"><Activity size={16} />运行时间线</div>
      {rows.map(({ span, depth }) => <SpanRow key={span.span_id} span={span} depth={depth} />)}
    </section>
  );
}
