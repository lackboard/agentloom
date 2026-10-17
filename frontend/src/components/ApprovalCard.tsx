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
  const canDecide = approval.status === "pending" && approval.checkpoint_ready && !busy;
  return (
    <section className="approval-card" aria-label="待审批操作">
      <div className="approval-heading">
        <span className="approval-icon"><ShieldAlert size={18} /></span>
        <div><strong>需要你的确认</strong><p>Agent 已暂停，确认后才会继续执行。</p></div>
      </div>
      <div className="approval-body">
        {calls.length > 0 ? calls.map((call, index) => (
          <pre key={index}>{JSON.stringify(call, null, 2)}</pre>
        )) : <pre>{JSON.stringify(payload, null, 2)}</pre>}
      </div>
      {!approval.checkpoint_ready && <p className="muted">正在保存恢复点…</p>}
      <div className="approval-actions">
        <button className="button ghost danger" disabled={!canDecide} onClick={() => onDecision("reject")}><X size={16} />拒绝</button>
        <button className="button primary" disabled={!canDecide} onClick={() => onDecision("approve")}><Check size={16} />批准并继续</button>
      </div>
    </section>
  );
}
