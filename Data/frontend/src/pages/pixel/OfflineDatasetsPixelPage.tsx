import { useEffect, useMemo, useState } from "react";
import { AppShell } from "../../layouts/AppShell";
import {
  OFFLINE_ACTIONS,
  OFFLINE_ACTIVE_JOBS,
  OFFLINE_CONVERSION_SETTINGS,
  OFFLINE_DATASET_DETAILS,
  OFFLINE_INTEGRITY,
  OFFLINE_PACKAGE_SUMMARY,
  OFFLINE_PAGE_COPY,
  OFFLINE_SIZE_FILTERS,
  OFFLINE_SOURCE_FILTERS,
  OFFLINE_STATS,
  OFFLINE_STATUS_FILTERS,
  OFFLINE_STORAGE_SEGMENTS,
  OFFLINE_TABLE_META,
  OFFLINE_TABLE_ROWS,
  type OfflineDatasetRow,
  type OfflineDatasetStatus,
} from "../../mocks/offline-datasets";
import { useAppToast } from "../../state/useAppToast";
import { PxIcon, PxKpi, PxSwitch } from "./pixel-shared";

const DAYS = ["Zondag", "Maandag", "Dinsdag", "Woensdag", "Donderdag", "Vrijdag", "Zaterdag"];
const MONTHS = ["JAN.", "FEB.", "MRT.", "APR.", "MEI", "JUN.", "JUL.", "AUG.", "SEP.", "OKT.", "NOV.", "DEC."];

function pad(n: number) {
  return String(n).padStart(2, "0");
}

function statusTone(status: OfflineDatasetStatus) {
  if (status === "ready") return "green";
  if (status === "converting") return "cyan";
  if (status === "queued") return "gold";
  if (status === "verification_failed") return "red";
  return "orange";
}

function detailForRow(row: OfflineDatasetRow | null) {
  if (!row) return null;
  const preset = OFFLINE_DATASET_DETAILS[row.id];
  if (preset) return preset;
  return {
    id: row.id,
    name: row.name,
    status: row.status,
    statusLabel: row.statusLabel,
    source: row.source,
    description: `Offline package voor ${row.name}.`,
    originalSize: row.size,
    localSize: row.size,
    format: ".jvpack",
    localPath: row.localPath,
    checksum: row.checksum,
    lastSynced: row.lastSynced,
    indexPresent: row.status === "ready",
    usedBy: "—",
  };
}

function offlineStatHint(stat: (typeof OFFLINE_STATS)[number]): string | undefined {
  const row = stat as { hint?: string; delta?: string };
  return row.hint ?? row.delta;
}

export function OfflineDatasetsPixelPage() {
  const toast = useAppToast();
  const [now, setNow] = useState(() => new Date());
  const [selectedId, setSelectedId] = useState("nl_wiki_2024");
  const [query, setQuery] = useState("");
  const [sourceFilter, setSourceFilter] = useState(OFFLINE_SOURCE_FILTERS[0]);
  const [statusFilter, setStatusFilter] = useState(OFFLINE_STATUS_FILTERS[0]);
  const [sizeFilter, setSizeFilter] = useState(OFFLINE_SIZE_FILTERS[0]);
  const [convToggles, setConvToggles] = useState(() =>
    Object.fromEntries(OFFLINE_CONVERSION_SETTINGS.toggles.map((t) => [t.id, t.on])),
  );

  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 30_000);
    return () => window.clearInterval(id);
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return OFFLINE_TABLE_ROWS.filter((row) => {
      if (sourceFilter !== "Alle bronnen" && row.source !== sourceFilter) return false;
      if (statusFilter !== "Alle statussen") {
        const map: Record<string, OfflineDatasetStatus> = {
          "Offline klaar": "ready",
          Converting: "converting",
          Queued: "queued",
          "Sync required": "sync_required",
        };
        const want = map[statusFilter];
        if (want && row.status !== want) return false;
      }
      if (!q) return true;
      return (
        row.name.toLowerCase().includes(q) ||
        row.source.toLowerCase().includes(q) ||
        row.localPath.toLowerCase().includes(q)
      );
    });
  }, [query, sourceFilter, statusFilter, sizeFilter]);

  const selected =
    filtered.find((r) => r.id === selectedId) ??
    OFFLINE_TABLE_ROWS.find((r) => r.id === selectedId) ??
    null;
  const detail = detailForRow(selected);

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Dataset Offline"
      searchPlaceholder="Zoek offline packages..."
      systemItems={["OFFLINE", "892 GB", "3 JOBS", "SYNC"]}
      layout="wide"
      pageClass="lv-app--pixel-datasets"
    >
      <main className="lv-main lv-px-main">
        <div className="lv-px-stack">
          <header className="lv-px-hero">
            <div className="lv-px-hero-grid">
              <div>
                <h1 className="lv-px-hero-title">{OFFLINE_PAGE_COPY.title}</h1>
                <p className="lv-px-hero-sub">{OFFLINE_PAGE_COPY.subtitle}</p>
              </div>
              <p className="lv-px-hero-quote">{OFFLINE_PAGE_COPY.quote}</p>
              <div className="lv-px-clock">
                <div className="date">
                  {DAYS[now.getDay()]!.slice(0, 2).toUpperCase()}, {now.getDate()} {MONTHS[now.getMonth()]}{" "}
                  {now.getFullYear()}
                </div>
                <div className="time">
                  {pad(now.getHours())}:{pad(now.getMinutes())}
                </div>
              </div>
            </div>
          </header>

          <div className="lv-px-kpi-row">
            {OFFLINE_STATS.map((stat) => (
              <PxKpi
                key={stat.id}
                label={stat.label}
                value={stat.value}
                hint={offlineStatHint(stat)}
                hintTone={stat.tone === "cyan" ? "cyan" : stat.tone === "gold" ? "gold" : stat.tone === "red" ? "red" : "muted"}
                icon={stat.icon}
                progress={"progress" in stat ? stat.progress : undefined}
              />
            ))}
          </div>

          <div className="lv-px-actions">
            {OFFLINE_ACTIONS.map((action) => (
              <button key={action.id} type="button" className="lv-px-action" onClick={() => toast(action.toast)}>
                <span className="lv-px-action-ico">
                  <PxIcon name={action.icon} />
                </span>
                <span className="lv-px-action-title">{action.label}</span>
              </button>
            ))}
          </div>

          <div className="lv-px-workspace">
            <section className="lv-px-panel" style={{ gridColumn: "span 2" }}>
              <div className="lv-px-filters">
                <label className="lv-px-search">
                  <PxIcon name="search" />
                  <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Zoek..." aria-label="Zoek offline datasets" />
                </label>
                <select className="lv-px-select" value={sourceFilter} onChange={(e) => setSourceFilter(e.target.value)}>
                  {OFFLINE_SOURCE_FILTERS.map((f) => (
                    <option key={f} value={f}>{f}</option>
                  ))}
                </select>
                <select className="lv-px-select" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
                  {OFFLINE_STATUS_FILTERS.map((f) => (
                    <option key={f} value={f}>{f}</option>
                  ))}
                </select>
                <select className="lv-px-select" value={sizeFilter} onChange={(e) => setSizeFilter(e.target.value)}>
                  {OFFLINE_SIZE_FILTERS.map((f) => (
                    <option key={f} value={f}>{f}</option>
                  ))}
                </select>
              </div>
              <div className="lv-px-table-wrap">
                <table className="lv-px-table">
                  <thead>
                    <tr>
                      <th>Naam</th>
                      <th>Bron</th>
                      <th>Grootte</th>
                      <th>Status</th>
                      <th>Compressie</th>
                      <th>Pad</th>
                      <th>Sync</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map((row) => (
                      <tr
                        key={row.id}
                        className={row.id === selectedId ? "is-active" : ""}
                        onClick={() => setSelectedId(row.id)}
                      >
                        <td><strong>{row.name}</strong></td>
                        <td>{row.source}</td>
                        <td>{row.size}</td>
                        <td>
                          <span className={`lv-px-pill is-${statusTone(row.status)}`}>
                            {row.progress != null && row.status === "converting"
                              ? `${row.statusLabel} (${row.progress}%)`
                              : row.statusLabel}
                          </span>
                        </td>
                        <td>{row.compression}</td>
                        <td style={{ fontSize: 8 }}>{row.localPath}</td>
                        <td>{row.lastSynced}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p style={{ fontSize: 9, color: "var(--lv-text-muted)", marginTop: 6 }}>
                {OFFLINE_TABLE_META.total} datasets · toont {filtered.length}
              </p>
            </section>

            <aside className="lv-px-stack">
              <section className="lv-px-panel">
                <h2 className="lv-px-panel-title">Package details</h2>
                {detail ? (
                  <>
                    <p style={{ fontSize: 11, color: "var(--lv-text-bright)" }}>{detail.name}</p>
                    <p style={{ fontSize: 10 }}>{detail.description}</p>
                    <dl className="lv-px-meta-grid" style={{ marginTop: 8 }}>
                      <dt>Status</dt>
                      <dd>{detail.statusLabel}</dd>
                      <dt>Origineel</dt>
                      <dd>{detail.originalSize}</dd>
                      <dt>Lokaal</dt>
                      <dd>{detail.localSize}</dd>
                      <dt>Format</dt>
                      <dd>{detail.format}</dd>
                      <dt>Checksum</dt>
                      <dd>{detail.checksum}</dd>
                      <dt>Gebruikt door</dt>
                      <dd>{detail.usedBy}</dd>
                    </dl>
                  </>
                ) : null}
              </section>

              <section className="lv-px-panel">
                <h2 className="lv-px-panel-title">Opslag segmenten</h2>
                {OFFLINE_STORAGE_SEGMENTS.map((seg) => (
                  <div key={seg.label} style={{ marginTop: 6 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 9 }}>
                      <span>{seg.label}</span>
                      <span>{seg.value}</span>
                    </div>
                    <div className="lv-px-progress is-thin">
                      <i style={{ width: `${seg.pct}%`, background: seg.color }} />
                    </div>
                  </div>
                ))}
              </section>

              <section className="lv-px-panel">
                <h2 className="lv-px-panel-title">Conversie instellingen</h2>
                <p style={{ fontSize: 10 }}>
                  {OFFLINE_CONVERSION_SETTINGS.format} · level {OFFLINE_CONVERSION_SETTINGS.level} · chunk{" "}
                  {OFFLINE_CONVERSION_SETTINGS.chunk}
                </p>
                {OFFLINE_CONVERSION_SETTINGS.toggles.map((t) => (
                  <div key={t.id} className="lv-px-toggle-row">
                    <strong>{t.label}</strong>
                    <PxSwitch
                      label={t.label}
                      on={!!convToggles[t.id]}
                      onToggle={() => {
                        setConvToggles((prev) => ({ ...prev, [t.id]: !prev[t.id] }));
                        toast(t.label);
                      }}
                    />
                  </div>
                ))}
              </section>

              <section className="lv-px-panel">
                <h2 className="lv-px-panel-title">Actieve jobs</h2>
                {OFFLINE_ACTIVE_JOBS.map((job) => (
                  <div key={job.id} className="lv-px-queue-item">
                    <div className="lv-px-queue-top">
                      <strong>{job.dataset}</strong>
                      <span>{job.state}</span>
                    </div>
                    <div className="lv-px-progress">
                      <i style={{ width: `${job.progress}%` }} />
                    </div>
                    <div className="lv-px-queue-meta">
                      <span>{job.task}</span>
                      <span>{job.eta}</span>
                    </div>
                  </div>
                ))}
              </section>

              <section className="lv-px-panel">
                <h2 className="lv-px-panel-title">Integriteit</h2>
                <p style={{ fontSize: 10 }}>
                  {OFFLINE_INTEGRITY.result} · {OFFLINE_INTEGRITY.lastCheck}
                </p>
                {OFFLINE_INTEGRITY.checks.map((c) => (
                  <div key={c.id} style={{ fontSize: 10, padding: "4px 0", color: c.ok ? "var(--lv-success)" : "var(--lv-danger)" }}>
                    {c.ok ? "✓" : "✕"} {c.label}
                  </div>
                ))}
              </section>

              {selected?.status === "ready" ? (
                <section className="lv-px-panel">
                  <h2 className="lv-px-panel-title">Package export</h2>
                  <p style={{ fontSize: 10 }}>
                    {OFFLINE_PACKAGE_SUMMARY.format} v{OFFLINE_PACKAGE_SUMMARY.version} · {OFFLINE_PACKAGE_SUMMARY.size}
                  </p>
                  {OFFLINE_PACKAGE_SUMMARY.includes.map((inc) => (
                    <div key={inc.id} className="lv-px-toggle-row">
                      <span>{inc.label}</span>
                      <PxSwitch label={inc.label} on={inc.on} onToggle={() => toast(inc.label)} />
                    </div>
                  ))}
                  <button type="button" className="lv-px-btn is-gold" style={{ marginTop: 8, width: "100%" }} onClick={() => toast("Package-export voorbereid")}>
                    Exporteer package
                  </button>
                </section>
              ) : null}
            </aside>
          </div>
        </div>
      </main>
    </AppShell>
  );
}
