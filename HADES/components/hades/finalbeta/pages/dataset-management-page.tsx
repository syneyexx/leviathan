"use client";

import { useMemo, useState } from "react";
import { FbIcon } from "../icons";
import {
  DM_ACTIONS,
  DM_DATASET_DETAILS,
  DM_FOOTER_ACTIONS,
  DM_IMPORT_JOBS,
  DM_PAGE_COPY,
  DM_QUICK_ACTIONS,
  DM_SAMPLE_JSON,
  DM_SAMPLE_TABS,
  DM_SOURCE_FILTERS,
  DM_SPLIT_FILTERS,
  DM_STATS,
  DM_STATUS_FILTERS,
  DM_STORAGE_HEALTH,
  DM_TABLE_META,
  DM_TABLE_ROWS,
  DM_TAG_CLOUD,
  DM_TYPE_FILTERS,
  type DatasetMgmtDetail,
  type DatasetMgmtRow,
  type DatasetImportJob,
  type DatasetMgmtStatus,
  type DatasetSampleTab,
} from "../mocks/dataset-management";
import { FinalBetaShell } from "../shell/finalbeta-shell";
import type { FinalBetaNavigate } from "../types";

type Props = { onNavigate: FinalBetaNavigate };

function statusTone(status: DatasetMgmtStatus): string {
  if (status === "Klaar") return "green";
  if (status === "Verwerkt") return "cyan";
  if (status === "Bezig") return "cyan";
  if (status === "Wachtrij") return "gold";
  if (status === "Waarschuwing") return "orange";
  return "red";
}

function jobStatusTone(status: DatasetImportJob["status"]): string {
  if (status === "Klaar") return "green";
  if (status === "Bezig") return "cyan";
  return "gold";
}

function StatusPill({ status }: { status: DatasetMgmtStatus }) {
  return (
    <span className={`dm-status ${statusTone(status)}`}>
      <i />
      {status}
    </span>
  );
}

function detailForRow(row: DatasetMgmtRow | null): DatasetMgmtDetail | null {
  if (!row) return null;
  const preset = DM_DATASET_DETAILS[row.id];
  if (preset) return preset;
  return {
    id: row.id,
    name: row.name,
    description: `Dataset ${row.name} — ${row.type} uit ${row.source}.`,
    source: row.source,
    type: row.type,
    splits: `${row.split} 100%`,
    location: `/data/datasets/${row.id}`,
    version: "1.0.0",
    language: row.tags.includes("nl") ? "Nederlands" : "—",
    license: "—",
    taskType: row.type,
    created: row.updated,
    updated: row.updated,
  };
}

export function DatasetManagementPage({ onNavigate }: Props) {
  const [selectedId, setSelectedId] = useState("nl_wiki_2024");
  const [query, setQuery] = useState("");
  const [view, setView] = useState<"table" | "card">("table");
  const [typeFilter, setTypeFilter] = useState(DM_TYPE_FILTERS[0]);
  const [sourceFilter, setSourceFilter] = useState(DM_SOURCE_FILTERS[0]);
  const [splitFilter, setSplitFilter] = useState(DM_SPLIT_FILTERS[0]);
  const [statusFilter, setStatusFilter] = useState(DM_STATUS_FILTERS[0]);
  const [sampleTab, setSampleTab] = useState<DatasetSampleTab>("JSON");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return DM_TABLE_ROWS.filter((row) => {
      if (typeFilter !== "Alle types" && row.type !== typeFilter) return false;
      if (sourceFilter !== "Alle bronnen" && row.source !== sourceFilter) return false;
      if (splitFilter !== "Alle splits" && row.split !== splitFilter) return false;
      if (statusFilter !== "Alle statussen" && row.status !== statusFilter) return false;
      if (!q) return true;
      return (
        row.name.toLowerCase().includes(q) ||
        row.source.toLowerCase().includes(q) ||
        row.tags.some((tag) => tag.toLowerCase().includes(q))
      );
    });
  }, [query, typeFilter, sourceFilter, splitFilter, statusFilter]);

  const selected =
    filtered.find((r) => r.id === selectedId) ??
    DM_TABLE_ROWS.find((r) => r.id === selectedId) ??
    null;
  const detail = detailForRow(selected);

  const body = (
    <div className="dm-page">
      <header className="dm-welcome">
        <div className="dm-welcome-copy">
          <h1>{DM_PAGE_COPY.title}</h1>
          <p>{DM_PAGE_COPY.subtitle}</p>
        </div>
        <div className="dm-welcome-mid">“{DM_PAGE_COPY.quote}”</div>
        <div className="dm-welcome-pillar" aria-hidden="true">
          {DM_PAGE_COPY.pillars.map((line) => (
            <span key={line}>{line}</span>
          ))}
        </div>
      </header>

      <div className="dm-stats">
        {DM_STATS.map((stat) => (
          <article key={stat.id} className="dm-stat card">
            <span className={`dm-stat-ico ${stat.tone}`}>
              <FbIcon name={stat.icon} size={16} />
            </span>
            <div className="dm-stat-body">
              <div className="dm-stat-label">{stat.label}</div>
              <div className="dm-stat-value-row">
                <span className="dm-stat-value">{stat.value}</span>
                {"sub" in stat && stat.sub ? <span className="dm-stat-sub">{stat.sub}</span> : null}
                {"delta" in stat && stat.delta ? (
                  <span className="dm-stat-delta up">{stat.delta}</span>
                ) : null}
              </div>
              {"progress" in stat && stat.progress != null ? (
                <div className="dm-stat-progress">
                  <i style={{ width: `${stat.progress}%` }} />
                </div>
              ) : null}
              <div className="dm-stat-hint">
                {"deltaSub" in stat && stat.deltaSub
                  ? stat.deltaSub
                  : "hint" in stat
                    ? stat.hint
                    : null}
              </div>
            </div>
          </article>
        ))}
      </div>

      <div className="dm-workspace">
        <aside className="dm-actions card">
          <h2 className="dm-panel-title">Dataset Acties</h2>
          <p className="dm-selection-summary">
            Geselecteerd: {selected ? `1 dataset` : "geen"}
          </p>
          <div className="dm-action-list">
            {DM_ACTIONS.map((action) => (
              <button
                key={action.id}
                type="button"
                className={`dm-action-btn${"danger" in action && action.danger ? " danger" : ""}`}
                data-toast={action.toast}
              >
                <FbIcon name={action.icon} size={14} />
                <span>{action.label}</span>
              </button>
            ))}
          </div>
        </aside>

        <section className="dm-table-panel card">
          <div className="dm-table-head">
            <div>
              <h2 className="dm-panel-title">Dataset Bibliotheek</h2>
              <p className="dm-panel-sub">{DM_TABLE_META.total} datasets in bibliotheek</p>
            </div>
            <div className="dm-table-tools">
              <label className="dm-search">
                <FbIcon name="search" size={13} />
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Zoek datasets..."
                  aria-label="Zoek datasets"
                />
              </label>
              <select
                className="dm-select"
                value={typeFilter}
                onChange={(e) => setTypeFilter(e.target.value)}
                aria-label="Type filter"
              >
                {DM_TYPE_FILTERS.map((opt) => (
                  <option key={opt} value={opt}>{opt}</option>
                ))}
              </select>
              <select
                className="dm-select"
                value={sourceFilter}
                onChange={(e) => setSourceFilter(e.target.value)}
                aria-label="Bron filter"
              >
                {DM_SOURCE_FILTERS.map((opt) => (
                  <option key={opt} value={opt}>{opt}</option>
                ))}
              </select>
              <select
                className="dm-select"
                value={splitFilter}
                onChange={(e) => setSplitFilter(e.target.value)}
                aria-label="Split filter"
              >
                {DM_SPLIT_FILTERS.map((opt) => (
                  <option key={opt} value={opt}>{opt}</option>
                ))}
              </select>
              <select
                className="dm-select"
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                aria-label="Status filter"
              >
                {DM_STATUS_FILTERS.map((opt) => (
                  <option key={opt} value={opt}>{opt}</option>
                ))}
              </select>
              <button type="button" className="dm-select" data-toast="Tags filter">
                Tags
              </button>
              <div className="dm-view-toggle" role="group" aria-label="Weergave">
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
            <div className="dm-table-wrap">
              <table className="dm-table">
                <thead>
                  <tr>
                    <th className="dm-col-check" aria-label="Selectie" />
                    <th>Naam</th>
                    <th>Type</th>
                    <th>Bron</th>
                    <th>Split</th>
                    <th>Grootte</th>
                    <th>Tokens / Rijen</th>
                    <th>Status</th>
                    <th>Tags</th>
                    <th>Laatst Bijgewerkt</th>
                    <th className="dm-col-menu" aria-label="Acties" />
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((row) => (
                    <tr
                      key={row.id}
                      className={selectedId === row.id ? "active" : undefined}
                      onClick={() => setSelectedId(row.id)}
                    >
                      <td className="dm-col-check">
                        <input
                          type="checkbox"
                          readOnly
                          checked={selectedId === row.id}
                          aria-label={`Selecteer ${row.name}`}
                        />
                      </td>
                      <td className="dm-name">
                        <FbIcon name="database" size={13} />
                        <strong>{row.name}</strong>
                      </td>
                      <td>
                        <span className={`dm-type-pill ${row.typeTone}`}>{row.type}</span>
                      </td>
                      <td>
                        <span className="dm-source-cell">
                          <FbIcon name={row.sourceIcon} size={12} />
                          {row.source}
                        </span>
                      </td>
                      <td className="dm-mono">{row.split}</td>
                      <td>{row.size}</td>
                      <td>{row.tokens}</td>
                      <td><StatusPill status={row.status} /></td>
                      <td className="dm-tags-cell">
                        {row.tags.map((tag) => (
                          <span key={tag} className="dm-tag-pill">{tag}</span>
                        ))}
                      </td>
                      <td>{row.updated}</td>
                      <td className="dm-col-menu">
                        <button
                          type="button"
                          aria-label="Meer"
                          data-toast="Meer acties"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <FbIcon name="more" size={14} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="dm-card-grid">
              {filtered.map((row) => (
                <button
                  key={row.id}
                  type="button"
                  className={`dm-dataset-card${selectedId === row.id ? " active" : ""}`}
                  onClick={() => setSelectedId(row.id)}
                >
                  <strong>{row.name}</strong>
                  <span>{row.type} · {row.size}</span>
                  <StatusPill status={row.status} />
                </button>
              ))}
            </div>
          )}

          <footer className="dm-table-foot">
            <span>
              {DM_TABLE_META.page * DM_TABLE_META.pageSize - DM_TABLE_META.pageSize + 1}-
              {Math.min(DM_TABLE_META.page * DM_TABLE_META.pageSize, DM_TABLE_META.total)} van{" "}
              {DM_TABLE_META.total} datasets
            </span>
            <div className="dm-pages" role="navigation" aria-label="Paginering">
              {[1, 2, 3, 4, 5].map((n) => (
                <button key={n} type="button" className={n === 1 ? "active" : undefined} data-toast={`Pagina ${n}`}>
                  {n}
                </button>
              ))}
              <span>…</span>
              <button type="button" data-toast={`Pagina ${DM_TABLE_META.pageCount}`}>
                {DM_TABLE_META.pageCount}
              </button>
            </div>
            <label className="dm-page-size">
              Rijen per pagina:
              <select defaultValue={String(DM_TABLE_META.pageSize)} aria-label="Rijen per pagina">
                <option value="8">8</option>
                <option value="16">16</option>
                <option value="32">32</option>
              </select>
            </label>
          </footer>
        </section>
      </div>

      <div className="dm-bottom">
        <section className="dm-detail card">
          <div className="dm-detail-head">
            <h2 className="dm-panel-title">Dataset Details</h2>
            {selected ? <StatusPill status={selected.status} /> : null}
          </div>
          {detail ? (
            <div className="dm-detail-grid">
              <div className="dm-detail-name">{detail.name}</div>
              <div className="dm-kv wide">
                <span className="k">Beschrijving</span>
                <span className="v">{detail.description}</span>
              </div>
              <div className="dm-kv">
                <span className="k">Bron</span>
                <span className="v">{detail.source}</span>
              </div>
              <div className="dm-kv">
                <span className="k">Type</span>
                <span className="v">{detail.type}</span>
              </div>
              <div className="dm-kv">
                <span className="k">Splits</span>
                <span className="v">{detail.splits}</span>
              </div>
              <div className="dm-kv wide">
                <span className="k">Locatie</span>
                <button type="button" className="dm-path-link" data-toast="Pad gekopieerd">
                  {detail.location}
                </button>
              </div>
              <div className="dm-kv">
                <span className="k">Versie</span>
                <span className="v">{detail.version}</span>
              </div>
              <div className="dm-kv">
                <span className="k">Taal</span>
                <span className="v">{detail.language}</span>
              </div>
              <div className="dm-kv">
                <span className="k">Licentie</span>
                <span className="v">{detail.license}</span>
              </div>
              <div className="dm-kv">
                <span className="k">Task type</span>
                <span className="v">{detail.taskType}</span>
              </div>
              <div className="dm-kv">
                <span className="k">Aangemaakt</span>
                <span className="v">{detail.created}</span>
              </div>
              <div className="dm-kv">
                <span className="k">Bijgewerkt</span>
                <span className="v">{detail.updated}</span>
              </div>
            </div>
          ) : (
            <p className="dm-muted">Selecteer een dataset in de bibliotheek.</p>
          )}
        </section>

        <section className="dm-detail card">
          <h2 className="dm-panel-title">Voorbeeld Data (5 Rijen)</h2>
          <nav className="dm-sample-tabs" aria-label="Voorbeeld weergave">
            {DM_SAMPLE_TABS.map((tab) => (
              <button
                key={tab}
                type="button"
                className={sampleTab === tab ? "active" : undefined}
                onClick={() => setSampleTab(tab)}
                data-toast={tab}
              >
                {tab}
              </button>
            ))}
          </nav>
          {sampleTab === "JSON" ? (
            <pre className="dm-sample-pre">{DM_SAMPLE_JSON}</pre>
          ) : (
            <p className="dm-muted">
              {sampleTab === "Tekst"
                ? "Amsterdam is de hoofdstad en grootste stad van Nederland…"
                : "Tabelvoorbeeld — kolommen id, title, text, source."}
            </p>
          )}
        </section>

        <div className="dm-bottom-side">
          <section className="dm-jobs card">
            <h2 className="dm-panel-title">Import &amp; Verwerking Jobs</h2>
            <table className="dm-jobs-table">
              <thead>
                <tr>
                  <th>Taak</th>
                  <th>Dataset</th>
                  <th>Status</th>
                  <th>Voortgang</th>
                  <th>Gestart</th>
                  <th>Duur</th>
                </tr>
              </thead>
              <tbody>
                {DM_IMPORT_JOBS.map((job) => (
                  <tr key={job.id}>
                    <td>{job.task}</td>
                    <td>{job.dataset}</td>
                    <td>
                      <span className={`dm-status ${jobStatusTone(job.status)}`}>
                        <i />
                        {job.status}
                      </span>
                    </td>
                    <td>
                      <div className="dm-job-progress">
                        <div className="dm-progress-bar">
                          <i style={{ width: `${job.progress}%` }} />
                        </div>
                        <span>{job.progress}%</span>
                      </div>
                    </td>
                    <td>{job.started}</td>
                    <td>{job.duration}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <article className="dm-storage card">
            <h2 className="dm-panel-title">Opslag &amp; Gezondheid</h2>
            <p className="dm-storage-summary">
              <strong>{DM_STORAGE_HEALTH.used}</strong> van <span>{DM_STORAGE_HEALTH.total}</span> (
              {DM_STORAGE_HEALTH.pct}%)
            </p>
            <div className="dm-storage-bar">
              <i style={{ flex: DM_STORAGE_HEALTH.pct, background: "#3ac7ee" }} />
              <i style={{ flex: 100 - DM_STORAGE_HEALTH.pct, background: "rgba(48, 102, 123, 0.35)" }} />
            </div>
            <div className="dm-health-row">
              <span>Deduplicatie bespaard</span>
              <b>{DM_STORAGE_HEALTH.dedupeSaved}</b>
            </div>
            <div className="dm-health-row">
              <span>Integriteitscontrole</span>
              <b>{DM_STORAGE_HEALTH.integrity}</b>
            </div>
          </article>

          <article className="dm-conversion card">
            <h2 className="dm-panel-title">Tags en Categorieën</h2>
            <div className="dm-tag-cloud">
              {DM_TAG_CLOUD.map((item) => (
                <button key={item.tag} type="button" data-toast={`Filter: ${item.tag}`}>
                  {item.tag}
                  <span>{item.count}</span>
                </button>
              ))}
            </div>
          </article>
        </div>
      </div>

      <div className="dm-action-bar">
        <span className="dm-action-bar-label">Dataset acties:</span>
        {DM_FOOTER_ACTIONS.map((action) => (
          <button
            key={action.id}
            type="button"
            className={`btn btn-sm ${action.tone === "gold" ? "btn-gold" : action.tone === "danger" ? "btn-outline btn-danger" : "btn-outline"}`}
            data-toast={action.label}
          >
            {action.label}
          </button>
        ))}
      </div>
    </div>
  );

  const inspector = selected && detail ? (
    <>
      <section className="insp-section dm-insp">
        <h3 className="insp-title">Selectie</h3>
        <div className="insp-card">
          <div className="detail-row">
            <span className="k">Dataset</span>
            <span className="v">{detail.name}</span>
          </div>
          <div className="detail-row">
            <span className="k">Status</span>
            <span className="v">{selected.status}</span>
          </div>
          <div className="detail-row">
            <span className="k">Grootte</span>
            <span className="v">{selected.size}</span>
          </div>
          <div className="detail-row">
            <span className="k">Tokens</span>
            <span className="v">{selected.tokens}</span>
          </div>
          <p className="dm-insp-note">{detail.description}</p>
        </div>
      </section>

      <section className="insp-section dm-insp">
        <h3 className="insp-title">Snelle acties</h3>
        <div className="dm-quick-actions">
          {DM_QUICK_ACTIONS.map((action) => (
            <button key={action.id} type="button" data-toast={action.label}>
              <FbIcon name={action.icon} size={14} />
              {action.label}
            </button>
          ))}
        </div>
      </section>
    </>
  ) : (
    <section className="insp-section">
      <h3 className="insp-title">Inspector</h3>
      <div className="insp-card">
        <p className="muted" style={{ margin: 0 }}>Selecteer een dataset in de bibliotheek.</p>
      </div>
    </section>
  );

  const footer = (
    <footer className="dash-footer dm-footer">
      <span>HADES FINALBETA v0.9.0&nbsp;&nbsp;|&nbsp;&nbsp;Local AI Platform</span>
      <span className="motto">
        A DEEPER INTELLIGENCE A BRIGHTER TOMORROW. <b>━━</b>
      </span>
    </footer>
  );

  return (
    <FinalBetaShell
      page="dataset-management"
      body={body}
      inspector={inspector}
      onNavigate={onNavigate}
      appClassName="dm-app"
      mainClassName="dm-main"
      footer={footer}
    />
  );
}
