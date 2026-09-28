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
  onClose,
}: {
  lab: LabRunRecord | null;
  learning: LearningRecord | null;
  phases: PhaseState[];
  busyAction: string | null;
  onControl: (action: "start" | "pause" | "resume" | "cancel") => void;
  onClose?: () => void;
}) {
  if (!lab) {
    return (
      <aside className="lv-rl-detail" aria-label="Run details">
        <div className="lv-rl-detail-scroll">
          <div className="lv-rl-detail-chrome">
            <h2>Run details</h2>
          </div>
          <div className="lv-rl-empty">
            <strong>No run selected</strong>
            Select a research run from the left rail, or create one.
          </div>
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
  const ceilingPct = autonomyCeilingPct(ceiling) ?? 20;
  const started =
    lab.created_at != null
      ? String(lab.created_at)
      : learning?.created_at != null
        ? String(learning.created_at)
        : null;
  const updated =
    lab.updated_at != null
      ? String(lab.updated_at)
      : learning?.updated_at != null
        ? String(learning.updated_at)
        : null;
  const worker =
    learning?.job_id != null
      ? String(learning.job_id)
      : lab.job_id != null
        ? String(lab.job_id)
        : null;
  const strategy =
    lab.strategy_id != null
      ? String(lab.strategy_id)
      : learning?.strategy_id != null
        ? String(learning.strategy_id)
        : "—";
  const source = String(lab.source_id || learning?.source_id || "—");
  const busy = busyAction != null;
  const familyHint =
    learning && asRecord(learning.learner_state)?.family_probabilities
      ? "Multi-strategy (adaptive)"
      : String((asRecord(lab.campaign) || {}).name || "Strategy search");

  return (
    <aside className="lv-rl-detail" aria-label="Run details">
      <div className="lv-rl-detail-scroll">
        <div className="lv-rl-detail-chrome">
          <h2>Run details</h2>
          <div className="lv-rl-detail-chrome-actions">
            <button type="button" className="lv-rl-btn is-ghost" disabled title="Edit metadata is not exposed by the lab API">
              Edit
            </button>
            {onClose ? (
              <button type="button" className="lv-rl-btn is-icon" onClick={onClose} aria-label="Deselect run">
                ✕
              </button>
            ) : null}
          </div>
        </div>

        <h3 className="lv-rl-detail-name">{String(lab.name || lab.lab_id)}</h3>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
          <span className={`lv-rl-pill is-${tone}`}>{statusLabel(status)}</span>
        </div>
        <div className="lv-rl-detail-id">ID: {String(lab.lab_id)}</div>

        <dl className="lv-rl-dl">
          <div>
            <dt>Run mode</dt>
            <dd>{String(lab.run_mode || meta.run_mode || "—")}</dd>
          </div>
          <div>
            <dt>Source / dataset</dt>
            <dd>{source}</dd>
          </div>
          <div>
            <dt>Strategy family</dt>
            <dd>
              {familyHint}
              {lab.strategy_version != null ? ` · v${String(lab.strategy_version)}` : ""}
              <div style={{ color: "rgba(232,228,220,0.4)", fontSize: 10, marginTop: 2 }}>{strategy}</div>
            </dd>
          </div>
          <div>
            <dt>Research objective</dt>
            <dd>
              {String(lab.research_objective || meta.research_objective || "") || hyp || "—"}
            </dd>
          </div>
          <div>
            <dt>Hypothesis</dt>
            <dd>{hyp || "—"}</dd>
          </div>
          <div>
            <dt>Notes</dt>
            <dd>{notes || "—"}</dd>
          </div>
        </dl>

        <div className="lv-rl-autonomy">
          <div className="hdr">
            <span>Autonomy ceiling</span>
            <strong>
              {ceiling} · {Math.round(ceilingPct)}%
            </strong>
          </div>
          <div className="track">
            <i style={{ width: `${ceilingPct}%` }} />
          </div>
        </div>

        <p className="lv-rl-sec-label">Phases</p>
        <ul className="lv-rl-phases">
          {phases.map((p) => (
            <li key={p.id} className={`is-${p.state}`}>
              <span className="mark" aria-hidden="true">
                {p.state === "done" ? "✓" : p.state === "active" ? "●" : p.state === "failed" ? "!" : "○"}
              </span>
              <span>{p.label}</span>
              <span style={{ marginLeft: "auto", fontSize: 9, textTransform: "uppercase", letterSpacing: "0.08em" }}>
                {p.state}
              </span>
            </li>
          ))}
        </ul>

        <div className="lv-rl-meta-grid">
          <div>
            <div className="k">Started</div>
            <div className="v">{started ? started.replace("T", " ").slice(0, 19) : "—"}</div>
          </div>
          <div>
            <div className="k">Last update</div>
            <div className="v">{updated ? updated.replace("T", " ").slice(0, 19) : "—"}</div>
          </div>
          <div>
            <div className="k">Running time</div>
            <div className="v">
              {durationLabel(started, statusTone(status) === "running" ? undefined : updated) || "—"}
            </div>
          </div>
          <div>
            <div className="k">Active worker</div>
            <div className="v">{worker || "inline / none"}</div>
          </div>
        </div>

        {lab.error || learning?.error ? (
          <p className="lv-rl-card-hint" style={{ color: "#f87171", marginBottom: 10 }}>
            {String(lab.error || learning?.error)}
          </p>
        ) : null}

        <div className="lv-rl-actions">
          {actions.canStart ? (
            <button
              type="button"
              className="lv-rl-btn is-primary"
              disabled={busy}
              onClick={() => onControl("start")}
            >
              {busyAction === "start" ? "…" : "Start"}
            </button>
          ) : (
            <button
              type="button"
              className="lv-rl-btn is-pause"
              disabled={busy || !actions.canPause}
              onClick={() => onControl("pause")}
            >
              {busyAction === "pause" ? "…" : "Pause"}
            </button>
          )}
          <button
            type="button"
            className="lv-rl-btn"
            disabled={busy || !actions.canResume}
            onClick={() => onControl("resume")}
          >
            {busyAction === "resume" ? "…" : "Resume"}
          </button>
          <button
            type="button"
            className="lv-rl-btn is-danger"
            disabled={busy || !actions.canCancel}
            onClick={() => onControl("cancel")}
          >
            {busyAction === "cancel" ? "…" : "Cancel"}
          </button>
        </div>
        <div className="lv-rl-actions-secondary">
          <button type="button" className="lv-rl-btn is-ghost" disabled title="Clone is not exposed by the lab API">
            Clone Run
          </button>
          <button type="button" className="lv-rl-btn is-ghost" disabled title="Export is not exposed by the lab API">
            Export Results
          </button>
          <button type="button" className="lv-rl-btn is-icon" disabled title="More actions unavailable">
            ⋯
          </button>
        </div>
      </div>
    </aside>
  );
}
