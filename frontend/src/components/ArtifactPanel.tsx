import { useEffect, useState } from "react";
import { Download, File, FileCode2, Upload } from "lucide-react";
import type { Artifact } from "../types";
import { SafeMarkdown } from "./SafeMarkdown";

function formatSize(bytes: number) {
  return bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(1)} KB`;
}

export function ArtifactPanel({ artifacts }: { artifacts: Artifact[] }) {
  const [selected, setSelected] = useState<Artifact | null>(null);
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!selected) return;
    let cancelled = false;
    setLoading(true);
    fetch(selected.content_url)
      .then((response) => response.text())
      .then((value) => { if (!cancelled) setText(value); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [selected]);

  return (
    <div className="artifact-panel">
      <div className="artifact-list">
        {artifacts.length === 0 && <div className="empty-small"><File size={20} /><span>上传与生成的文件会出现在这里</span></div>}
        {artifacts.map((artifact) => (
          <button key={artifact.artifact_id} className={`artifact-row ${selected?.artifact_id === artifact.artifact_id ? "selected" : ""}`} onClick={() => setSelected(artifact)}>
            <span className={`file-kind ${artifact.kind}`}>
              {artifact.kind === "upload" ? <Upload size={15} /> : <FileCode2 size={15} />}
            </span>
            <span><strong>{artifact.display_name}</strong><small>{artifact.kind === "upload" ? "上传" : "产物"} · {formatSize(artifact.size_bytes)}</small></span>
          </button>
        ))}
      </div>
      {selected && (
        <div className="preview-shell">
          <div className="preview-head"><span>{selected.display_name}</span><a href={selected.content_url} download={selected.display_name} title="下载文件"><Download size={16} /></a></div>
          <div className="preview-body">
            {loading ? <p className="muted">读取中…</p> : selected.mime_type === "text/markdown" ? (
              <SafeMarkdown>{text}</SafeMarkdown>
            ) : selected.mime_type === "text/html" ? (
              <iframe title={`${selected.display_name} 隔离预览`} sandbox="" referrerPolicy="no-referrer" srcDoc={text} />
            ) : selected.mime_type.startsWith("text/") || selected.mime_type.includes("json") || selected.mime_type.includes("csv") ? (
              <pre>{text}</pre>
            ) : <p className="muted">该格式请下载后查看。</p>}
          </div>
        </div>
      )}
    </div>
  );
}
