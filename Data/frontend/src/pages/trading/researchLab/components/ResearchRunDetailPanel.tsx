import { RingGauge } from "../../shared";
import {
  actionAvailability,
  asRecord,
  autonomyCeilingPct,
  durationLabel,
  resolveRunStatus,
  statusLabel,
  statusTone,
  type LabRunRecord,
  type LearningRecord,
  type PhaseState,
} from "../viewModels";

export function ResearchRunDetailPanel({
  lab,
  learning,
  phases,
  busyAction,
  onControl,
  onProbeFeed,
  feedHealth,
}: {
  lab: LabRunRecord | null;
  learning: LearningRecord | null;
  phases: PhaseState[];
  busyAction: string | null;
  onControl: (action: "start" | "pause" | "resume" | "cancel") => void;
  onProbeFeed: () => void;
  feedHealth: Record<string, unknown> | null;
}) {
  if (!lab) {
    return (
      <aside className="lv-rl-detail" aria-label="Run details">
        <div className="lv-rl-empty">
          <strong>No run selected</strong>
          Select a research run from the left rail, or create one.
        </div>
      </aside>
    );
  }

  const status = resolveRunStatus(lab, learning);
  const tone = statusTone(status);
  const actions = actionAvailability(status);
  const meta = asRecord(lab.metadata) || {};
  const learningMeta = asRecord(learning?.metadata);
  const hyp = String(meta.hypothesis || learningMeta?.hypothesis || "");
  const notes = meta.notes != null ? String(meta.notes) : "";
  const ceiling = String(lab.autonomy_ceiling || meta.autonomy_ceiling || "A1");
  const ceilingPct = autonomyCeilingPct(ceiling);
  const started = lab.created_at != null ? String(lab.created_at) : learning?.created_at != null ? String(learning.created_at) : null;
  const updated = lab.updated_at != null ? String(lab.updated_at) : learning?.updated_at != null ? String(learning.updated_at) : null;
  const worker = learning?.job_id != null ? String(learning.job_id) : lab.job_id != null ? String(lab.job_id) : null;
  const family =
    learning?.strategy_id != null
      ? String(learning.strategy_id)
      : lab.strategy_id != null
        ? String(lab.strategy_id)
        : null;
  const source = String(lab.source_id || learning?.source_id || "—");
  const busy = busyAction != null;

  return (
    <aside className="lv-rl-detail" aria-label="Run details">
      <div className="lv-rl-detail-head">
        <div>
          <h2>{String(lab.name || lab.lab_id)}</h2>
          <div className="lv-rl-detail-id">{String(lab.lab_id)}</div>
        </div>
        <span className={`lv-rl-pill is-${tone}`}>{statusLabel(status)}</span>
      </div>

      <dl className="lv-rl-dl">
        <div>
          <dt>Source / dataset</dt>
          <dd>{source}</dd>
        </div>
        <div>
          <dt>Strategy</dt>
          <dd>
            {family || "—"}
            {lab.strategy_version != null ? ` · v${String(lab.strategy_version)}` : ""}
          </dd>
        </div>
        <div>
          <dt>Hypothesis</dt>
          <dd>{hyp || "—"}</dd>
        </div>
        {notes ? (
          <div>
            <dt>Notes</dt>
            <dd>{notes}</dd>
          </div>
        ) : null}
        <div>
          <dt>Started</dt>
          <dd>{started ? started.replace("T", " ").slice(0, 19) : "—"}</dd>
        </div>
        <div>
          <dt>Last update</dt>
          <dd>{updated ? updated.replace("T", " ").slice(0, 19) : "—"}</dd>
        </div>
        <div>
          <dt>Running time</dt>
          <dd>{durationLabel(started, statusTone(status) === "running" ? undefined : updated) || "—"}</dd>
        </div>
        <div>
          <dt>Active worker / job</dt>
          <dd>{worker || "inline / none"}</dd>
        </div>
        {lab.outcome != null ? (
          <div>
            <dt>Outcome</dt>
            <dd>{String(lab.outcome)}</dd>
          </div>
        ) : null}
        {lab.error || learning?.error ? (
          <div>
            <dt>Error</dt>
            <dd style={{ color: "#f87171" }}>{String(lab.error || learning?.error)}</dd>
          </div>
        ) : null}
      </dl>

      <p className="lv-rl-section-title">Autonomy ceiling</p>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 14 }}>
        <RingGauge
          value={ceilingPct ?? 0}
          label={ceiling}
          display={ceiling}
          color="#d4af37"
        />
        <p className="lv-rl-card-hint" style={{ margin: 0 }}>
          A5 live trading remains blocked by product truth. Ceiling is an autonomy bound, not proof of edge.
        </p>
      </div>

      <p className="lv-rl-section-title">Phases</p>
      <ul className="lv-rl-phases">
        {phases.map((p) => (
          <li key={p.id} className={`is-${p.state}`}>
            <span className="lv-rl-step-dot" />
            {p.label}
            <span style={{ marginLeft: "auto", fontSize: 10, textTransform: "uppercase" }}>{p.state}</span>
          </li>
        ))}
      </ul>

      <div className="lv-rl-actions">
        <button
          type="button"
          className="lv-rl-btn is-primary"
          disabled={busy || !actions.canStart}
          onClick={() => onControl("start")}
        >
          {busyAction === "start" ? "Starting…" : "Start"}
        </button>
        <button
          type="button"
          className="lv-rl-btn"
          disabled={busy || !actions.canPause}
          onClick={() => onControl("pause")}
        >
          {busyAction === "pause" ? "Pausing…" : "Pause"}
        </button>
        <button
          type="button"
          className="lv-rl-btn"
          disabled={busy || !actions.canResume}
          onClick={() => onControl("resume")}
        >
          {busyAction === "resume" ? "Resuming…" : "Resume"}
        </button>
        <button
          type="button"
          className="lv-rl-btn is-danger"
          disabled={busy || !actions.canCancel}
          onClick={() => onControl("cancel")}
        >
          {busyAction === "cancel" ? "Cancelling…" : "Cancel"}
        </button>
        <button type="button" className="lv-rl-btn is-ghost" disabled title="Clone is not exposed by the lab API">
          Clone Run
        </button>
        <button type="button" className="lv-rl-btn is-ghost" disabled title="Export is not exposed by the lab API">
          Export Results
        </button>
      </div>

      <div style={{ marginTop: 12 }}>
        <button type="button" className="lv-rl-btn is-ghost" disabled={busy} onClick={onProbeFeed}>
          {busyAction === "probe" ? "Probing…" : "Probe feed health"}
        </button>
        {feedHealth ? (
          <p className="lv-rl-card-hint" style={{ marginTop: 6 }}>
            Feed {String(feedHealth.status)} · staleness={String(feedHealth.staleness_seconds)}s
          </p>
        ) : null}
      </div>
    </aside>
  );
}
