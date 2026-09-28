import { asNum, asRecord, fmtMetric } from "../viewModels";

function measuredValue(raw: unknown): { value: string; status: string } {
  const rec = asRecord(raw);
  if (!rec) {
    if (raw == null || raw === "") return { value: "—", status: "UNMEASURED" };
    return { value: String(raw), status: "MEASURED" };
  }
  const status = String(rec.status || "UNMEASURED").toUpperCase();
  if (status !== "MEASURED") {
    return {
      value: rec.reason != null ? String(rec.reason) : "—",
      status,
    };
  }
  if (rec.value == null) return { value: "—", status: "UNMEASURED" };
  const n = asNum(rec.value);
  return {
    value: n != null ? fmtMetric(n, 4) : String(rec.value),
    status: "MEASURED",
  };
}

function snapshotRows(snapshot: Record<string, unknown> | undefined): { key: string; value: string; status: string }[] {
  if (!snapshot) return [];
  const keys = [
    "returns",
    "momentum",
    "trend",
    "realized_vol",
    "volume_state",
    "rsi",
    "adx",
    "atr",
    "regime_labels",
    "data_health",
    "market_state",
  ];
  const rows: { key: string; value: string; status: string }[] = [];
  for (const key of keys) {
    if (!(key in snapshot)) continue;
    const m = measuredValue(snapshot[key]);
    rows.push({ key, value: m.value, status: m.status });
  }
  return rows;
}

export function ResearchLabPerceptionPanel({
  perception,
  status,
  loading,
}: {
  perception: Record<string, unknown> | null;
  status: string | null;
  loading?: boolean;
}) {
  if (loading) {
    return (
      <div className="lv-rl-skel">
        <div className="lv-rl-skel-bar" style={{ height: 160 }} />
      </div>
    );
  }

  const overall = String(status || "UNMEASURED").toUpperCase();
  if (!perception || overall === "UNMEASURED") {
    return (
      <div className="lv-rl-empty">
        <strong>UNMEASURED</strong>
        No research perception snapshot is stored for this lab yet. Numeric features appear after a
        research cycle observes READY bars. Chart vision remains UNAVAILABLE until enabled and measured.
      </div>
    );
  }

  const envelope = perception;
  const snapshot =
    asRecord(envelope.snapshot) ||
    (envelope.symbol != null || envelope.returns != null ? envelope : undefined);
  const rows = snapshotRows(snapshot);
  const chartStatus = String(
    envelope.chart_status || snapshot?.chart_status || "UNAVAILABLE",
  ).toUpperCase();
  const conflictsRaw = envelope.conflicts ?? snapshot?.conflicts;
  const conflicts = Array.isArray(conflictsRaw)
    ? conflictsRaw.map((c) => asRecord(c) || { detail: String(c) })
    : [];
  const regime = String(envelope.regime || snapshot?.regime || "—");
  const asOf = String(envelope.as_of || snapshot?.as_of || "—");
  const symbol = String(snapshot?.symbol || envelope.symbol || "—");
  const timeframe = String(snapshot?.timeframe || envelope.timeframe || "—");

  return (
    <div style={{ display: "grid", gap: 10 }}>
      <article className="lv-rl-card">
        <h3>Perception status</h3>
        <div className="lv-rl-grid-4" style={{ marginTop: 8 }}>
          <div>
            <div className="k">Overall</div>
            <div className="v">{overall}</div>
          </div>
          <div>
            <div className="k">Chart vision</div>
            <div className="v">{chartStatus === "MEASURED" ? "MEASURED" : "UNAVAILABLE"}</div>
          </div>
          <div>
            <div className="k">Symbol / TF</div>
            <div className="v">
              {symbol} · {timeframe}
            </div>
          </div>
          <div>
            <div className="k">As of</div>
            <div className="v">{asOf !== "—" ? asOf.replace("T", " ").slice(0, 19) : "—"}</div>
          </div>
        </div>
        <p className="lv-rl-card-hint" style={{ marginTop: 8 }}>
          Regime label: {regime}. Chart status is UNAVAILABLE when vision is disabled or not measured —
          never treated as a measured edge.
        </p>
      </article>

      <article className="lv-rl-card">
        <h3>Numeric snapshot</h3>
        {rows.length === 0 ? (
          <div className="lv-rl-empty" style={{ padding: 14 }}>
            <strong>EMPTY / UNMEASURED</strong>
            Perception envelope present but no numeric feature rows recorded.
          </div>
        ) : (
          <div className="lv-rl-table-wrap">
            <table className="lv-rl-table">
              <thead>
                <tr>
                  <th>Feature</th>
                  <th>Value</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.key}>
                    <td>{r.key}</td>
                    <td>{r.value}</td>
                    <td>{r.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </article>

      <article className="lv-rl-card">
        <h3>Conflicts</h3>
        {conflicts.length === 0 ? (
          <p className="lv-rl-card-hint">No perception / research-cycle conflicts recorded.</p>
        ) : (
          <ul className="lv-rl-fam-list">
            {conflicts.map((c, i) => (
              <li key={i}>
                {c.stage != null ? `[${String(c.stage)}] ` : ""}
                {String(c.error || c.detail || c.reason || JSON.stringify(c))}
              </li>
            ))}
          </ul>
        )}
      </article>
    </div>
  );
}
