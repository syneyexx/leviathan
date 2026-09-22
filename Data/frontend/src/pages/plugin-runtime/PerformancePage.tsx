import { useMemo, useState, type ReactNode } from "react";
import { pluginRuntimeHeroes } from "../../assets/pluginRuntimeAssets";
import { AppShell } from "../../layouts/AppShell";
import { useAppToast } from "../../state/useAppToast";
import {
  PERF_ALERTS,
  PERF_CACHE_IO,
  PERF_COMPONENTS,
  PERF_HEALTH,
  PERF_HOT_PATHS,
  PERF_KPIS,
  PERF_RESOURCE_ALLOC,
  PERF_TOOLS,
  PERF_WORKER_POOLS,
  type PerfComponentStatus,
} from "./mocks";
import { Bar, Panel, Pill, PrHero, Spark, type PillTone } from "./shared";

const TYPE_OPTIONS = ["Alle types", ...Array.from(new Set(PERF_COMPONENTS.map((c) => c.type)))];
const STATUS_OPTIONS = ["Alle statussen", "Gezond", "Belast", "Waarschuwing"] as const;

const NAME_ICON_COLORS = [
  "#8B5CF6",
  "#FBBF24",
  "#38BDF8",
  "#F97316",
  "#34D399",
  "#F472B6",
  "#60A5FA",
  "#A78BFA",
];

function deltaArrow(delta: string): string {
  if (delta.startsWith("-")) return "↓";
  if (delta.startsWith("+")) return "↑";
  return "";
}

function statusPillTone(tone: string): PillTone {
  if (tone === "ok") return "ok";
  if (tone === "warn" || tone === "gold") return "gold";
  if (tone === "err") return "err";
  return "muted";
}

function IconBtn({
  label,
  onClick,
  children,
}: {
  label: string;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button type="button" className="lv-pr-icon-btn" aria-label={label} title={label} onClick={onClick}>
      {children}
    </button>
  );
}

function KpiCard({ k }: { k: (typeof PERF_KPIS)[number] }) {
  const hasSpark = "spark" in k && Array.isArray(k.spark);
  const hasBar = "pct" in k && typeof k.pct === "number";
  const hasDelta = "delta" in k && typeof k.delta === "string";
  const warn = "warn" in k && k.warn;
  const sub = "sub" in k ? k.sub : undefined;
  const showSubInline = k.id === "throughput";
  const showSubMeta = Boolean(sub) && !showSubInline;

  return (
    <article className={`lv-pr-kpi${warn ? " is-warn" : ""}`}>
      <div className="lv-pr-kpi-label">{k.label}</div>
      <div className="lv-pr-kpi-value">
        {k.value}
        {showSubInline ? <span className="lv-pr-kpi-unit"> {sub}</span> : null}
      </div>
      <div className="lv-pr-kpi-foot">
        <div className="lv-pr-kpi-meta">
          {showSubMeta ? (
            <span className="lv-pr-kpi-sub">
              {sub}
              {k.id === "ram" && hasBar ? ` (${k.pct}%)` : null}
              {k.id === "workers" && hasDelta ? (
                <span className={`lv-pr-kpi-delta ${k.deltaGood ? "is-good" : "is-bad"}`}> [{k.delta}]</span>
              ) : null}
            </span>
          ) : hasDelta && k.id !== "workers" ? (
            <span className={`lv-pr-kpi-delta ${k.deltaGood ? "is-good" : "is-bad"}`}>
              {deltaArrow(k.delta)} {k.delta}
            </span>
          ) : (
            <span />
          )}
        </div>
        {hasBar && !hasSpark ? (
          <Bar pct={k.pct!} tone={"barTone" in k && k.barTone ? k.barTone : "cyan"} className="lv-pr-kpi-bar" />
        ) : hasSpark ? (
          <Spark points={k.spark!} color={warn ? "#F87171" : "#00E5FF"} width={56} height={18} />
        ) : null}
      </div>
      {k.id === "workers" && hasBar ? (
        <Bar pct={k.pct!} tone={"barTone" in k && k.barTone ? k.barTone : "cyan"} className="lv-pr-kpi-bar" />
      ) : null}
    </article>
  );
}

export function PerformancePage() {
  const toast = useAppToast();
  const [activeTool, setActiveTool] = useState<string>(PERF_TOOLS.find((t) => t.active)?.id ?? PERF_TOOLS[0].id);
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState("Alle types");
  const [statusFilter, setStatusFilter] = useState<string>("Alle statussen");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return PERF_COMPONENTS.filter((row) => {
      if (typeFilter !== "Alle types" && row.type !== typeFilter) return false;
      if (statusFilter !== "Alle statussen" && row.status !== statusFilter) return false;
      if (!q) return true;
      return (
        row.name.toLowerCase().includes(q) ||
        row.type.toLowerCase().includes(q) ||
        row.status.toLowerCase().includes(q)
      );
    });
  }, [query, typeFilter, statusFilter]);

  return (
    <AppShell
      modeLabel="Plugin Mode"
      searchPlaceholder="Zoek datasets, plugins..."
      systemItems={["LLM", "NEURAL", "MEMORY", "TOOLS"]}
      layout="wide"
      pageClass="lv-app--plugin-runtime"
    >
      <main className="lv-main lv-pr-main">
        <PrHero title="PERFORMANCE" image={pluginRuntimeHeroes.performance} imageOnly objectPosition="center 35%" />

        <section className="lv-pr-kpi-row" aria-label="Performance KPIs">
          {PERF_KPIS.map((k) => (
            <KpiCard key={k.id} k={k} />
          ))}
        </section>

        <section className="lv-pr-perf-mid" aria-label="Performance tools and components">
          <Panel title="Performance Tools" className="lv-pr-perf-tools">
            <div className="lv-pr-tools-list">
              {PERF_TOOLS.map((tool) => (
                <button
                  key={tool.id}
                  type="button"
                  className={`lv-pr-tool-btn${activeTool === tool.id ? " is-active" : ""}`}
                  onClick={() => {
                    setActiveTool(tool.id);
                    toast(tool.label);
                  }}
                >
                  {tool.label}
                </button>
              ))}
            </div>
          </Panel>

          <Panel
            title="Plugins & Runtime Componenten"
            className="lv-pr-perf-components"
            action={
              <div className="lv-pr-perf-toolbar">
                <label className="lv-pr-search">
                  <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
                    <circle cx="11" cy="11" r="6.5" fill="none" stroke="currentColor" strokeWidth="1.6" />
                    <path d="M16 16l4 4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                  </svg>
                  <input
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="Zoek componenten..."
                    aria-label="Zoek componenten"
                  />
                </label>
                <select
                  className="lv-pr-select"
                  value={typeFilter}
                  onChange={(e) => setTypeFilter(e.target.value)}
                  aria-label="Filter op type"
                >
                  {TYPE_OPTIONS.map((opt) => (
                    <option key={opt} value={opt}>
                      {opt}
                    </option>
                  ))}
                </select>
                <select
                  className="lv-pr-select"
                  value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value)}
                  aria-label="Filter op status"
                >
                  {STATUS_OPTIONS.map((opt) => (
                    <option key={opt} value={opt}>
                      {opt}
                    </option>
                  ))}
                </select>
                <button type="button" className="lv-pr-refresh" onClick={() => toast("Componenten vernieuwd")}>
                  <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
                    <path
                      d="M4 12a8 8 0 0 1 13.5-5.8M20 12a8 8 0 0 1-13.5 5.8"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.6"
                      strokeLinecap="round"
                    />
                    <path d="M17 3v4h4M7 21v-4H3" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                  </svg>
                  Vernieuwen
                </button>
                <IconBtn label="Rasterweergave" onClick={() => toast("Rasterweergave")}>
                  <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
                    <rect x="3" y="3" width="7" height="7" rx="1" fill="none" stroke="currentColor" strokeWidth="1.6" />
                    <rect x="14" y="3" width="7" height="7" rx="1" fill="none" stroke="currentColor" strokeWidth="1.6" />
                    <rect x="3" y="14" width="7" height="7" rx="1" fill="none" stroke="currentColor" strokeWidth="1.6" />
                    <rect x="14" y="14" width="7" height="7" rx="1" fill="none" stroke="currentColor" strokeWidth="1.6" />
                  </svg>
                </IconBtn>
                <IconBtn label="Kolommen" onClick={() => toast("Kolominstellingen")}>
                  <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
                    <path d="M4 7h16M4 12h16M4 17h10" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                  </svg>
                </IconBtn>
              </div>
            }
          >
            <div className="lv-pr-table-wrap">
              <table className="lv-pr-table lv-pr-perf-table">
                <thead>
                  <tr>
                    <th>Naam</th>
                    <th>Type</th>
                    <th>Status</th>
                    <th>Gem. latentie</th>
                    <th>P95 latentie</th>
                    <th>Throughput</th>
                    <th>Geheugen</th>
                    <th>CPU</th>
                    <th>Errors</th>
                    <th>Laatst actief</th>
                    <th>Acties</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((row, i) => (
                    <tr key={row.id}>
                      <td className="is-name">
                        <span
                          className="lv-pr-name-icon"
                          style={{ background: NAME_ICON_COLORS[i % NAME_ICON_COLORS.length] }}
                          aria-hidden="true"
                        />
                        {row.name}
                      </td>
                      <td>{row.type}</td>
                      <td>
                        <Pill tone={statusPillTone(row.statusTone)}>{row.status as PerfComponentStatus}</Pill>
                      </td>
                      <td>{row.avgLatency}</td>
                      <td className={row.p95Latency.includes("s") && !row.p95Latency.startsWith("0") ? "is-warn" : undefined}>
                        {row.p95Latency}
                      </td>
                      <td>{row.throughput}</td>
                      <td>{row.memory}</td>
                      <td>{row.cpu}</td>
                      <td className={row.errors > 0 ? "is-err" : undefined}>{row.errors}</td>
                      <td>{row.lastActive}</td>
                      <td>
                        <button
                          type="button"
                          className="lv-pr-more"
                          aria-label={`Acties voor ${row.name}`}
                          onClick={() => toast(`Acties · ${row.name}`)}
                        >
                          ⋮
                        </button>
                      </td>
                    </tr>
                  ))}
                  {filtered.length === 0 ? (
                    <tr>
                      <td colSpan={11} className="lv-pr-empty">
                        Geen componenten gevonden
                      </td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          </Panel>
        </section>

        <section className="lv-pr-perf-bottom" aria-label="Performance widgets">
          <Panel title="Hot Paths / Traagste Operaties" className="lv-pr-perf-hot">
            <div className="lv-pr-table-wrap">
              <table className="lv-pr-table">
                <thead>
                  <tr>
                    <th>Naam</th>
                    <th>Gem. tijd</th>
                    <th>Aantal</th>
                    <th>Trend</th>
                  </tr>
                </thead>
                <tbody>
                  {PERF_HOT_PATHS.map((row) => (
                    <tr key={row.id}>
                      <td className="is-name">{row.name}</td>
                      <td>{row.avg}</td>
                      <td>{row.count}</td>
                      <td>
                        <Spark points={row.spark} color="#F87171" width={52} height={16} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>

          <Panel title="Worker Pools / Runtime Queues" className="lv-pr-perf-workers">
            <div className="lv-pr-table-wrap">
              <table className="lv-pr-table">
                <thead>
                  <tr>
                    <th>Pool</th>
                    <th>Actief / Max</th>
                    <th>Queue</th>
                    <th>Gebruik</th>
                  </tr>
                </thead>
                <tbody>
                  {PERF_WORKER_POOLS.map((row) => (
                    <tr key={row.id}>
                      <td className="is-name">{row.name}</td>
                      <td>
                        {row.active} / {row.max}
                      </td>
                      <td className={row.queue >= 10 ? "is-err" : undefined}>{row.queue}</td>
                      <td className="lv-pr-usage-cell">
                        <Bar pct={row.pct} tone={row.barTone} />
                        <span className="lv-pr-usage-pct">{row.pct}%</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>

          <div className="lv-pr-perf-stack">
            <Panel title="Plugin & Runtime Health">
              <div className="lv-pr-table-wrap">
                <table className="lv-pr-table">
                  <thead>
                    <tr>
                      <th>Component</th>
                      <th>Status</th>
                      <th>Trend</th>
                    </tr>
                  </thead>
                  <tbody>
                    {PERF_HEALTH.map((row) => (
                      <tr key={row.id}>
                        <td className="is-name">{row.name}</td>
                        <td>
                          <Pill tone={statusPillTone(row.tone)}>{row.status}</Pill>
                        </td>
                        <td>
                          <Spark
                            points={row.spark}
                            color={row.tone === "ok" ? "#00E5FF" : row.tone === "warn" ? "#FBBF24" : "#F87171"}
                            width={48}
                            height={14}
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>

            <Panel title="Cache & I/O">
              <div className="lv-pr-table-wrap">
                <table className="lv-pr-table">
                  <thead>
                    <tr>
                      <th>Metriek</th>
                      <th>Waarde</th>
                      <th>Trend</th>
                    </tr>
                  </thead>
                  <tbody>
                    {PERF_CACHE_IO.map((row) => (
                      <tr key={row.id}>
                        <td>{row.label}</td>
                        <td className="is-name">{row.value}</td>
                        <td>
                          <Spark points={row.spark} color="#00E5FF" width={48} height={14} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>
          </div>

          <div className="lv-pr-perf-stack">
            <Panel title="Resource Allocatie">
              <div className="lv-pr-table-wrap">
                <table className="lv-pr-table">
                  <thead>
                    <tr>
                      <th>Instelling</th>
                      <th>Huidig</th>
                      <th>Max</th>
                    </tr>
                  </thead>
                  <tbody>
                    {PERF_RESOURCE_ALLOC.map((row) => (
                      <tr key={row.id}>
                        <td>{row.label}</td>
                        <td className="is-name">{row.current}</td>
                        <td>{row.max}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="lv-pr-panel-foot">
                <button type="button" className="lv-pr-ghost-btn" onClick={() => toast("Instellingen aanpassen")}>
                  ⚙ Instellingen aanpassen
                </button>
              </div>
            </Panel>

            <Panel title="Recente Performance Alerts">
              <ul className="lv-pr-alert-list">
                {PERF_ALERTS.map((alert) => (
                  <li key={alert.id}>
                    <span className="time">{alert.time}</span>
                    <Pill tone={statusPillTone(alert.tone)}>{alert.label}</Pill>
                    <span>{alert.message}</span>
                  </li>
                ))}
              </ul>
              <div className="lv-pr-panel-foot">
                <button type="button" className="lv-pr-link" onClick={() => toast("Alle incidenten")}>
                  Toon alle incidenten →
                </button>
              </div>
            </Panel>
          </div>
        </section>
      </main>
    </AppShell>
  );
}
