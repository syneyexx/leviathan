import type { TrainingWorkspace } from "../../hooks/useTrainingWorkspace";
import { Badge, Panel } from "../ui";

type Props = {
  ws: TrainingWorkspace;
};

function CkptIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
      <path d="M5 19h14a2 2 0 0 0 2-2V9l-5-5H5a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2z" />
      <path d="M14 4v5h5" />
    </svg>
  );
}

function basename(path: string): string {
  const parts = path.replace(/\\/g, "/").split("/");
  return parts[parts.length - 1] || path;
}

function formatWhen(iso: string): string {
  const d = Date.parse(iso);
  if (Number.isNaN(d)) return iso;
  return new Date(d).toLocaleString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    day: "2-digit",
    month: "short",
  });
}

export function TrainingCheckpointsPanel({ ws }: Props) {
  const bestId =
    typeof ws.selectedJob?.metricsSummary?.best_checkpoint_id === "string"
      ? ws.selectedJob.metricsSummary.best_checkpoint_id
      : null;

  return (
    <Panel title="Checkpoints" icon={<CkptIcon />} className="lv-v2-training-checkpoints">
      {!ws.selectedJob ? (
        <p className="lv-v2-muted">Selecteer een run.</p>
      ) : ws.checkpoints.length === 0 ? (
        <p className="lv-v2-muted">Nog geen checkpoints.</p>
      ) : (
        <div className="lv-v2-training-checkpoints__table-wrap">
          <table className="lv-v2-training-checkpoints__table">
            <thead>
              <tr>
                <th>Naam</th>
                <th>Step</th>
                <th>Epoch</th>
                <th>Grootte</th>
                <th>Tijd</th>
              </tr>
            </thead>
            <tbody>
              {ws.checkpoints.map((ck) => {
                const size =
                  typeof ck.metadata?.byteSize === "number"
                    ? ws.formatBytes(ck.metadata.byteSize)
                    : typeof ck.metadata?.sizeBytes === "number"
                      ? ws.formatBytes(ck.metadata.sizeBytes)
                      : "—";
                const isBest = bestId === ck.checkpointId;
                return (
                  <tr key={ck.checkpointId} className={isBest ? "is-best" : undefined}>
                    <td>
                      {basename(ck.path)}
                      {isBest ? (
                        <Badge tone="success" className="lv-v2-training-checkpoints__best">
                          best
                        </Badge>
                      ) : null}
                    </td>
                    <td>{ck.step ?? "—"}</td>
                    <td>{ck.epoch ?? "—"}</td>
                    <td>{size}</td>
                    <td>{formatWhen(ck.createdAt)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}
