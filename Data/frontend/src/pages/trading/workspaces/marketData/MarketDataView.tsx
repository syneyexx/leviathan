/**
 * Market Data (WAVE 5/6) — PRIMARY pixel layout.
 * Hero + CTAs → KPI strip → Offline Dataset Bibliotheek + Live Feed Health →
 * Marktdekking / Regime Monitor / Data Quality & Gaps → Ingestie & Sync
 * (activity log) / Bron Provenance & Certificatie / Replay & Sampling.
 */
import { useMemo, useState } from "react";
import { UNMEASURED } from "../commandHub/hubFormat";
import {
  certificationStateOf,
  shortHash,
  type LibraryRow,
  type MarketDataWorkspaceData,
} from "./useMarketDataWorkspace";

function statusTone(status: string): string {
  const map: Record<string, string> = {
    READY: "is-good",
    INVALID: "is-bad",
    PENDING: "is-warn",
    PASS: "is-good",
    WARN: "is-warn",
    FAIL: "is-bad",
    UNMEASURED: "is-muted",
    RUNNING: "is-good",
    PAUSED: "is-warn",
    STOPPED: "is-muted",
  };
  return map[status.toUpperCase()] ?? "is-muted";
}

function qualityToneClass(status: "good" | "warn" | "bad" | "unmeasured"): string {
  return { good: "is-good", warn: "is-warn", bad: "is-bad", unmeasured: "is-muted" }[status];
}

function LibraryPanel({
  data,
  onSelectRow,
  onOpenImport,
  onCertify,
}: {
  data: MarketDataWorkspaceData;
  onSelectRow: (row: LibraryRow) => void;
  onOpenImport: () => void;
  onCertify: (row: LibraryRow) => void;
}) {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [marketFilter, setMarketFilter] = useState("all");

  const markets = useMemo(() => Array.from(new Set(data.library.map((r) => r.symbol))).sort(), [data.library]);
  const statuses = useMemo(() => Array.from(new Set(data.library.map((r) => r.status))).sort(), [data.library]);

  const filtered = data.library.filter((r) => {
    if (statusFilter !== "all" && r.status !== statusFilter) return false;
    if (marketFilter !== "all" && r.symbol !== marketFilter) return false;
    const q = search.trim().toLowerCase();
    if (q && !r.symbol.toLowerCase().includes(q) && !r.path.toLowerCase().includes(q)) return false;
    return true;
  });

  return (
    <article className="lv-md-panel lv-md-library" aria-label="Offline Dataset Bibliotheek">
      <header>
        <h3>Offline Dataset Bibliotheek</h3>
        <div className="lv-md-library__filters">
          <input type="search" placeholder="Zoek symbool of pad..." value={search} onChange={(e) => setSearch(e.target.value)} />
          <select value={marketFilter} onChange={(e) => setMarketFilter(e.target.value)}>
            <option value="all">Alle markten</option>
            {markets.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="all">Alle statussen</option>
            {statuses.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <button type="button" className="lv-md-btn lv-md-btn--primary" onClick={() => void data.scan()} disabled={data.busy}>
            {data.busy ? "…" : "Scan folder"}
          </button>
          <button type="button" className="lv-md-btn" onClick={onOpenImport}>
            + Dataset importeren
          </button>
        </div>
      </header>
      <div className="lv-md-table-scroll">
        <table className="lv-md-table">
          <thead>
            <tr>
              <th>Dataset</th>
              <th>TF</th>
              <th>Status</th>
              <th>Kwaliteit</th>
              <th>Bars</th>
              <th>Periode</th>
              <th>Grootte</th>
              <th>Hash</th>
              <th>Certificate</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {filtered.map((row) => {
              const cert = data.certifications[row.id];
              const certKnown = row.id in data.certifications;
              return (
                <tr key={row.id} onClick={() => onSelectRow(row)}>
                  <td className="sym">{row.symbol}</td>
                  <td>{row.timeframe}</td>
                  <td>
                    <span className={`lv-md-pill ${statusTone(row.status)}`}>{row.status}</span>
                  </td>
                  <td>
                    <span className={`lv-md-pill ${statusTone(row.quality)}`}>{row.quality}</span>
                  </td>
                  <td>{row.barCount.toLocaleString("nl-NL")}</td>
                  <td>{row.range}</td>
                  <td>{row.size}</td>
                  <td title={row.hash}>{shortHash(row.hash)}</td>
                  <td>
                    {certKnown ? (
                      <span className={`lv-md-pill ${statusTone(certificationStateOf(cert))}`}>
                        {certificationStateOf(cert)}
                      </span>
                    ) : (
                      <button
                        type="button"
                        className="lv-md-btn lv-md-btn--ghost"
                        onClick={(e) => {
                          e.stopPropagation();
                          void data.fetchCertification(row.id, row.hash.slice(0, 16));
                        }}
                      >
                        Check
                      </button>
                    )}
                  </td>
                  <td>
                    <button
                      type="button"
                      className="lv-md-btn lv-md-btn--ghost"
                      onClick={(e) => {
                        e.stopPropagation();
                        onCertify(row);
                      }}
                    >
                      Certificeren
                    </button>
                  </td>
                </tr>
              );
            })}
            {!filtered.length ? (
              <tr>
                <td colSpan={10} className="lv-md-muted">
                  {data.loading ? "Laden…" : "Geen datasets gevonden — scan of importeer een bron."}
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </article>
  );
}

function FeedHealthPanel({ data, onOpenFeeds }: { data: MarketDataWorkspaceData; onOpenFeeds: () => void }) {
  return (
    <article className="lv-md-panel lv-md-feeds" aria-label="Live Feed Health">
      <header>
        <h3>Live Feed Health</h3>
        <button type="button" className="lv-md-btn" onClick={onOpenFeeds}>
          Feeds beheren
        </button>
      </header>
      <div className="lv-md-table-scroll">
        <table className="lv-md-table">
          <thead>
            <tr>
              <th>Bron</th>
              <th>Type</th>
              <th>Latency</th>
              <th>Status</th>
              <th>Licentie</th>
            </tr>
          </thead>
          <tbody>
            {data.providers.map((p) => (
              <tr key={p.providerId}>
                <td className="sym">{p.providerId}</td>
                <td>{p.dataKinds.join(", ") || "—"}</td>
                <td>{p.latencyMs != null ? `${p.latencyMs.toFixed(0)} ms` : UNMEASURED}</td>
                <td>
                  <span
                    className={`lv-md-pill ${p.reachable === true ? "is-good" : p.reachable === false ? "is-bad" : "is-muted"}`}
                  >
                    {p.reachable === true ? "Online" : p.reachable === false ? "Offline" : UNMEASURED}
                  </span>
                </td>
                <td title={p.licenseNote}>{p.licenseState}</td>
              </tr>
            ))}
            {!data.providers.length ? (
              <tr>
                <td colSpan={5} className="lv-md-muted">
                  {data.providersLoading ? "Providers laden…" : "Geen providers geregistreerd."}
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </article>
  );
}

function CoveragePanel({ data }: { data: MarketDataWorkspaceData }) {
  return (
    <article className="lv-md-panel lv-md-coverage" aria-label="Marktdekking">
      <header>
        <h3>Marktdekking (Symbol Coverage)</h3>
        <span className="lv-md-tag-soft">{data.coverage.length} symbolen</span>
      </header>
      <div className="lv-md-table-scroll">
        <table className="lv-md-table">
          <thead>
            <tr>
              <th>Symbool</th>
              <th>Timeframes</th>
              <th>Bronnen</th>
              <th>Beschikbaarheid</th>
            </tr>
          </thead>
          <tbody>
            {data.coverage.slice(0, 20).map((c) => (
              <tr key={c.symbol}>
                <td className="sym">{c.symbol}</td>
                <td>{c.timeframes.join(", ") || "—"}</td>
                <td>
                  {c.readyCount}/{c.sourceCount}
                </td>
                <td>
                  <span className="lv-md-coverage__bar">
                    <i style={{ width: `${c.readyPct}%` }} />
                  </span>
                </td>
              </tr>
            ))}
            {!data.coverage.length ? (
              <tr>
                <td colSpan={4} className="lv-md-muted">
                  {data.loading ? "Laden…" : "Geen symbolen geïndexeerd."}
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </article>
  );
}

function RegimePanel({ data }: { data: MarketDataWorkspaceData }) {
  return (
    <article className="lv-md-panel lv-md-regime" aria-label="Regime Monitor">
      <header>
        <h3>Regime Monitor</h3>
        <span className="lv-md-tag-soft">{UNMEASURED}</span>
      </header>
      <div className="lv-md-regime__body">
        <p>
          Regime detector versie <strong>{data.regime.detectorVersion}</strong>. HMM regime status:{" "}
          <strong>{data.regime.hmmStatus}</strong>.
        </p>
        <p className="lv-md-muted">
          {data.regime.hmmReason ||
            "Geen live regime-classificatie is aan de Market Data workspace gekoppeld — UNMEASURED voorkomt het verzinnen van een Bullish/Bearish verdeling."}
        </p>
      </div>
    </article>
  );
}

function QualityGapsPanel({ data }: { data: MarketDataWorkspaceData }) {
  return (
    <article className="lv-md-panel lv-md-quality" aria-label="Data Quality & Gaps">
      <header>
        <h3>Data Quality &amp; Gaps</h3>
        <span className="lv-md-tag-soft">Laatste 30 dagen</span>
      </header>
      <ul className="lv-md-quality__list">
        {data.qualityGaps.map((m) => (
          <li key={m.id}>
            <span>{m.label}</span>
            <span className={`lv-md-pill ${qualityToneClass(m.status)}`}>{m.value}</span>
            <em>{m.note}</em>
          </li>
        ))}
      </ul>
    </article>
  );
}

function ActivityPanel({ data }: { data: MarketDataWorkspaceData }) {
  return (
    <article className="lv-md-panel lv-md-activity" aria-label="Ingestie & Sync Jobs">
      <header>
        <h3>Ingestie &amp; Sync Jobs</h3>
        <span className="lv-md-tag-soft">Sessie-activiteit</span>
      </header>
      <p className="lv-md-muted">
        Geen asynchrone job-queue API voor market data ingestie — scan/register/import zijn synchroon. Dit logt de
        echte acties van deze sessie (geen gefabriceerde queue-status).
      </p>
      <ul className="lv-md-activity__list">
        {data.activity.map((a) => (
          <li key={a.id}>
            <div>
              <strong>{a.label}</strong>
              <span className={`lv-md-pill ${a.status === "ok" ? "is-good" : a.status === "error" ? "is-bad" : "is-warn"}`}>
                {a.status.toUpperCase()}
              </span>
            </div>
            <span className="lv-md-activity__detail">
              {new Date(a.ts).toLocaleTimeString("nl-NL", { hour: "2-digit", minute: "2-digit", second: "2-digit" })} ·{" "}
              {a.detail}
            </span>
          </li>
        ))}
        {!data.activity.length ? <li className="lv-md-muted">Nog geen scan/import acties in deze sessie.</li> : null}
      </ul>
    </article>
  );
}

function ProvenancePanel({
  data,
  onOpenCertify,
}: {
  data: MarketDataWorkspaceData;
  onOpenCertify: () => void;
}) {
  const known = data.library.filter((r) => r.id in data.certifications);
  return (
    <article className="lv-md-panel lv-md-provenance" aria-label="Bron Provenance / Certificatie">
      <header>
        <h3>Bron Provenance / Certificatie</h3>
        <button type="button" className="lv-md-btn" onClick={onOpenCertify}>
          Certificaten beheren
        </button>
      </header>
      <ul className="lv-md-provenance__list">
        {known.slice(0, 8).map((r) => {
          const cert = data.certifications[r.id];
          return (
            <li key={r.id}>
              <span>
                {r.symbol} · {r.timeframe}
              </span>
              <span className={`lv-md-pill ${statusTone(certificationStateOf(cert))}`}>{certificationStateOf(cert)}</span>
              <span className="lv-md-muted">{cert ? "certificatie-record" : "niet gecertificeerd"}</span>
            </li>
          );
        })}
        {!known.length ? (
          <li className="lv-md-muted">Nog geen certificatie opgevraagd — open “Certificaten beheren”.</li>
        ) : null}
      </ul>
    </article>
  );
}

function ReplayPanel({ data, onOpenReplay }: { data: MarketDataWorkspaceData; onOpenReplay: () => void }) {
  const activeRun = data.simRuns.find((r) => r.run_id === data.selectedSimRunId) ?? data.simRuns[0] ?? null;
  return (
    <article className="lv-md-panel lv-md-replay" aria-label="Replay & Sampling">
      <header>
        <h3>Replay &amp; Sampling</h3>
        <button type="button" className="lv-md-btn lv-md-btn--primary" onClick={onOpenReplay}>
          Replay openen
        </button>
      </header>
      {activeRun ? (
        <>
          <div className="lv-md-replay__row">
            <span>Dataset</span>
            <strong>
              {activeRun.symbol} · {activeRun.timeframe}
            </strong>
          </div>
          <div className="lv-md-replay__row">
            <span>Periode</span>
            <strong>
              {activeRun.start_ts?.slice(0, 10) ?? "—"} → {activeRun.end_ts?.slice(0, 10) ?? "—"}
            </strong>
          </div>
          <div className="lv-md-replay__row">
            <span>Status</span>
            <strong>{activeRun.status}</strong>
          </div>
          <div className="lv-md-replay__row">
            <span>Bar</span>
            <strong>
              {activeRun.bar_index}/{activeRun.bar_count}
            </strong>
          </div>
        </>
      ) : (
        <p className="lv-md-muted">Nog geen replay-run — open “Replay openen” om een dataset te sampelen.</p>
      )}
      <div className="lv-md-replay__controls">
        {data.simRuns.slice(0, 5).map((r) => (
          <button
            key={r.run_id}
            type="button"
            className={`lv-md-btn${data.selectedSimRunId === r.run_id ? " lv-md-btn--primary" : ""}`}
            onClick={() => data.setSelectedSimRunId(r.run_id)}
          >
            {r.symbol} · {r.run_id.slice(0, 6)}
          </button>
        ))}
      </div>
    </article>
  );
}

export function MarketDataView({
  data,
  onOpenImport,
  onOpenFeeds,
  onOpenCertify,
  onOpenReplay,
  onSelectRow,
}: {
  data: MarketDataWorkspaceData;
  onOpenImport: () => void;
  onOpenFeeds: () => void;
  onOpenCertify: (row: LibraryRow | null) => void;
  onOpenReplay: (row: LibraryRow | null) => void;
  onSelectRow: (row: LibraryRow) => void;
}) {
  return (
    <div className="lv-md-view">
      <section className="lv-md-hero" aria-label="Market Data & Regime Intelligence">
        <svg className="lv-md-hero__art" viewBox="0 0 800 320" preserveAspectRatio="xMaxYMid slice" aria-hidden="true">
          <defs>
            <radialGradient id="lv-md-globe-glow" cx="72%" cy="50%" r="45%">
              <stop offset="0%" stopColor="#38bdf8" stopOpacity="0.35" />
              <stop offset="70%" stopColor="#38bdf8" stopOpacity="0.08" />
              <stop offset="100%" stopColor="#38bdf8" stopOpacity="0" />
            </radialGradient>
          </defs>
          <circle cx="600" cy="160" r="150" fill="url(#lv-md-globe-glow)" />
          <g fill="none" stroke="#67e8f9" strokeOpacity="0.35" strokeWidth="1">
            <circle cx="600" cy="160" r="95" />
            <ellipse cx="600" cy="160" rx="95" ry="32" />
            <ellipse cx="600" cy="160" rx="95" ry="60" />
            <line x1="600" y1="65" x2="600" y2="255" />
            <ellipse cx="600" cy="160" rx="32" ry="95" />
            <ellipse cx="600" cy="160" rx="60" ry="95" />
          </g>
          <g fill="#4ade80" opacity="0.8">
            <circle cx="560" cy="120" r="2.2" />
            <circle cx="640" cy="140" r="2.2" />
            <circle cx="615" cy="200" r="2.2" />
            <circle cx="570" cy="190" r="2.2" />
          </g>
        </svg>
        <div className="lv-md-hero__copy">
          <p className="lv-md-hero__kicker">Market Data &amp; Regime Intelligence</p>
          <p className="lv-md-hero__sub">
            Selecteer, valideer en monitor offline datasets en live marktbronnen voor trading research, backtesting
            en live trading.
          </p>
          <div className="lv-md-hero__cta">
            <button type="button" className="lv-md-btn lv-md-btn--primary" onClick={onOpenImport}>
              ⭱ Dataset importeren
            </button>
            <button type="button" className="lv-md-btn" onClick={onOpenFeeds}>
              Feeds beheren
            </button>
            <button type="button" className="lv-md-btn" onClick={() => onOpenCertify(null)}>
              Data certificeren
            </button>
            <button type="button" className="lv-md-btn" onClick={() => onOpenReplay(null)}>
              ▶ Replay openen
            </button>
          </div>
        </div>
        <blockquote className="lv-md-hero__quote">
          “Kwalitatieve data is de fundering van superieure trading.” — LEVIATHAN
        </blockquote>
      </section>

      <section className="lv-md-kpis" aria-busy={data.loading}>
        {data.kpis.map((k) => (
          <article key={k.id} className="lv-md-kpi">
            <h3>{k.label}</h3>
            <p>{data.loading ? "…" : k.value}</p>
            <span>{k.note}</span>
          </article>
        ))}
      </section>

      <section className="lv-md-row-2">
        <LibraryPanel
          data={data}
          onSelectRow={onSelectRow}
          onOpenImport={onOpenImport}
          onCertify={(row) => onOpenCertify(row)}
        />
        <FeedHealthPanel data={data} onOpenFeeds={onOpenFeeds} />
      </section>

      <section className="lv-md-row-3">
        <CoveragePanel data={data} />
        <RegimePanel data={data} />
        <QualityGapsPanel data={data} />
      </section>

      <section className="lv-md-row-3">
        <ActivityPanel data={data} />
        <ProvenancePanel data={data} onOpenCertify={() => onOpenCertify(null)} />
        <ReplayPanel data={data} onOpenReplay={() => onOpenReplay(null)} />
      </section>
    </div>
  );
}
