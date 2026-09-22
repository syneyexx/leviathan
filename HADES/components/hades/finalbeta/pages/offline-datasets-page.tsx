"use client";

import { useEffect, useMemo, useState } from "react";
import { FbIcon } from "../icons";
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
} from "../mocks/offline-datasets";
import { FinalBetaShell } from "../shell/finalbeta-shell";
import type { FinalBetaNavigate } from "../types";

type Props = { onNavigate: FinalBetaNavigate };

const DAYS = ["Zondag", "Maandag", "Dinsdag", "Woensdag", "Donderdag", "Vrijdag", "Zaterdag"];
const MONTHS = [
  "JAN.",
  "FEB.",
  "MRT.",
  "APR.",
  "MEI",
  "JUN.",
  "JUL.",
  "AUG.",
  "SEP.",
  "OKT.",
  "NOV.",
  "DEC.",
];

function pad(n: number) {
  return String(n).padStart(2, "0");
}

function statusTone(status: OfflineDatasetStatus): string {
  if (status === "ready") return "green";
  if (status === "converting") return "cyan";
  if (status === "queued") return "gold";
  if (status === "verification_failed") return "red";
  return "orange";
}

function StatusPill({ row }: { row: OfflineDatasetRow }) {
  const tone = statusTone(row.status);
  const label =
    row.status === "converting" && row.progress != null
      ? `${row.statusLabel} (${row.progress}%)`
      : row.statusLabel;
  return (
    <span className={`od-status ${tone}`}>
      <i />
      {label}
    </span>
  );
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

export function OfflineDatasetsPage({ onNavigate }: Props) {
  const [now, setNow] = useState(() => new Date());
  const [selectedId, setSelectedId] = useState("nl_wiki_2024");
  const [query, setQuery] = useState("");
  const [view, setView] = useState<"table" | "card">("table");
  const [sourceFilter, setSourceFilter] = useState(OFFLINE_SOURCE_FILTERS[0]);
  const [statusFilter, setStatusFilter] = useState(OFFLINE_STATUS_FILTERS[0]);
  const [sizeFilter, setSizeFilter] = useState(OFFLINE_SIZE_FILTERS[0]);

  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 30_000);
    return () => window.clearInterval(id);
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return OFFLINE_TABLE_ROWS.filter((row) => {
      if (sourceFilter !== "Alle bronnen" && row.source !== sourceFilter) return false;
      if (statusFilter !== "Alle statussen") {
        const map: Record<string, OfflineDatasetStatus | "converting"> = {
          "Offline klaar": "ready",
          Converting: "converting",
          Queued: "queued",
          "Sync required": "sync_required",
        };
        const want = map[statusFilter];
        if (want && row.status !== want) return false;
      }
      if (sizeFilter === "< 10 GB" && !row.size.includes("GB") && parseFloat(row.size) >= 10) return false;
      if (sizeFilter === "10–100 GB") {
        const n = parseFloat(row.size);
        if (Number.isFinite(n) && (n < 10 || n > 100)) return false;
      }
      if (sizeFilter === "> 100 GB") {
        const n = parseFloat(row.size);
        if (Number.isFinite(n) && n <= 100) return false;
      }
      if (!q) return true;
      return (
        row.name.toLowerCase().includes(q) ||
        row.source.toLowerCase().includes(q) ||
        row.localPath.toLowerCase().includes(q)
      );
    });
  }, [query, sourceFilter, statusFilter, sizeFilter]);

  const selected = filtered.find((r) => r.id === selectedId) ?? OFFLINE_TABLE_ROWS.find((r) => r.id === selectedId) ?? null;
  const detail = detailForRow(selected);
  const showPackageInspector = selected?.status === "ready";

  const body = (
    <div className="od-page">
      <header className="od-welcome">
        <div className="od-welcome-copy">
          <h1>{OFFLINE_PAGE_COPY.title}</h1>
          <p>{OFFLINE_PAGE_COPY.subtitle}</p>
        </div>
        <div className="od-welcome-mid">{OFFLINE_PAGE_COPY.quote}</div>
        <div className="od-welcome-clock">
          <div className="od-clock-copy">
            <div className="date">
              {DAYS[now.getDay()].slice(0, 2).toUpperCase()}, {now.getDate()} {MONTHS[now.getMonth()]}{" "}
              {now.getFullYear()}
            </div>
            <div className="time">{pad(now.getHours())}:{pad(now.getMinutes())}</div>
          </div>
          <FbIcon name="bolt" size={22} className="od-sun" />
        </div>
      </header>

      <div className="od-stats">
        {OFFLINE_STATS.map((stat) => (
          <article key={stat.id} className="od-stat card">
            <span className={`od-stat-ico ${stat.tone}`}>
              <FbIcon name={stat.icon} size={16} />
            </span>
            <div className="od-stat-body">
              <div className="od-stat-label">{stat.label}</div>
              <div className="od-stat-value-row">
                <span className="od-stat-value">{stat.value}</span>
                {"sub" in stat && stat.sub ? <span className="od-stat-sub">{stat.sub}</span> : null}
                {"delta" in stat && stat.delta ? (
                  <span className={`od-stat-delta ${stat.deltaTone ?? ""}`}>{stat.delta}</span>
                ) : null}
              </div>
              {"progress" in stat && stat.progress != null ? (
                <div className="od-stat-progress">
                  <i style={{ width: `${stat.progress}%` }} />
                </div>
              ) : null}
              <div className="od-stat-hint">{stat.hint}</div>
            </div>
          </article>
        ))}
      </div>

      <div className="od-workspace">
        <aside className="od-actions card">
          <h2 className="od-panel-title">Offline Acties</h2>
          <div className="od-action-list">
            {OFFLINE_ACTIONS.map((action) => (
              <button
                key={action.id}
                type="button"
                className="od-action-btn"
                data-toast={action.toast}
              >
                <FbIcon name={action.icon} size={14} />
                <span>{action.label}</span>
              </button>
            ))}
          </div>
        </aside>

        <section className="od-table-panel card">
          <div className="od-table-head">
            <div>
              <h2 className="od-panel-title">Offline Datasets</h2>
              <p className="od-panel-sub">{OFFLINE_TABLE_META.total} datasets in lokale bibliotheek</p>
            </div>
            <div className="od-table-tools">
              <label className="od-search">
                <FbIcon name="search" size={13} />
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Zoek datasets, offline bestanden..."
                  aria-label="Zoek datasets"
                />
              </label>
              <select
                className="od-select"
                value={sourceFilter}
                onChange={(e) => setSourceFilter(e.target.value)}
                aria-label="Bron filter"
              >
                {OFFLINE_SOURCE_FILTERS.map((opt) => (
                  <option key={opt} value={opt}>{opt}</option>
                ))}
              </select>
              <select
                className="od-select"
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                aria-label="Status filter"
              >
                {OFFLINE_STATUS_FILTERS.map((opt) => (
                  <option key={opt} value={opt}>{opt}</option>
                ))}
              </select>
              <select
                className="od-select"
                value={sizeFilter}
                onChange={(e) => setSizeFilter(e.target.value)}
                aria-label="Grootte filter"
              >
                {OFFLINE_SIZE_FILTERS.map((opt) => (
                  <option key={opt} value={opt}>{opt}</option>
                ))}
              </select>
              <div className="od-view-toggle" role="group" aria-label="Weergave">
                <button
                  type="button"
                  className={view === "table" ? "active" : ""}
                  onClick={() => setView("table")}
                  data-toast="Tabelweergave"
                >
                  Tabel
                </button>
                <button
                  type="button"
                  className={view === "card" ? "active" : ""}
                  onClick={() => setView("card")}
                  data-toast="Kaartweergave"
                >
                  Kaart
                </button>
              </div>
            </div>
          </div>

          {view === "table" ? (
            <div className="od-table-wrap">
              <table className="od-table">
                <thead>
                  <tr>
                    <th className="od-col-check" aria-label="Selectie" />
                    <th>Dataset Naam</th>
                    <th>Bron</th>
                    <th>Grootte</th>
                    <th>Offline Status</th>
                    <th>Compressie</th>
                    <th>Lokaal Pad</th>
                    <th>Checksum (SHA256)</th>
                    <th>Laatst Gesynced</th>
                    <th className="od-col-menu" aria-label="Acties" />
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((row) => (
                    <tr
                      key={row.id}
                      className={selectedId === row.id ? "active" : undefined}
                      onClick={() => setSelectedId(row.id)}
                    >
                      <td className="od-col-check">
                        <input type="checkbox" readOnly checked={selectedId === row.id} aria-label={`Selecteer ${row.name}`} />
                      </td>
                      <td className="od-name">
                        <FbIcon name="database" size={13} />
                        <strong>{row.name}</strong>
                      </td>
                      <td>{row.source}</td>
                      <td>{row.size}</td>
                      <td><StatusPill row={row} /></td>
                      <td>{row.compression}</td>
                      <td className="od-path">{row.localPath}</td>
                      <td className="od-mono">{row.checksum}</td>
                      <td>{row.lastSynced}</td>
                      <td className="od-col-menu">
                        <button type="button" aria-label="Meer" data-toast="Meer acties" onClick={(e) => e.stopPropagation()}>
                          <FbIcon name="more" size={14} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="od-card-grid">
              {filtered.map((row) => (
                <button
                  key={row.id}
                  type="button"
                  className={`od-dataset-card${selectedId === row.id ? " active" : ""}`}
                  onClick={() => setSelectedId(row.id)}
                >
                  <strong>{row.name}</strong>
                  <span>{row.source} · {row.size}</span>
                  <StatusPill row={row} />
                </button>
              ))}
            </div>
          )}

          <footer className="od-table-foot">
            <span>
              {OFFLINE_TABLE_META.page * OFFLINE_TABLE_META.pageSize - OFFLINE_TABLE_META.pageSize + 1}-
              {Math.min(OFFLINE_TABLE_META.page * OFFLINE_TABLE_META.pageSize, OFFLINE_TABLE_META.total)} van{" "}
              {OFFLINE_TABLE_META.total} datasets
            </span>
            <label className="od-page-size">
              Rijen per pagina:
              <select defaultValue={String(OFFLINE_TABLE_META.pageSize)} aria-label="Rijen per pagina">
                <option value="8">8</option>
                <option value="16">16</option>
                <option value="32">32</option>
              </select>
            </label>
          </footer>
        </section>
      </div>

      <div className="od-bottom">
        <section className="od-detail card">
          <div className="od-detail-head">
            <h2 className="od-panel-title">Dataset Details</h2>
            {detail ? (
              <span className={`od-status ${statusTone(detail.status)}`}>
                <i />
                {detail.statusLabel}
              </span>
            ) : null}
          </div>
          {detail ? (
            <div className="od-detail-grid">
              <div className="od-detail-name">{detail.name}</div>
              <div className="od-kv">
                <span className="k">Bron</span>
                <span className="v">{detail.source}</span>
              </div>
              <div className="od-kv wide">
                <span className="k">Beschrijving</span>
                <span className="v">{detail.description}</span>
              </div>
              <div className="od-kv">
                <span className="k">Originele grootte</span>
                <span className="v">{detail.originalSize}</span>
              </div>
              <div className="od-kv">
                <span className="k">Lokale grootte</span>
                <span className="v">{detail.localSize}</span>
              </div>
              <div className="od-kv">
                <span className="k">Bestandsformaat</span>
                <span className="v">{detail.format}</span>
              </div>
              <div className="od-kv wide">
                <span className="k">Lokaal pad</span>
                <button type="button" className="od-path-link" data-toast="Pad gekopieerd">
                  {detail.localPath}
                </button>
              </div>
              <div className="od-kv wide">
                <span className="k">Checksum</span>
                <span className="v od-mono">{detail.checksum}</span>
              </div>
              <div className="od-kv">
                <span className="k">Laatste sync</span>
                <span className="v">{detail.lastSynced}</span>
              </div>
              <div className="od-kv">
                <span className="k">Index aanwezig</span>
                <span className="v">{detail.indexPresent ? "Ja" : "Nee"}</span>
              </div>
              <div className="od-kv">
                <span className="k">Gebruikt door</span>
                <span className="v">{detail.usedBy}</span>
              </div>
            </div>
          ) : (
            <p className="od-muted">Selecteer een dataset in de tabel.</p>
          )}
        </section>

        <section className="od-settings-stack">
          <article className="od-storage card">
            <h2 className="od-panel-title">Lokale Opslag</h2>
            <p className="od-storage-summary">
              <strong>892 GB</strong> van <span>4.0 TB</span> gebruikt (22%)
            </p>
            <div className="od-storage-bar">
              {OFFLINE_STORAGE_SEGMENTS.map((seg) => (
                <i key={seg.label} style={{ flex: seg.pct, background: seg.color }} title={seg.label} />
              ))}
            </div>
            <ul className="od-storage-legend">
              {OFFLINE_STORAGE_SEGMENTS.map((seg) => (
                <li key={seg.label}>
                  <i style={{ background: seg.color }} />
                  <span>{seg.label}</span>
                  <b>{seg.value}</b>
                </li>
              ))}
            </ul>
          </article>

          <article className="od-conversion card">
            <h2 className="od-panel-title">Conversie Instellingen</h2>
            <div className="od-conversion-grid">
              <label className="od-field">
                <span>Compressie formaat</span>
                <select defaultValue={OFFLINE_CONVERSION_SETTINGS.format} aria-label="Compressie formaat">
                  <option value="zstd">zstd</option>
                  <option value="lz4">lz4</option>
                </select>
              </label>
              <label className="od-field">
                <span>Compressie niveau</span>
                <select defaultValue={OFFLINE_CONVERSION_SETTINGS.level} aria-label="Compressie niveau">
                  <option value="6">6</option>
                  <option value="3">3</option>
                  <option value="9">9</option>
                </select>
              </label>
              <label className="od-field">
                <span>Chunk grootte</span>
                <select defaultValue={OFFLINE_CONVERSION_SETTINGS.chunk} aria-label="Chunk grootte">
                  <option value="1 GB">1 GB</option>
                  <option value="512 MB">512 MB</option>
                </select>
              </label>
            </div>
            <ul className="od-toggle-list">
              {OFFLINE_CONVERSION_SETTINGS.toggles.map((toggle) => (
                <li key={toggle.id}>
                  <span>{toggle.label}</span>
                  <button
                    type="button"
                    className={`od-toggle${toggle.on ? " on" : ""}`}
                    role="switch"
                    aria-checked={toggle.on}
                    data-toast={toggle.label}
                  >
                    <i />
                  </button>
                </li>
              ))}
              <li className="od-toggle-highlight">
                <span>Splits in portable package (.jvpack)</span>
                <button
                  type="button"
                  className={`od-toggle${OFFLINE_CONVERSION_SETTINGS.portablePackage ? " on cyan" : ""}`}
                  role="switch"
                  aria-checked={OFFLINE_CONVERSION_SETTINGS.portablePackage}
                  data-toast="Portable package"
                >
                  <i />
                </button>
              </li>
            </ul>
          </article>
        </section>

        <section className="od-jobs card">
          <h2 className="od-panel-title">Actieve Jobs</h2>
          <ul className="od-job-list">
            {OFFLINE_ACTIVE_JOBS.map((job) => (
              <li key={job.id} className="od-job-row">
                <div className="od-job-copy">
                  <strong>{job.dataset}</strong>
                  <span>{job.task}</span>
                </div>
                <div className="od-job-progress">
                  <div className="od-progress-bar">
                    <i style={{ width: `${job.progress}%` }} />
                  </div>
                  <span>{job.progress}%</span>
                </div>
                <div className="od-job-meta">
                  <span>{job.eta}</span>
                  <span className={`od-job-state ${job.state === "Bezig" ? "busy" : ""}`}>{job.state}</span>
                </div>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );

  const inspector = showPackageInspector ? (
    <>
      <section className="insp-section od-insp">
        <div className="od-insp-head">
          <h3 className="insp-title">Integriteitsverificatie</h3>
          <span className="od-verify-badge">{OFFLINE_INTEGRITY.result}</span>
        </div>
        <p className="od-insp-sub">Laatste controle: {OFFLINE_INTEGRITY.lastCheck}</p>
        <div className="insp-card od-checklist">
          <ul>
            {OFFLINE_INTEGRITY.checks.map((check) => (
              <li key={check.id} className={check.ok ? "ok" : "fail"}>
                <FbIcon name="checkcircle" size={14} />
                <span>{check.label}</span>
                <b>{check.ok ? "OK" : "Fout"}</b>
              </li>
            ))}
          </ul>
        </div>
        <button type="button" className="btn btn-sm btn-outline btn-block" data-toast="Integriteit opnieuw controleren">
          Opnieuw verifiëren
        </button>
      </section>

      <section className="insp-section od-insp">
        <h3 className="insp-title">Offline Package</h3>
        <div className="insp-card od-package-card">
          <div className="od-package-meta">
            <div>
              <span className="k">Formaat</span>
              <span className="v">{OFFLINE_PACKAGE_SUMMARY.format}</span>
            </div>
            <div>
              <span className="k">Versie</span>
              <span className="v">{OFFLINE_PACKAGE_SUMMARY.version}</span>
            </div>
            <div>
              <span className="k">Grootte</span>
              <span className="v">{OFFLINE_PACKAGE_SUMMARY.size}</span>
            </div>
          </div>
          <ul className="od-package-includes">
            {OFFLINE_PACKAGE_SUMMARY.includes.map((item) => (
              <li key={item.id} className={item.on ? "on" : ""}>
                <FbIcon name="check" size={12} />
                {item.label}
              </li>
            ))}
          </ul>
        </div>
        <button type="button" className="btn btn-gold btn-block od-export-btn" data-toast="Package-export gestart">
          <FbIcon name="upload" size={14} />
          Exporteer package…
        </button>
      </section>
    </>
  ) : detail ? (
    <>
      <section className="insp-section od-insp">
        <h3 className="insp-title">Selectie detail</h3>
        <div className="insp-card">
          <div className="detail-row">
            <span className="k">Dataset</span>
            <span className="v">{detail.name}</span>
          </div>
          <div className="detail-row">
            <span className="k">Status</span>
            <span className="v">{detail.statusLabel}</span>
          </div>
          <div className="detail-row">
            <span className="k">Bron</span>
            <span className="v">{detail.source}</span>
          </div>
          <div className="detail-row">
            <span className="k">Pad</span>
            <span className="v od-mono">{detail.localPath}</span>
          </div>
          <p className="od-insp-note">{detail.description}</p>
        </div>
        <button type="button" className="btn btn-sm btn-outline btn-block" data-toast="Details vernieuwd">
          Vernieuwen
        </button>
      </section>
    </>
  ) : (
    <section className="insp-section">
      <h3 className="insp-title">Inspector</h3>
      <div className="insp-card">
        <p className="muted" style={{ margin: 0 }}>Selecteer een offline dataset.</p>
      </div>
    </section>
  );

  const footer = (
    <footer className="dash-footer od-footer">
      <span>HADES FINALBETA v0.9.0&nbsp;&nbsp;|&nbsp;&nbsp;Local AI Platform</span>
      <span className="motto">
        A DEEPER INTELLIGENCE A BRIGHTER TOMORROW. <b>━━</b>
      </span>
    </footer>
  );

  return (
    <FinalBetaShell
      page="offline-datasets"
      body={body}
      inspector={inspector}
      onNavigate={onNavigate}
      appClassName="od-app"
      mainClassName="od-main"
      footer={footer}
    />
  );
}
