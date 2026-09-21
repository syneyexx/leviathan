"use client";

import { useEffect, useState } from "react";
import { Download, Eye, Loader2, Trash2, RefreshCcw } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Panel, StatusBadge } from "@/components/hades/ui";
import { formatBytes, formatDate, hadesApi, HadesArtifact } from "@/lib/hades-api";

type Props = {
  conversationId?: string;
  taskId?: string;
  title?: string;
  focusArtifactId?: string;
  onReuse?: (artifact: HadesArtifact) => void;
};

export function ResultsPanel({ conversationId, taskId, title = "Resultaten", focusArtifactId, onReuse }: Props) {
  const [items, setItems] = useState<HadesArtifact[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [preview, setPreview] = useState<string | null>(null);
  const [previewNote, setPreviewNote] = useState("");
  const [loading, setLoading] = useState(false);

  const refresh = async () => {
    setLoading(true);
    try {
      const list = await hadesApi.artifacts({ conversation_id: conversationId, task_id: taskId });
      setItems(list);
      setSelectedId((current) => {
        if (focusArtifactId && list.some((item) => item.id === focusArtifactId)) return focusArtifactId;
        return list.some((item) => item.id === current) ? current : list[0]?.id || "";
      });
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Resultaten laden mislukt.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void refresh();
  }, [conversationId, taskId, focusArtifactId]);  

  useEffect(() => {
    if (!selectedId) {
      setPreview(null);
      setPreviewNote("");
      return;
    }
    hadesApi.artifactPreview(selectedId)
      .then((result) => {
        setPreview(result.previewable ? result.text : null);
        setPreviewNote(result.reason || (result.truncated ? "Voorbeeld afgekapt." : ""));
      })
      .catch((reason: Error) => {
        setPreview(null);
        setPreviewNote(reason.message);
      });
  }, [selectedId]);

  const selected = items.find((item) => item.id === selectedId);

  return (
    <Panel title={title} actions={<Button variant="ghost" size="icon" onClick={() => void refresh()} aria-label="Resultaten vernieuwen"><RefreshCcw /></Button>}>
      {loading ? <div className="page-state"><Loader2 className="spin" />Resultaten laden…</div> : null}
      <div className="results-panel">
        <div className="results-list">
          {items.map((item) => (
            <button key={item.id} type="button" className={item.id === selectedId ? "result-item active" : "result-item"} onClick={() => setSelectedId(item.id)}>
              <strong>{item.name}</strong>
              <small>{item.kind} · {item.mime_type} · {formatBytes(item.size_bytes)}</small>
              <StatusBadge tone={item.status === "ready" ? "success" : item.status === "failed" ? "danger" : "warning"}>{item.status}</StatusBadge>
              {item.metadata && typeof item.metadata === "object" && ("success" in item.metadata || "execution_id" in item.metadata) ? (
                <small>
                  {typeof item.metadata.execution_id === "string" ? `exec ${String(item.metadata.execution_id).slice(0, 10)} · ` : ""}
                  {typeof item.metadata.plugin_id === "string" ? `${item.metadata.plugin_id}/${String(item.metadata.tool_name || "")} · ` : ""}
                  {item.metadata.success === true ? "tool ok" : item.metadata.success === false ? "tool failed" : ""}
                  {typeof item.metadata.persistence_verified === "boolean"
                    ? (item.metadata.persistence_verified ? " · persist ok" : " · persist niet geverifieerd")
                    : ""}
                </small>
              ) : null}
            </button>
          ))}
          {!items.length && !loading ? <p className="empty-copy">Nog geen beheerde resultaten.</p> : null}
        </div>
        {selected ? (
          <div className="results-detail">
            <div className="result-meta">
              <div>
                <strong>{selected.name}</strong>
                <small>v{selected.version} · {formatDate(selected.updated_at)} · checksum {selected.checksum_sha256.slice(0, 12)}…</small>
              </div>
              <div className="result-actions">
                {selected.status === "ready" ? (
                  <a className="button-link" href={hadesApi.artifactDownloadUrl(selected.id)} download={selected.name}><Download />Download</a>
                ) : null}
                {onReuse && selected.status === "ready" ? (
                  <Button variant="outline" size="sm" onClick={() => onReuse(selected)}><Eye />Hergebruik</Button>
                ) : null}
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label="Verwijderen"
                  onClick={async () => {
                    await hadesApi.deleteArtifact(selected.id);
                    toast.success("Resultaat verwijderd.");
                    await refresh();
                  }}
                >
                  <Trash2 />
                </Button>
              </div>
            </div>
            {preview ? <pre className="artifact-preview safe-preview">{preview}</pre> : <p className="empty-copy">{previewNote || "Geen veilige preview."}</p>}
          </div>
        ) : null}
      </div>
    </Panel>
  );
}
