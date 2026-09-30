/**
 * Strategy Lab (WAVE 5) — PRIMARY pixel layout.
 * Hero + CTAs → KPI strip → validation ladder → discovery table + deep dive →
 * experiment pipeline / robustness teaser / research sessions / paper validation.
 */
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { UNMEASURED } from "../commandHub/hubFormat";
import type { DiscoveryRow, StrategyLabData } from "./useStrategyLabData";

const STATUS_TONE: Record<string, string> = {
  PAPER_RUNNING: "is-good",
  RUNNING: "is-good",
  ACTIVE: "is-good",
  CANDIDATE: "is-info",
  BACKTESTING: "is-info",
  LEARNING: "is-warn",
  DISCOVERING: "is-warn",
  CREATED: "is-muted",
  PAUSED: "is-warn",
  CANCELLED: "is-bad",
  REJECTED: "is-bad",
  FAILED: "is-bad",
};

function statusTone(status: string): string {
  return STATUS_TONE[status.toUpperCase()] ?? "is-muted";
}

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    PAPER_RUNNING: "Paper Running",
    RUNNING: "Running",
    CANDIDATE: "Candidate",
    BACKTESTING: "Backtesting",
    LEARNING: "Learning",
    DISCOVERING: "Discovering",
    CREATED: "Created",
    PAUSED: "Paused",
    QUALIFIED_STRATEGY_FOUND: "Qualified",
    NO_STRATEGY_QUALIFIED: "No match",
    IN_PROGRESS: "In progress",
  };
  return map[status.toUpperCase()] ?? status;
}

export type DeepDiveTab = "hypothese" | "waarom" | "zwaktes" | "confidence" | "tags";

function DeepDivePanel({
  row,
  strategyDescription,
  strategyTags,
  onOpenAdvanced,
}: {
  row: DiscoveryRow | null;
  strategyDescription: string | null;
  strategyTags: string[];
  onOpenAdvanced: () => void;
}) {
  const [tab, setTab] = useState<DeepDiveTab>("hypothese");
  const TABS: { id: DeepDiveTab; label: string }[] = [
    { id: "hypothese", label: "Hypothese" },
    { id: "waarom", label: "Waarom het werkt" },
    { id: "zwaktes", label: "Zwaktes" },
    { id: "confidence", label: "Confidence" },
    { id: "tags", label: "Tags" },
  ];

  if (!row) {
    return (
      <section className="lv-sl-panel lv-sl-deepdive" aria-label="Strategy Deep Dive">
        <header>
          <h3>Strategy Deep Dive</h3>
        </header>
        <p className="lv-sl-muted">Selecteer een strategie in de tabel om de deep dive te openen.</p>
      </section>
    );
  }

  const hypothesis = String(row.raw.hypothesis ?? "").trim();

  return (
    <section className="lv-sl-panel lv-sl-deepdive" aria-label="Strategy Deep Dive">
      <header>
        <div>
          <h3>{row.name}</h3>
          <span className="lv-sl-deepdive__sub">{row.family} · {row.market}</span>
        </div>
        <span className={`lv-sl-pill ${statusTone(row.status)}`}>{statusLabel(row.status)}</span>
      </header>
      <div className="lv-sl-tabs" role="tablist">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            className={`lv-sl-tab${tab === t.id ? " is-active" : ""}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div className="lv-sl-deepdive__body">
        {tab === "hypothese" ? (
          <p>{hypothesis || strategyDescription || "Geen hypothese geregistreerd voor deze trial."}</p>
        ) : null}
        {tab === "waarom" ? (
          <p>
            Sharpe <strong>{row.sharpe}</strong> · Win rate <strong>{row.winRate}</strong> · Paper PnL{" "}
            <strong>{row.paperPnl}</strong>. Backend-gemeten resultaten — geen LLM-storytelling.
          </p>
        ) : null}
        {tab === "zwaktes" ? (
          <p>
            Max drawdown <strong>{row.maxDrawdown}</strong>. {row.status === "REJECTED" ? String(row.raw.rejection_reason ?? "Geen reden geregistreerd.") : "Geen geregistreerde zwaktes buiten de gemeten metrics."}
          </p>
        ) : null}
        {tab === "confidence" ? (
          <p>
            Confidence <strong>{row.confidence}</strong>. {row.confidence === UNMEASURED ? "Backend rapporteert geen confidence-score voor deze trial." : null}
          </p>
        ) : null}
        {tab === "tags" ? (
          <div className="lv-sl-tagrow">
            {strategyTags.length ? (
              strategyTags.map((t) => <em key={t}>{t}</em>)
            ) : (
              <span className="lv-sl-muted">Geen tags</span>
            )}
          </div>
        ) : null}
      </div>
      <footer>
        <button type="button" className="lv-sl-btn lv-sl-btn--ghost" onClick={onOpenAdvanced}>
          Volledige analyse · Advanced ▸
        </button>
      </footer>
    </section>
  );
}

export function StrategyLabView({
  data,
  selectedRow,
  onSelectRow,
  compareIds,
  onToggleCompare,
  onOpenCreateRun,
  onOpenCompare,
  onOpenAdvanced,
}: {
  data: StrategyLabData;
  selectedRow: DiscoveryRow | null;
  onSelectRow: (row: DiscoveryRow) => void;
  compareIds: string[];
  onToggleCompare: (id: string) => void;
  onOpenCreateRun: () => void;
  onOpenCompare: () => void;
  onOpenAdvanced: () => void;
}) {
  const [search, setSearch] = useState("");
  const [familyFilter, setFamilyFilter] = useState("all");
  const [marketFilter, setMarketFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");

  const families = useMemo(
    () => Array.from(new Set(data.discovery.map((r) => r.family).filter((f) => f && f !== "—"))).sort(),
    [data.discovery],
  );
  const markets = useMemo(
    () => Array.from(new Set(data.discovery.map((r) => r.market).filter((m) => m && m !== "—"))).sort(),
    [data.discovery],
  );
  const statuses = useMemo(
    () => Array.from(new Set(data.discovery.map((r) => r.status))).sort(),
    [data.discovery],
  );

  const filteredRows = useMemo(() => {
    const q = search.trim().toLowerCase();
    return data.discovery.filter((r) => {
      if (familyFilter !== "all" && r.family !== familyFilter) return false;
      if (marketFilter !== "all" && r.market !== marketFilter) return false;
      if (statusFilter !== "all" && r.status !== statusFilter) return false;
      if (q && !r.name.toLowerCase().includes(q) && !r.family.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [data.discovery, familyFilter, marketFilter, statusFilter, search]);

  const selectedStrategy = selectedRow?.strategyId ? data.strategyById.get(selectedRow.strategyId) ?? null : null;

  return (
    <div className="lv-sl-view">
      <section className="lv-sl-hero" aria-label="Strategy Discovery & Validation Lab">
        <div className="lv-sl-hero__copy">
          <p className="lv-sl-hero__kicker">Strategy Discovery &amp; Validation Lab</p>
          <p className="lv-sl-hero__sub">
            Autonoom ontdekken, leren en valideren van trading strategieën. Van idee of hypothese tot offline
            testing en paper validatie.
          </p>
          <div className="lv-sl-hero__cta">
            <button type="button" className="lv-sl-btn lv-sl-btn--primary" onClick={onOpenCreateRun}>
              + Nieuwe zoekopdracht
            </button>
            <Link className="lv-sl-btn" to="/trading/command-hub?surface=research-command">
              Research sessie
            </Link>
            <Link className="lv-sl-btn" to="/trading/trading-desk?surface=paper">
              Paper validatie
            </Link>
            <button type="button" className="lv-sl-btn" onClick={onOpenCompare} disabled={compareIds.length < 2}>
              Vergelijken{compareIds.length ? ` (${compareIds.length})` : ""}
            </button>
          </div>
        </div>
        <blockquote className="lv-sl-hero__quote">
          “Data wordt inzicht. AI test hypothesen. Validatie creëert vertrouwen. Zo ontstaan winnende
          strategieën.” — LEVIATHAN
        </blockquote>
      </section>

      <section className="lv-sl-kpis" aria-busy={data.loading}>
        {data.kpis.map((k) => (
          <article key={k.id} className="lv-sl-kpi">
            <h3>{k.label}</h3>
            <p>{data.loading ? "…" : k.value}</p>
            <span>{k.note}</span>
          </article>
        ))}
      </section>

      <section className="lv-sl-ladder" aria-label="Validation ladder">
        {data.ladder.map((step, i) => (
          <div key={step.id} className="lv-sl-ladder__step">
            <strong>{step.label}</strong>
            <span>{data.loading ? "…" : step.value}</span>
            <small>{step.note}</small>
            {i < data.ladder.length - 1 ? (
              <span className="lv-sl-ladder__arrow" aria-hidden="true">
                →
              </span>
            ) : null}
          </div>
        ))}
      </section>

      <section className="lv-sl-main-grid">
        <article className="lv-sl-panel lv-sl-discovery">
          <header>
            <h3>Strategy Discovery, Learning &amp; Validation</h3>
            <div className="lv-sl-discovery__filters">
              <input
                type="search"
                placeholder="Zoek strategieën..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
              <select value={familyFilter} onChange={(e) => setFamilyFilter(e.target.value)}>
                <option value="all">Alle families</option>
                {families.map((f) => (
                  <option key={f} value={f}>
                    {f}
                  </option>
                ))}
              </select>
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
                    {statusLabel(s)}
                  </option>
                ))}
              </select>
            </div>
          </header>
          <div className="lv-sl-table-scroll">
            <table className="lv-sl-table">
              <thead>
                <tr>
                  <th aria-label="Vergelijken" />
                  <th>#</th>
                  <th>Strategie Naam</th>
                  <th>Familie</th>
                  <th>Markt</th>
                  <th>Mode</th>
                  <th>Sharpe</th>
                  <th>Win Rate</th>
                  <th>Max DD</th>
                  <th>Paper PnL</th>
                  <th>Confidence</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {filteredRows.map((row, i) => (
                  <tr
                    key={row.id || i}
                    className={selectedRow?.id === row.id ? "is-selected" : ""}
                    onClick={() => onSelectRow(row)}
                  >
                    <td onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        checked={compareIds.includes(row.id)}
                        onChange={() => onToggleCompare(row.id)}
                        aria-label={`Vergelijk ${row.name}`}
                      />
                    </td>
                    <td>{i + 1}</td>
                    <td>{row.name}</td>
                    <td>{row.family}</td>
                    <td>{row.market}</td>
                    <td>{row.mode}</td>
                    <td>{row.sharpe}</td>
                    <td>{row.winRate}</td>
                    <td>{row.maxDrawdown}</td>
                    <td>{row.paperPnl}</td>
                    <td>{row.confidence}</td>
                    <td>
                      <span className={`lv-sl-pill ${statusTone(row.status)}`}>{statusLabel(row.status)}</span>
                    </td>
                  </tr>
                ))}
                {!filteredRows.length ? (
                  <tr>
                    <td colSpan={12} className="lv-sl-muted">
                      {data.loading ? "Laden…" : "Geen trials gevonden — start een nieuwe zoekopdracht."}
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </article>

        <DeepDivePanel
          row={selectedRow}
          strategyDescription={selectedStrategy?.description ?? null}
          strategyTags={selectedStrategy?.tags ?? []}
          onOpenAdvanced={onOpenAdvanced}
        />
      </section>

      <section className="lv-sl-bottom-grid">
        <article className="lv-sl-panel lv-sl-pipeline">
          <header>
            <h3>Experiment Pipeline</h3>
          </header>
          <ul className="lv-sl-pipeline__list">
            {data.pipeline.map((stage) => (
              <li key={stage.id}>
                <span className="lv-sl-pipeline__label">{stage.label}</span>
                <span className="lv-sl-pipeline__count">
                  {stage.active} actief / {stage.total}
                </span>
                <span className="lv-sl-pipeline__bar">
                  <i style={{ width: `${stage.total ? Math.round((stage.active / stage.total) * 100) : 0}%` }} />
                </span>
              </li>
            ))}
            {!data.pipeline.length ? <li className="lv-sl-muted">Nog geen research sessies.</li> : null}
          </ul>
        </article>

        <article className="lv-sl-panel lv-sl-robustness">
          <header>
            <h3>Robustness Matrix</h3>
            <span className="lv-sl-tag-soft">Teaser</span>
          </header>
          <p className="lv-sl-muted">
            Volledige regime × marktomstandigheid robustness-scan is een Advanced-capability — open een
            geselecteerde lab run voor gemeten generatie- en familie-verdeling.
          </p>
          <div className="lv-sl-robustness__mini">
            <span>Families ontdekt</span>
            <strong>{data.families.length || UNMEASURED}</strong>
          </div>
        </article>

        <article className="lv-sl-panel lv-sl-sessions">
          <header>
            <h3>Research Sessies</h3>
          </header>
          <ul className="lv-sl-sessions__list">
            {data.researchSessions.slice(0, 8).map((s) => (
              <li key={s.id}>
                <div>
                  <strong>{s.name}</strong>
                  <span>{s.candidateCount} kandidaten · {s.createdAt.slice(0, 10)}</span>
                </div>
                <span className={`lv-sl-pill ${statusTone(s.status)}`}>{statusLabel(s.status)}</span>
              </li>
            ))}
            {!data.researchSessions.length ? <li className="lv-sl-muted">Nog geen research sessies.</li> : null}
          </ul>
        </article>

        <article className="lv-sl-panel lv-sl-papersnap">
          <header>
            <h3>Paper Validatie Snapshot</h3>
            <Link to="/trading/trading-desk?surface=paper">Details</Link>
          </header>
          <div className="lv-sl-papersnap__row">
            <div>
              <span>Beste equity</span>
              <strong>{data.paperValidation.bestEquity}</strong>
            </div>
            <div>
              <span>Beste return</span>
              <strong className={data.paperValidation.bestReturnPct.startsWith("-") ? "is-bad" : "is-good"}>
                {data.paperValidation.bestReturnPct}
              </strong>
            </div>
            <div>
              <span>Shadow / Autonomous</span>
              <strong>
                {data.paperValidation.shadow} / {data.paperValidation.autonomous}
              </strong>
            </div>
          </div>
          <ul className="lv-sl-papersnap__list">
            {data.paperValidation.recent.map((d) => (
              <li key={d.id}>
                <span>{d.label}</span>
                <em>{d.mode}</em>
                <span className={`lv-sl-pill ${statusTone(d.status)}`}>{statusLabel(d.status)}</span>
              </li>
            ))}
            {!data.paperValidation.recent.length ? <li className="lv-sl-muted">Nog geen paper deployments.</li> : null}
          </ul>
        </article>
      </section>
    </div>
  );
}
