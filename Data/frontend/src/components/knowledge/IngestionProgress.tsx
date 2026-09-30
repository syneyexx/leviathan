import type { KnowledgeLibraryWorkspace } from "../../pages/knowledge/useKnowledgeLibraryWorkspace";

/**
 * Active ingestion progress bar — sourced from SourceIngestion status polling.
 * Unmeasured progress renders "UNMEASURED", never a fabricated percentage.
 */
export function IngestionProgress({ ws }: { ws: KnowledgeLibraryWorkspace }) {
  const pct =
    ws.activeProgress && typeof ws.activeProgress.progress_pct === "number"
      ? ws.activeProgress.progress_pct
      : null;
  const measured = ws.activeProgress?.measured === true;
  const phase = String(ws.activeProgress?.phase || ws.activeProgress?.status || "—");

  return (
    <div className="lv-v2-kl-ingest-progress">
      <header>
        <h4>Ingestie Voortgang</h4>
        {ws.ingestionError ? <span className="lv-v2-kl-warn">{ws.ingestionError}</span> : null}
      </header>
      {ws.activeIngestionId ? (
        <>
          <p className="lv-v2-kl-ingest-line">
            Processing: <strong>{String(ws.activeProgress?.filename || ws.activeIngestionId)}</strong>
          </p>
          <div className="lv-v2-kl-progress">
            <div
              style={{
                width: measured && pct != null ? `${Math.max(0, Math.min(100, pct))}%` : "0%",
              }}
            />
          </div>
          <p className="lv-v2-kl-ingest-meta">
            <strong>{measured && pct != null ? `${pct}%` : "UNMEASURED"}</strong>
            <span>
              {typeof ws.activeProgress?.bytes_processed === "number" &&
              typeof ws.activeProgress?.bytes_total === "number"
                ? `${ws.formatBytes(ws.activeProgress.bytes_processed as number)} / ${ws.formatBytes(ws.activeProgress.bytes_total as number)}`
                : phase}
            </span>
            <span>
              {typeof ws.activeProgress?.eta_seconds === "number"
                ? `${Math.max(1, Math.round((ws.activeProgress.eta_seconds as number) / 60))} min resterend`
                : "ETA onbekend"}
            </span>
          </p>
          <div className="lv-v2-kl-detail__actions">
            <button type="button" onClick={() => void ws.onCancelIngestion()} disabled={ws.busy}>
              Cancel
            </button>
            <button type="button" onClick={() => void ws.onRetryIngestion()} disabled={ws.busy}>
              Retry
            </button>
            {typeof ws.activeProgress?.brain_failed === "number" && (ws.activeProgress.brain_failed as number) > 0 ? (
              <button type="button" onClick={() => void ws.onBrainRetryIngestion()} disabled={ws.busy}>
                Brain Retry
              </button>
            ) : null}
          </div>
        </>
      ) : (
        <p className="lv-v2-kl-muted">Geen actieve ingestie</p>
      )}
    </div>
  );
}
