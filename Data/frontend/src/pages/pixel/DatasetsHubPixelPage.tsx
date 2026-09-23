import { useMemo, useState } from "react";
import { AppShell } from "../../layouts/AppShell";
import {
  DSH_ACTIONS,
  DSH_FOOTER_STATS,
  DSH_PAGE_COPY,
  DSH_PIPELINE,
  DSH_QUICK_ACTIONS,
  DSH_RECENT_ACTIVITY,
  DSH_SIZE_FILTERS,
  DSH_SORT_OPTIONS,
  DSH_STATUS_FILTERS,
  DSH_STORAGE,
  DSH_TABLE_ROWS,
  DSH_TABS,
  DSH_TYPE_FILTERS,
  type DatasetsHubRow,
  type DatasetsHubStatus,
  type DatasetsHubTab,
} from "../../mocks/datasets-hub";
import { useAppToast } from "../../state/useAppToast";
import { donutSegments, PxHero, PxIcon } from "./pixel-shared";

function statusTone(status: DatasetsHubStatus) {
  if (status === "processed") return "green";
  if (status === "indexed") return "blue";
  if (status === "processing") return "gold";
  return "purple";
}

export function DatasetsHubPixelPage() {
  const toast = useAppToast();
  const [tab, setTab] = useState<DatasetsHubTab>("My Datasets");
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState<(typeof DSH_TYPE_FILTERS)[number]>(DSH_TYPE_FILTERS[0]);
  const [sizeFilter, setSizeFilter] = useState<(typeof DSH_SIZE_FILTERS)[number]>(DSH_SIZE_FILTERS[0]);
  const [statusFilter, setStatusFilter] = useState<(typeof DSH_STATUS_FILTERS)[number]>(DSH_STATUS_FILTERS[0]);
  const [sort, setSort] = useState<(typeof DSH_SORT_OPTIONS)[number]>(DSH_SORT_OPTIONS[0]);
  const [selectedId, setSelectedId] = useState(DSH_TABLE_ROWS[0]!.id);

  const storageDonut = useMemo(
    () =>
      donutSegments(
        DSH_STORAGE.segments.map((seg) => ({
          value: seg.pct,
          color: seg.color,
        })),
      ),
    [],
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return DSH_TABLE_ROWS.filter((row) => {
      if (typeFilter !== "All Types" && row.type !== typeFilter) return false;
      if (statusFilter !== "All Status" && row.statusLabel !== statusFilter) return false;
      if (sizeFilter === "< 10 GB") {
        const n = parseFloat(row.size);
        if (Number.isFinite(n) && n >= 10) return false;
      }
      if (sizeFilter === "10–50 GB") {
        const n = parseFloat(row.size);
        if (Number.isFinite(n) && (n < 10 || n > 50)) return false;
      }
      if (sizeFilter === "> 50 GB") {
        const n = parseFloat(row.size);
        if (Number.isFinite(n) && n <= 50) return false;
      }
      if (!q) return true;
      return (
        row.name.toLowerCase().includes(q) ||
        row.meta.toLowerCase().includes(q) ||
        row.type.toLowerCase().includes(q)
      );
    });
  }, [query, typeFilter, sizeFilter, statusFilter]);

  const selected = filtered.find((r) => r.id === selectedId) ?? DSH_TABLE_ROWS.find((r) => r.id === selectedId) ?? null;

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Research Datasets"
      searchPlaceholder="Search datasets, sources, tags..."
      systemItems={["DATASETS", "342 GB", "98% INDEX", "SYNC"]}
      layout="wide"
      pageClass="lv-app--pixel-research"
    >
      <main className="lv-main lv-px-main">
        <div className="lv-px-dsh-layout">
          <div className="lv-px-stack">
            <PxHero
              title={DSH_PAGE_COPY.title}
              subtitle={DSH_PAGE_COPY.subtitle}
              quote={DSH_PAGE_COPY.quote}
              pillars={DSH_PAGE_COPY.pillars}
            />

            <div className="lv-px-actions">
              {DSH_ACTIONS.map((action) => (
                <button key={action.id} type="button" className="lv-px-action" onClick={() => toast(action.toast)}>
                  <span className="lv-px-action-ico">
                    <PxIcon name={action.icon} />
                  </span>
                  <span className="lv-px-action-title">{action.title}</span>
                  <span className="lv-px-action-sub">{action.subtitle}</span>
                </button>
              ))}
            </div>

            <section className="lv-px-panel">
              <div className="lv-px-tabs" role="tablist">
                {DSH_TABS.map((item) => (
                  <button
                    key={item}
                    type="button"
                    role="tab"
                    aria-selected={tab === item}
                    className={`lv-px-tab${tab === item ? " is-active" : ""}`}
                    onClick={() => {
                      setTab(item);
                      toast(item);
                    }}
                  >
                    {item}
                  </button>
                ))}
              </div>

              <div className="lv-px-filters" style={{ marginTop: 8 }}>
                <label className="lv-px-search">
                  <PxIcon name="search" />
                  <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search datasets..." aria-label="Search datasets" />
                </label>
                <select className="lv-px-select" value={typeFilter} onChange={(e) => setTypeFilter(e.target.value as typeof typeFilter)}>
                  {DSH_TYPE_FILTERS.map((f) => (
                    <option key={f} value={f}>{f}</option>
                  ))}
                </select>
                <select className="lv-px-select" value={sizeFilter} onChange={(e) => setSizeFilter(e.target.value as typeof sizeFilter)}>
                  {DSH_SIZE_FILTERS.map((f) => (
                    <option key={f} value={f}>{f}</option>
                  ))}
                </select>
                <select className="lv-px-select" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as typeof statusFilter)}>
                  {DSH_STATUS_FILTERS.map((f) => (
                    <option key={f} value={f}>{f}</option>
                  ))}
                </select>
                <select className="lv-px-select" value={sort} onChange={(e) => setSort(e.target.value as typeof sort)}>
                  {DSH_SORT_OPTIONS.map((f) => (
                    <option key={f} value={f}>{f}</option>
                  ))}
                </select>
              </div>

              <div className="lv-px-table-wrap" style={{ marginTop: 8 }}>
                <table className="lv-px-table">
                  <thead>
                    <tr>
                      <th />
                      <th>Dataset</th>
                      <th>Type</th>
                      <th>Size</th>
                      <th>Samples</th>
                      <th>Status</th>
                      <th>Updated</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map((row) => (
                      <DatasetTableRow
                        key={row.id}
                        row={row}
                        active={row.id === selectedId}
                        onSelect={() => setSelectedId(row.id)}
                        onMenu={() => toast("Dataset actions")}
                      />
                    ))}
                  </tbody>
                </table>
              </div>
            </section>

            <section className="lv-px-panel">
              <h2 className="lv-px-panel-title">Processing pipeline</h2>
              <div className="lv-px-pipeline" style={{ marginTop: 8 }}>
                {DSH_PIPELINE.map((step) => (
                  <div key={step.id} className="lv-px-pipeline-card">
                    <PxIcon name={step.icon} />
                    <strong>{step.title}</strong>
                    <span>{step.detail}</span>
                  </div>
                ))}
              </div>
            </section>

            <footer className="lv-px-page-footer">
              <span>“{DSH_PAGE_COPY.footerQuote}” — {DSH_PAGE_COPY.footerAttribution}</span>
              <span>
                {DSH_FOOTER_STATS.map((s) => `${s.value} ${s.label}`).join(" · ")}
              </span>
            </footer>
          </div>

          <aside className="lv-px-rail">
            <section className="lv-px-rail-section">
              <h3 className="lv-px-rail-title">Selected dataset</h3>
              {selected ? (
                <>
                  <p style={{ fontSize: 11, color: "var(--lv-text-bright)" }}>{selected.name}</p>
                  <p style={{ fontSize: 10, color: "var(--lv-text-muted)" }}>{selected.meta}</p>
                  <div className="lv-px-pills" style={{ marginTop: 8 }}>
                    <span className={`lv-px-pill is-${selected.typeTone}`}>{selected.type}</span>
                    <span className={`lv-px-pill is-${statusTone(selected.status)}`}>{selected.statusLabel}</span>
                  </div>
                </>
              ) : (
                <p style={{ fontSize: 10, color: "var(--lv-text-muted)" }}>No selection</p>
              )}
            </section>

            <section className="lv-px-rail-section">
              <h3 className="lv-px-rail-title">Storage</h3>
              <p style={{ fontSize: 10 }}>
                {DSH_STORAGE.usedGb} GB / {DSH_STORAGE.totalTb} TB ({DSH_STORAGE.usedPct}%)
              </p>
              <div className="lv-px-donut-wrap" style={{ marginTop: 8 }}>
                <div className="lv-px-donut">
                  <svg viewBox="0 0 42 42" aria-hidden="true">
                    <circle cx="21" cy="21" r="14" fill="none" stroke="#223544" strokeWidth="5" />
                    {storageDonut.map((seg, index) => (
                      <circle
                        key={`${seg.color}-${index}`}
                        cx="21"
                        cy="21"
                        r="14"
                        fill="none"
                        stroke={seg.color}
                        strokeWidth="5"
                        strokeDasharray={seg.dash}
                        strokeDashoffset={seg.offset}
                        transform="rotate(-90 21 21)"
                      />
                    ))}
                  </svg>
                  <div className="lv-px-donut-center">
                    <strong>{DSH_STORAGE.usedPct}%</strong>
                    <span>used</span>
                  </div>
                </div>
                <ul className="lv-px-storage-legend">
                  {DSH_STORAGE.segments.map((seg) => (
                    <li key={seg.label}>
                      <i style={{ background: seg.color }} />
                      <span>{seg.label}</span>
                      <b>{seg.pct}%</b>
                    </li>
                  ))}
                </ul>
              </div>
            </section>

            <section className="lv-px-rail-section">
              <h3 className="lv-px-rail-title">Quick actions</h3>
              <div className="lv-px-action-list">
                {DSH_QUICK_ACTIONS.map((a) => (
                  <button key={a.id} type="button" onClick={() => toast(a.label)}>
                    <PxIcon name={a.icon} />
                    <span>{a.label}</span>
                  </button>
                ))}
              </div>
            </section>

            <section className="lv-px-rail-section">
              <h3 className="lv-px-rail-title">Recent activity</h3>
              {DSH_RECENT_ACTIVITY.map((a) => (
                <div key={a.id} className="lv-px-activity">
                  <PxIcon name={a.icon} />
                  <span>{a.text}</span>
                  <span className="lv-px-activity-when">{a.when}</span>
                </div>
              ))}
            </section>
          </aside>
        </div>
      </main>
    </AppShell>
  );
}

function DatasetTableRow({
  row,
  active,
  onSelect,
  onMenu,
}: {
  row: DatasetsHubRow;
  active: boolean;
  onSelect: () => void;
  onMenu: () => void;
}) {
  return (
    <tr className={active ? "is-active" : undefined} onClick={onSelect}>
      <td>
        <input type="checkbox" readOnly checked={active} aria-label={`Select ${row.name}`} />
      </td>
      <td>
        <div className="lv-px-cell-name">
          <PxIcon name={row.icon} />
          <span>
            <strong>{row.name}</strong>
            <div style={{ fontSize: 8, color: "var(--lv-text-muted)" }}>{row.meta}</div>
          </span>
        </div>
      </td>
      <td>
        <span className={`lv-px-pill is-${row.typeTone}`}>{row.type}</span>
      </td>
      <td>{row.size}</td>
      <td>{row.samples}</td>
      <td>
        <span className={`lv-px-pill is-${statusTone(row.status)}`}>{row.statusLabel}</span>
      </td>
      <td>{row.updated}</td>
      <td>
        <button
          type="button"
          className="lv-px-btn"
          aria-label="Actions"
          onClick={(e) => {
            e.stopPropagation();
            onMenu();
          }}
        >
          <PxIcon name="more" />
        </button>
      </td>
    </tr>
  );
}
