import type { DerivedEvent, LabRunRecord } from "../viewModels";

export function ResearchLabLogsPanel({
  events,
  runTrials,
  loading,
}: {
  events: DerivedEvent[];
  runTrials: LabRunRecord[];
  loading?: boolean;
}) {
  if (loading) {
    return (
      <div className="lv-rl-skel">
        <div className="lv-rl-skel-bar" style={{ height: 160 }} />
      </div>
    );
  }

  if (events.length === 0 && runTrials.length === 0) {
    return (
      <div className="lv-rl-empty">
        <strong>No logs yet</strong>
        There is no dedicated lab event-stream endpoint. This panel derives a timeline from learning
        status, generation summaries, lessons, and candidate stage failures when present.
      </div>
    );
  }

  return (
    <div style={{ display: "grid", gap: 10 }}>
      <article className="lv-rl-card">
        <h3>Derived run timeline</h3>
        <p className="lv-rl-card-hint" style={{ marginBottom: 8 }}>
          Honest composite log — not a live worker syslog.
        </p>
        {events.length === 0 ? (
          <p className="lv-rl-card-hint">No derived events.</p>
        ) : (
          <ul className="lv-rl-log">
            {events.map((e) => (
              <li key={e.id}>
                <span className="ts">{e.ts ? e.ts.replace("T", " ").slice(0, 19) : "—"}</span>
                <span className={`lvl is-${e.level}`}>{e.level}</span>
                <span>
                  <em style={{ color: "rgba(232,228,220,0.45)", fontStyle: "normal" }}>[{e.source}] </em>
                  {e.message}
                </span>
              </li>
            ))}
          </ul>
        )}
      </article>

      {runTrials.length > 0 ? (
        <article className="lv-rl-card">
          <h3>Run trial ledger ({runTrials.length})</h3>
          <div className="lv-rl-table-wrap">
            <table className="lv-rl-table">
              <thead>
                <tr>
                  <th>Trial</th>
                  <th>Strategy</th>
                  <th>Status</th>
                  <th>Hypothesis</th>
                </tr>
              </thead>
              <tbody>
                {runTrials.slice(0, 40).map((t) => (
                  <tr key={String(t.trial_id || t.trialId)}>
                    <td>{String(t.trial_id || t.trialId || "—").slice(0, 14)}</td>
                    <td>{String(t.strategy_id || t.strategyId || "—").slice(0, 14)}</td>
                    <td>{String(t.status || "—")}</td>
                    <td>{String(t.hypothesis || "").slice(0, 60) || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </article>
      ) : null}
    </div>
  );
}
