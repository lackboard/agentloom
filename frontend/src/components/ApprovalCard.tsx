import { Check, ShieldAlert, X } from "lucide-react";
import type { Approval } from "../types";

export function ApprovalCard({
  approval,
  busy,
  onDecision,
}: {
  approval: Approval;
  busy: boolean;
  onDecision: (decision: "approve" | "reject") => void;
}) {
  const payload = approval.payload;
  const calls = Array.isArray(payload.actions) ? payload.actions : [];
  const files = Array.isArray(payload.files) ? payload.files as Array<Record<string, unknown>> : [];
  const coderChange = approval.kind === "coder_change";
  const canDecide = approval.status === "pending" && approval.checkpoint_ready && !busy;
  return (
    <section className="approval-card" aria-label="待审批操作">
      <div className="approval-heading">
        <span className="approval-icon"><ShieldAlert size={18} /></span>
        <div><strong>{coderChange ? "接纳 Coder 变更" : "需要你的确认"}</strong><p>{coderChange ? "批准后先在 Coder 私有目录运行 Docker 验证，通过后才写入父工作区。" : "Agent 已暂停，确认后才会继续执行。"}</p></div>
      </div>
      <div className="approval-body">
        {coderChange ? <>
          {files.map((file, index) => <pre key={index}>{String(file.diff ?? JSON.stringify(file, null, 2))}</pre>)}
          <pre>{JSON.stringify({ verification_command: payload.verification_command, manifest_hash: payload.manifest_hash }, null, 2)}</pre>
        </> : calls.length > 0 ? calls.map((call, index) => (
          <pre key={index}>{JSON.stringify(call, null, 2)}</pre>
        )) : <pre>{JSON.stringify(payload, null, 2)}</pre>}
      </div>
      {!approval.checkpoint_ready && <p className="muted">正在保存恢复点…</p>}
      <div className="approval-actions">
        <button className="button ghost danger" disabled={!canDecide} onClick={() => onDecision("reject")}><X size={16} />拒绝</button>
        <button className="button primary" disabled={!canDecide} onClick={() => onDecision("approve")}><Check size={16} />{coderChange ? "批准、验证并接纳" : "批准并继续"}</button>
      </div>
    </section>
  );
}
