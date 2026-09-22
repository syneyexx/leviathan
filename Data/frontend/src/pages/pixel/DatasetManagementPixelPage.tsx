import { useMemo, useState } from "react";
import { AppShell } from "../../layouts/AppShell";
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
  type DatasetSampleTab,
} from "../../mocks/dataset-management";
import { useAppToast } from "../../state/useAppToast";
import { PxHero, PxIcon, PxKpi } from "./pixel-shared";

function toneForType(tone: DatasetMgmtRow["typeTone"]) {
  return tone;
}

function toneForStatus(status: DatasetMgmtRow["status"]) {
  if (status === "Klaar") return "green";
  if (status === "Verwerkt" || status === "Bezig") return "cyan";
  if (status === "Wachtrij") return "gold";
  if (status === "Waarschuwing") return "orange";
  return "red";
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

export function DatasetManagementPixelPage() {
  const toast = useAppToast();
  const [selectedId, setSelectedId] = useState("nl_wiki_2024");
  const [query, setQuery] = useState("");
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

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Dataset Management"
      searchPlaceholder="Zoek datasets, tags, bronnen..."
      systemItems={["DATASETS", "842 GB", "3 IMPORTS", "SYNC"]}
      layout="wide"
      pageClass="lv-app--pixel-datasets"
    >
      <main className="lv-main lv-px-main">
        <div className="lv-px-stack">
          <PxHero
            title={DM_PAGE_COPY.title}
            subtitle={DM_PAGE_COPY.subtitle}
            quote={DM_PAGE_COPY.quote}
            pillars={DM_PAGE_COPY.pillars}
          />

          <div className="lv-px-kpi-row is-6">
            {DM_STATS.map((stat) => (
              <PxKpi
                key={stat.id}
                label={stat.label}
                value={stat.value}
                hint={
                  "hint" in stat
                    ? stat.hint
                    : "deltaSub" in stat && stat.deltaSub
                      ? `${stat.delta} ${stat.deltaSub}`
                      : undefined
                }
                hintTone={stat.tone === "cyan" ? "cyan" : stat.tone === "gold" ? "gold" : stat.tone === "green" ? "green" : stat.tone === "red" ? "red" : "muted"}
                icon={stat.icon}
                progress={"progress" in stat ? stat.progress : undefined}
              />
            ))}
          </div>

          <div className="lv-px-workspace">
            <aside className="lv-px-panel">
              <h2 className="lv-px-panel-title">Dataset Acties</h2>
              <p style={{ fontSize: 10, color: "var(--lv-text-muted)" }}>
                Geselecteerd: {selected ? "1 dataset" : "geen"}
              </p>
              <div className="lv-px-action-list" style={{ marginTop: 8 }}>
                {DM_ACTIONS.map((action) => (
                  <button
                    key={action.id}
                    type="button"
                    className={"danger" in action && action.danger ? "is-danger" : ""}
                    onClick={() => toast(action.toast)}
                  >
                    <PxIcon name={action.icon} />
                    <span>{action.label}</span>
                  </button>
                ))}
              </div>
            </aside>

            <section className="lv-px-panel">
              <div className="lv-px-panel-head">
                <h2 className="lv-px-panel-title">Dataset bibliotheek</h2>
                <span style={{ fontSize: 9, color: "var(--lv-text-muted)" }}>
                  {DM_TABLE_META.total} totaal · pagina {DM_TABLE_META.page}/{DM_TABLE_META.pageCount}
                </span>
              </div>
              <div className="lv-px-filters">
                <label className="lv-px-search">
                  <PxIcon name="search" />
                  <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Zoek..." aria-label="Zoek datasets" />
                </label>
                <select className="lv-px-select" value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
                  {DM_TYPE_FILTERS.map((f) => (
                    <option key={f} value={f}>{f}</option>
                  ))}
                </select>
                <select className="lv-px-select" value={sourceFilter} onChange={(e) => setSourceFilter(e.target.value)}>
                  {DM_SOURCE_FILTERS.map((f) => (
                    <option key={f} value={f}>{f}</option>
                  ))}
                </select>
                <select className="lv-px-select" value={splitFilter} onChange={(e) => setSplitFilter(e.target.value)}>
                  {DM_SPLIT_FILTERS.map((f) => (
                    <option key={f} value={f}>{f}</option>
                  ))}
                </select>
                <select className="lv-px-select" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
                  {DM_STATUS_FILTERS.map((f) => (
                    <option key={f} value={f}>{f}</option>
                  ))}
                </select>
              </div>
              <div className="lv-px-table-wrap">
                <table className="lv-px-table">
                  <thead>
                    <tr>
                      <th>Naam</th>
                      <th>Type</th>
                      <th>Bron</th>
                      <th>Split</th>
                      <th>Grootte</th>
                      <th>Tokens</th>
                      <th>Status</th>
                      <th>Tags</th>
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
                        <td><span className={`lv-px-pill is-${toneForType(row.typeTone)}`}>{row.type}</span></td>
                        <td>{row.source}</td>
                        <td>{row.split}</td>
                        <td>{row.size}</td>
                        <td>{row.tokens}</td>
                        <td><span className={`lv-px-pill is-${toneForStatus(row.status)}`}>{row.status}</span></td>
                        <td>
                          <div className="lv-px-pills">
                            {row.tags.map((t) => (
                              <span key={t} className="lv-px-pill">{t}</span>
                            ))}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>

            <aside className="lv-px-stack">
              <section className="lv-px-panel">
                <h2 className="lv-px-panel-title">Details</h2>
                {detail ? (
                  <>
                    <p style={{ fontSize: 11, color: "var(--lv-text-bright)", margin: "8px 0" }}>{detail.name}</p>
                    <p style={{ fontSize: 10, color: "var(--lv-text-secondary)" }}>{detail.description}</p>
                    <dl className="lv-px-meta-grid" style={{ marginTop: 8 }}>
                      <dt>Bron</dt>
                      <dd>{detail.source}</dd>
                      <dt>Type</dt>
                      <dd>{detail.type}</dd>
                      <dt>Locatie</dt>
                      <dd>{detail.location}</dd>
                      <dt>Versie</dt>
                      <dd>{detail.version}</dd>
                      <dt>Taal</dt>
                      <dd>{detail.language}</dd>
                      <dt>Licentie</dt>
                      <dd>{detail.license}</dd>
                    </dl>
                    <div className="lv-px-action-list" style={{ marginTop: 8 }}>
                      {DM_QUICK_ACTIONS.map((a) => (
                        <button key={a.id} type="button" onClick={() => toast(a.label)}>
                          <PxIcon name={a.icon} />
                          <span>{a.label}</span>
                        </button>
                      ))}
                    </div>
                  </>
                ) : (
                  <p style={{ fontSize: 10, color: "var(--lv-text-muted)" }}>Selecteer een dataset</p>
                )}
              </section>

              <section className="lv-px-panel">
                <div className="lv-px-tabs">
                  {DM_SAMPLE_TABS.map((t) => (
                    <button
                      key={t}
                      type="button"
                      className={`lv-px-tab${sampleTab === t ? " is-active" : ""}`}
                      onClick={() => setSampleTab(t)}
                    >
                      {t}
                    </button>
                  ))}
                </div>
                <pre className="lv-px-code" style={{ marginTop: 8 }}>{DM_SAMPLE_JSON}</pre>
              </section>

              <section className="lv-px-panel">
                <h2 className="lv-px-panel-title">Import jobs</h2>
                {DM_IMPORT_JOBS.map((job) => (
                  <div key={job.id} className="lv-px-queue-item">
                    <div className="lv-px-queue-top">
                      <strong>{job.dataset}</strong>
                      <span>{job.status}</span>
                    </div>
                    <div className="lv-px-progress">
                      <i style={{ width: `${job.progress}%` }} />
                    </div>
                    <div className="lv-px-queue-meta">
                      <span>{job.task}</span>
                      <span>{job.duration}</span>
                    </div>
                  </div>
                ))}
              </section>

              <section className="lv-px-panel">
                <h2 className="lv-px-panel-title">Opslag</h2>
                <p style={{ fontSize: 10 }}>
                  {DM_STORAGE_HEALTH.used} / {DM_STORAGE_HEALTH.total} ({DM_STORAGE_HEALTH.pct}%)
                </p>
                <div className="lv-px-progress is-thin">
                  <i style={{ width: `${DM_STORAGE_HEALTH.pct}%` }} />
                </div>
                <p style={{ fontSize: 9, color: "var(--lv-text-muted)", marginTop: 6 }}>
                  Dedupe {DM_STORAGE_HEALTH.dedupeSaved} · {DM_STORAGE_HEALTH.integrity}
                </p>
                <div className="lv-px-tag-cloud" style={{ marginTop: 8 }}>
                  {DM_TAG_CLOUD.map((t) => (
                    <span key={t.tag} className="lv-px-tag">
                      {t.tag} ({t.count})
                    </span>
                  ))}
                </div>
              </section>
            </aside>
          </div>

          <div className="lv-px-footer-bar">
            {DM_FOOTER_ACTIONS.map((a) => (
              <button
                key={a.id}
                type="button"
                className={`lv-px-btn${a.tone === "gold" ? " is-gold" : ""}${a.tone === "danger" ? " is-danger" : ""}`}
                onClick={() => toast(a.label)}
              >
                {a.label}
              </button>
            ))}
          </div>
        </div>
      </main>
    </AppShell>
  );
}
