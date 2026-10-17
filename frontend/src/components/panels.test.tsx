import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ApprovalCard } from "./ApprovalCard";
import { ArtifactPanel } from "./ArtifactPanel";
import { SafeMarkdown } from "./SafeMarkdown";
import type { Approval, Artifact } from "../types";
import { expect, test, vi } from "vitest";

test("审批恢复点未就绪时不能操作，真实参数仍可见", () => {
  const approval: Approval = {
    approval_id: "a1", run_id: "r1", kind: "tool_batch", payload_hash: "a".repeat(64),
    payload: { actions: [{ tool_name: "bash", args: { command: "python report.py" } }] },
    status: "pending", response: null, checkpoint_ready: false, created_at: "2026-01-01",
  };
  const onDecision = vi.fn();
  render(<ApprovalCard approval={approval} busy={false} onDecision={onDecision} />);
  expect(screen.getByText(/python report.py/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "批准并继续" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "批准并继续" }));
  expect(onDecision).not.toHaveBeenCalled();
});

test("Markdown 中的原始脚本不会进入工作台 DOM", () => {
  const { container } = render(<SafeMarkdown>{"# 报告\n<script>window.pwned = true</script>"}</SafeMarkdown>);
  expect(container.querySelector("script")).toBeNull();
  expect(window).not.toHaveProperty("pwned", true);
});

test("HTML 只能在无脚本、无同源权限的 sandbox iframe 中预览", async () => {
  const artifact: Artifact = {
    artifact_id: "f1", thread_id: "t1", run_id: "r1", kind: "output", display_name: "unsafe.html",
    virtual_path: "/mnt/user-data/unsafe.html", sha256: "b".repeat(64), size_bytes: 10,
    mime_type: "text/html", created_at: "2026-01-01", content_url: "/content/f1",
  };
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ text: () => Promise.resolve("<script>parent.pwned=true</script>") }));
  const { container } = render(<ArtifactPanel artifacts={[artifact]} />);
  fireEvent.click(screen.getByText("unsafe.html"));
  await waitFor(() => expect(container.querySelector("iframe")).not.toBeNull());
  const frame = container.querySelector("iframe")!;
  expect(frame.getAttribute("sandbox")).toBe("");
  expect(frame.getAttribute("srcdoc")).toContain("parent.pwned");
  vi.unstubAllGlobals();
});
