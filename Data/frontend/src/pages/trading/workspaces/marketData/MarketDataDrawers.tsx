/**
 * Market Data (WAVE 5/6) — ADVANCED drawers with working backend actions:
 * import/register dataset, manage feeds (providers), certify dataset,
 * and replay (historical market-sim run) with sampling controls.
 */
import { useEffect, useState, type ReactNode } from "react";
import { UNMEASURED } from "../commandHub/hubFormat";
import { certificationPitOf, certificationStateOf, type LibraryRow, type MarketDataWorkspaceData } from "./useMarketDataWorkspace";

function Drawer({
  title,
  onClose,
  children,
  wide = false,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  return (
    <div className="lv-md-drawer-backdrop" role="presentation" onClick={onClose}>
      <div
        className={`lv-md-drawer${wide ? " lv-md-drawer--wide" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <header>
          <h3>{title}</h3>
          <button type="button" className="lv-md-btn lv-md-btn--ghost" onClick={onClose} aria-label="Sluiten">
            ✕
          </button>
        </header>
        <div className="lv-md-drawer__body">{children}</div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------- import drawer */

export function ImportDrawer({ data, onClose }: { data: MarketDataWorkspaceData; onClose: () => void }) {
  const [path, setPath] = useState("BTCUSDT_1h.csv");
  const [symbol, setSymbol] = useState("");
  const [timeframe, setTimeframe] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function submitScan() {
    setError(null);
    try {
      await data.scan();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Scan mislukt");
    }
  }

  async function submitRegister() {
    setError(null);
    try {
      await data.register({ path, symbol: symbol || undefined, timeframe: timeframe || undefined });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Registratie mislukt");
    }
  }

  return (
    <Drawer title="Dataset importeren" onClose={onClose}>
      {error ? <p className="lv-md-drawer__error">{error}</p> : null}
      <p className="lv-md-muted">
        Plaats CSV-bestanden onder de markets root. Vereiste kolommen: timestamp, open, high, low, close, volume.
        Grote bestanden blijven op disk; de database bewaart alleen metadata + content hash.
      </p>
      <div className="lv-md-form">
        <label>
          Relatief pad onder markets root
          <input value={path} onChange={(e) => setPath(e.target.value)} placeholder="BTCUSDT_1h.csv" />
        </label>
        <div className="lv-md-form__row">
          <label>
            Symbool (optioneel)
            <input value={symbol} onChange={(e) => setSymbol(e.target.value)} placeholder="auto-detect" />
          </label>
          <label>
            Timeframe (optioneel)
            <input value={timeframe} onChange={(e) => setTimeframe(e.target.value)} placeholder="auto-detect" />
          </label>
        </div>
      </div>
      <footer className="lv-md-drawer__footer">
        <button type="button" className="lv-md-btn" onClick={() => void submitScan()} disabled={data.busy}>
          {data.busy ? "…" : "Scan folder"}
        </button>
        <button type="button" className="lv-md-btn lv-md-btn--primary" onClick={() => void submitRegister()} disabled={data.busy || !path.trim()}>
          {data.busy ? "…" : "Valideer & registreer"}
        </button>
      </footer>
      <div>
        <h4 style={{ margin: "0.4rem 0", fontSize: "0.8rem", color: "#94a3b8" }}>Recente sessie-activiteit</h4>
        <ul className="lv-md-activity__list">
          {data.activity.slice(0, 6).map((a) => (
            <li key={a.id}>
              <div>
                <strong>{a.label}</strong>
                <span className={`lv-md-pill ${a.status === "ok" ? "is-good" : "is-bad"}`}>{a.status}</span>
              </div>
              <span className="lv-md-activity__detail">{a.detail}</span>
            </li>
          ))}
        </ul>
      </div>
    </Drawer>
  );
}

/* ------------------------------------------------------------- feeds drawer */

export function FeedsDrawer({ data, onClose }: { data: MarketDataWorkspaceData; onClose: () => void }) {
  const [providerId, setProviderId] = useState("");
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [timeframe, setTimeframe] = useState("1h");
  const [limit, setLimit] = useState(500);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!providerId && data.providers.length) setProviderId(data.providers[0].providerId);
  }, [data.providers, providerId]);

  async function submitImport() {
    if (!providerId) return;
    setBusy(true);
    setError(null);
    try {
      await data.importProvider({ providerId, symbol, timeframe, limit });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Provider import mislukt");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Drawer title="Feeds beheren" onClose={onClose} wide>
      {error ? <p className="lv-md-drawer__error">{error}</p> : null}
      <div className="lv-md-table-scroll">
        <table className="lv-md-table">
          <thead>
            <tr>
              <th>Provider</th>
              <th>Data kinds</th>
              <th>Reachable</th>
              <th>Auth</th>
              <th>Latency</th>
              <th>Licentie</th>
              <th>Detail</th>
            </tr>
          </thead>
          <tbody>
            {data.providers.map((p) => (
              <tr key={p.providerId}>
                <td className="sym">{p.providerId}</td>
                <td>{p.dataKinds.join(", ") || "—"}</td>
                <td>
                  <span className={`lv-md-pill ${p.reachable === true ? "is-good" : p.reachable === false ? "is-bad" : "is-muted"}`}>
                    {p.reachable === true ? "Yes" : p.reachable === false ? "No" : UNMEASURED}
                  </span>
                </td>
                <td>{p.authenticated == null ? UNMEASURED : p.authenticated ? "Yes" : "No"}</td>
                <td>{p.latencyMs != null ? `${p.latencyMs.toFixed(0)} ms` : UNMEASURED}</td>
                <td>{p.licenseState}</td>
                <td className="lv-md-muted">{p.detail}</td>
              </tr>
            ))}
            {!data.providers.length ? (
              <tr>
                <td colSpan={7} className="lv-md-muted">
                  {data.providersLoading ? "Laden…" : "Geen providers geregistreerd."}
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
      <button type="button" className="lv-md-btn" onClick={() => void data.refreshProviders()} disabled={data.providersLoading}>
        {data.providersLoading ? "…" : "Providers verversen (live ping)"}
      </button>

      <h4 style={{ margin: "0.2rem 0", fontSize: "0.82rem", color: "#f1f5f9" }}>Import historische data via provider</h4>
      <div className="lv-md-form__row">
        <label>
          Provider
          <select value={providerId} onChange={(e) => setProviderId(e.target.value)}>
            {data.providers.map((p) => (
              <option key={p.providerId} value={p.providerId}>
                {p.providerId}
              </option>
            ))}
          </select>
        </label>
        <label>
          Symbool
          <input value={symbol} onChange={(e) => setSymbol(e.target.value)} />
        </label>
        <label>
          Timeframe
          <input value={timeframe} onChange={(e) => setTimeframe(e.target.value)} />
        </label>
        <label>
          Limit
          <input type="number" value={limit} onChange={(e) => setLimit(Number(e.target.value) || 500)} />
        </label>
      </div>
      <footer className="lv-md-drawer__footer">
        <button type="button" className="lv-md-btn lv-md-btn--primary" disabled={busy || !providerId} onClick={() => void submitImport()}>
          {busy ? "Importeren…" : "Import starten"}
        </button>
      </footer>
    </Drawer>
  );
}

/* ------------------------------------------------------------ certify drawer */

export function CertifyDrawer({
  data,
  initialRow,
  onClose,
}: {
  data: MarketDataWorkspaceData;
  initialRow: LibraryRow | null;
  onClose: () => void;
}) {
  const [selectedId, setSelectedId] = useState<string | null>(initialRow?.id ?? data.library[0]?.id ?? null);
  const [error, setError] = useState<string | null>(null);

  const row = data.library.find((r) => r.id === selectedId) ?? null;
  const cert = selectedId ? data.certifications[selectedId] : undefined;

  useEffect(() => {
    if (selectedId && !(selectedId in data.certifications)) {
      void data.fetchCertification(selectedId, row?.hash.slice(0, 16));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId]);

  async function submitEvaluate() {
    if (!row) return;
    setError(null);
    try {
      await data.evaluateCertification(row.raw);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Certificatie mislukt");
    }
  }

  return (
    <Drawer title="Data certificeren" onClose={onClose} wide>
      {error ? <p className="lv-md-drawer__error">{error}</p> : null}
      <div className="lv-md-form__row">
        <label>
          Dataset
          <select value={selectedId ?? ""} onChange={(e) => setSelectedId(e.target.value || null)}>
            <option value="">—</option>
            {data.library.map((r) => (
              <option key={r.id} value={r.id}>
                {r.symbol} · {r.timeframe} · {r.status}
              </option>
            ))}
          </select>
        </label>
      </div>

      {row ? (
        <>
          <p className="lv-md-muted">
            source_id <code>{row.id}</code> · content_hash <code>{row.hash}</code> · bars {row.barCount} · quality{" "}
            <strong>{row.quality}</strong>
          </p>

          <h4 style={{ margin: "0.2rem 0", fontSize: "0.82rem", color: "#f1f5f9" }}>Huidige certificatie</h4>
          {cert === undefined ? (
            <p className="lv-md-muted">Laden…</p>
          ) : cert === null ? (
            <p className="lv-md-muted">Nog geen certificatie voor deze dataset (server retourneerde 404 of geen record).</p>
          ) : (
            <div className="lv-md-form__row">
              <span>
                Certification state: <strong>{certificationStateOf(cert)}</strong>
              </span>
              <span>
                PIT: <strong>{certificationPitOf(cert)}</strong>
              </span>
            </div>
          )}
          {cert ? <pre>{JSON.stringify(cert, null, 2)}</pre> : null}

          <h4 style={{ margin: "0.2rem 0", fontSize: "0.82rem", color: "#f1f5f9" }}>Server-side evidence-based evaluatie</h4>
          <p className="lv-md-muted">
            Evidence wordt opgebouwd uit echte source-metadata (content hash, gap/duplicate counts, OHLC invariant
            checks). De server bepaalt certification/PIT-state — <code>certified=true</code> alleen wordt afgewezen
            (CALLER_BOOLEAN_NOT_CERTIFICATION).
          </p>
          <footer className="lv-md-drawer__footer">
            <button type="button" className="lv-md-btn lv-md-btn--primary" disabled={data.certBusy === row.id} onClick={() => void submitEvaluate()}>
              {data.certBusy === row.id ? "Evalueren…" : "Evalueer certificatie"}
            </button>
          </footer>
        </>
      ) : (
        <p className="lv-md-muted">Selecteer een dataset om te certificeren.</p>
      )}
    </Drawer>
  );
}

/* ------------------------------------------------------------- replay drawer */

export function ReplayDrawer({
  data,
  initialRow,
  onClose,
}: {
  data: MarketDataWorkspaceData;
  initialRow: LibraryRow | null;
  onClose: () => void;
}) {
  const readySources = data.sources.filter((s) => s.status === "READY");
  const [sourceId, setSourceId] = useState(initialRow?.raw.source_id ?? readySources[0]?.source_id ?? "");
  const [seed, setSeed] = useState(42);
  const [speed, setSpeed] = useState(1);
  const [initialCash, setInitialCash] = useState(100_000);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const act = async (name: string, fn: () => Promise<unknown>) => {
    setBusy(name);
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError(err instanceof Error ? err.message : `${name} mislukt`);
    } finally {
      setBusy(null);
    }
  };

  return (
    <Drawer title="Replay & Sampling" onClose={onClose} wide>
      {error ? <p className="lv-md-drawer__error">{error}</p> : null}
      <div className="lv-md-form__row">
        <label>
          Dataset (READY)
          <select value={sourceId} onChange={(e) => setSourceId(e.target.value)}>
            <option value="">—</option>
            {readySources.map((s) => (
              <option key={s.source_id} value={s.source_id}>
                {s.symbol} · {s.timeframe} · {s.bar_count} bars
              </option>
            ))}
          </select>
        </label>
        <label>
          Seed
          <input type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value) || 42)} />
        </label>
        <label>
          Speed
          <input type="number" min={0.1} step={0.1} value={speed} onChange={(e) => setSpeed(Number(e.target.value) || 1)} />
        </label>
        <label>
          Initial cash
          <input type="number" value={initialCash} onChange={(e) => setInitialCash(Number(e.target.value) || 100000)} />
        </label>
      </div>
      <div className="lv-md-replay__controls">
        <button
          type="button"
          className="lv-md-btn lv-md-btn--primary"
          disabled={!!busy || !sourceId}
          onClick={() =>
            void act("create", async () => {
              const run = await data.createReplayRun({ sourceId, seed, speed, initialCash });
              await data.startReplayRun(run.run_id);
            })
          }
        >
          {busy === "create" ? "…" : "Replay starten"}
        </button>
        <button
          type="button"
          className="lv-md-btn"
          disabled={!!busy || !data.selectedSimRunId}
          onClick={() => void act("pause", () => data.pauseReplayRun(data.selectedSimRunId as string))}
        >
          Pause
        </button>
        <button
          type="button"
          className="lv-md-btn"
          disabled={!!busy || !data.selectedSimRunId}
          onClick={() => void act("step", () => data.stepReplayRun(data.selectedSimRunId as string))}
        >
          Step
        </button>
        <button
          type="button"
          className="lv-md-btn lv-md-btn--danger"
          disabled={!!busy || !data.selectedSimRunId}
          onClick={() => void act("stop", () => data.stopReplayRun(data.selectedSimRunId as string))}
        >
          Stop
        </button>
      </div>

      <div className="lv-md-table-scroll">
        <table className="lv-md-table">
          <thead>
            <tr>
              <th />
              <th>Run</th>
              <th>Status</th>
              <th>Equity</th>
              <th>Bar</th>
            </tr>
          </thead>
          <tbody>
            {data.simRuns.map((r) => (
              <tr key={r.run_id} onClick={() => data.setSelectedSimRunId(r.run_id)}>
                <td>
                  <input type="radio" checked={data.selectedSimRunId === r.run_id} onChange={() => data.setSelectedSimRunId(r.run_id)} />
                </td>
                <td>
                  {r.run_id.slice(0, 10)} · {r.symbol}
                </td>
                <td>{r.status}</td>
                <td>{r.equity}</td>
                <td>
                  {r.bar_index}/{r.bar_count}
                </td>
              </tr>
            ))}
            {!data.simRuns.length ? (
              <tr>
                <td colSpan={5} className="lv-md-muted">
                  Nog geen replay runs.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
      {data.simLive ? (
        <p className="lv-md-muted">
          Live: {data.simLive.fills.length} fills · {data.simLive.messages.length} messages · causality violations{" "}
          {data.simLive.run.causality_violations}
        </p>
      ) : null}
    </Drawer>
  );
}
