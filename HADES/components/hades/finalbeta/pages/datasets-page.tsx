/** FINALBETA Research Datasets hub — mock UI from datasets reference. */
"use client";

import { useMemo, useState } from "react";
import { donutSegments } from "../hooks/dashboard-live-utils";
import { FbIcon } from "../icons";
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
} from "../mocks/datasets-hub";
import { FinalBetaShell } from "../shell/finalbeta-shell";
import type { FinalBetaNavigate } from "../types";

type Props = { onNavigate: FinalBetaNavigate };

function statusTone(status: DatasetsHubStatus): string {
  if (status === "processed") return "green";
  if (status === "indexed") return "blue";
  if (status === "processing") return "gold";
  return "pink";
}

function StatusPill({ row }: { row: DatasetsHubRow }) {
  return (
    <span className={`dsh-status ${statusTone(row.status)}`}>
      <i />
      {row.statusLabel}
    </span>
  );
}

function DatasetRow({
  row,
  active,
  onSelect,
}: {
  row: DatasetsHubRow;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <tr className={active ? "active" : undefined} onClick={onSelect}>
      <td className="dsh-col-check">
        <input type="checkbox" readOnly checked={active} aria-label={`Select ${row.name}`} />
      </td>
      <td className="dsh-name">
        <span className="dsh-row-ico">
          <FbIcon name={row.icon} size={13} />
        </span>
        <span className="dsh-name-copy">
          <strong>{row.name}</strong>
          <small>{row.meta}</small>
        </span>
      </td>
      <td>
        <span className={`dsh-type-pill ${row.typeTone}`}>{row.type}</span>
      </td>
      <td>{row.size}</td>
      <td>{row.samples}</td>
      <td><StatusPill row={row} /></td>
      <td className="dsh-updated">{row.updated}</td>
      <td className="dsh-col-menu">
        <button type="button" aria-label="Actions" data-toast="Dataset actions" onClick={(e) => e.stopPropagation()}>
          <FbIcon name="more" size={14} />
        </button>
      </td>
    </tr>
  );
}

export function DatasetsPage({ onNavigate }: Props) {
  const [tab, setTab] = useState<DatasetsHubTab>("My Datasets");
  const [query, setQuery] = useState("");
  const [view, setView] = useState<"list" | "grid">("list");
  const [typeFilter, setTypeFilter] = useState<(typeof DSH_TYPE_FILTERS)[number]>(DSH_TYPE_FILTERS[0]);
  const [sizeFilter, setSizeFilter] = useState<(typeof DSH_SIZE_FILTERS)[number]>(DSH_SIZE_FILTERS[0]);
  const [statusFilter, setStatusFilter] = useState<(typeof DSH_STATUS_FILTERS)[number]>(DSH_STATUS_FILTERS[0]);
  const [sort, setSort] = useState<(typeof DSH_SORT_OPTIONS)[number]>(DSH_SORT_OPTIONS[0]);
  const [selectedId, setSelectedId] = useState(DSH_TABLE_ROWS[0]!.id);

  const storageDonut = useMemo(
    () =>
      donutSegments(
        DSH_STORAGE.segments.map((seg) => ({
          label: seg.label,
          count: seg.pct,
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

  const body = (
    <div className="dsh-page">
      <header className="dsh-hero">
        <div className="dsh-hero-grid">
          <div className="dsh-hero-copy">
            <h1>{DSH_PAGE_COPY.title}</h1>
            <p className="dsh-hero-tag">{DSH_PAGE_COPY.subtitle}</p>
            <p className="dsh-hero-quote-inline">“{DSH_PAGE_COPY.quote}”</p>
          </div>
          <div className="dsh-hero-pillars" aria-hidden="true">
            {DSH_PAGE_COPY.pillars.map((line) => (
              <span key={line}>{line}</span>
            ))}
          </div>
        </div>
      </header>

      <div className="dsh-actions">
        {DSH_ACTIONS.map((action) => (
          <button key={action.id} type="button" className="dsh-action" data-toast={action.toast}>
            <span className="dsh-action-ico">
              <FbIcon name={action.icon} size={16} />
            </span>
            <span className="dsh-action-title">{action.title}</span>
            <span className="dsh-action-sub">{action.subtitle}</span>
          </button>
        ))}
      </div>

      <section className="dsh-library card">
        <div className="dsh-tabs" role="tablist">
          {DSH_TABS.map((item) => (
            <button
              key={item}
              type="button"
              role="tab"
              aria-selected={tab === item}
              className={`dsh-tab${tab === item ? " active" : ""}`}
              onClick={() => setTab(item)}
              data-toast={item}
            >
              {item}
            </button>
          ))}
        </div>

        <div className="dsh-toolbar">
          <label className="dsh-search">
            <FbIcon name="search" size={14} />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search datasets..."
              aria-label="Search datasets"
            />
          </label>
          <select
            className="dsh-select"
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value as (typeof DSH_TYPE_FILTERS)[number])}
            aria-label="Type filter"
          >
            {DSH_TYPE_FILTERS.map((opt) => (
              <option key={opt} value={opt}>{opt}</option>
            ))}
          </select>
          <select
            className="dsh-select"
            value={sizeFilter}
            onChange={(e) => setSizeFilter(e.target.value as (typeof DSH_SIZE_FILTERS)[number])}
            aria-label="Size filter"
          >
            {DSH_SIZE_FILTERS.map((opt) => (
              <option key={opt} value={opt}>{opt}</option>
            ))}
          </select>
          <select
            className="dsh-select"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as (typeof DSH_STATUS_FILTERS)[number])}
            aria-label="Status filter"
          >
            {DSH_STATUS_FILTERS.map((opt) => (
              <option key={opt} value={opt}>{opt}</option>
            ))}
          </select>
          <select
            className="dsh-select"
            value={sort}
            onChange={(e) => setSort(e.target.value as (typeof DSH_SORT_OPTIONS)[number])}
            aria-label="Sort"
          >
            {DSH_SORT_OPTIONS.map((opt) => (
              <option key={opt} value={opt}>{opt}</option>
            ))}
          </select>
          <div className="dsh-view-toggle" role="group" aria-label="View mode">
            <button
              type="button"
              className={view === "list" ? "active" : ""}
              onClick={() => setView("list")}
              aria-label="List view"
              data-toast="List view"
            >
              <FbIcon name="list" size={14} />
            </button>
            <button
              type="button"
              className={view === "grid" ? "active" : ""}
              onClick={() => setView("grid")}
              aria-label="Grid view"
              data-toast="Grid view"
            >
              <FbIcon name="grid" size={14} />
            </button>
          </div>
        </div>

        {view === "list" ? (
          <div className="dsh-table-wrap">
            <table className="dsh-table">
              <thead>
                <tr>
                  <th className="dsh-col-check" aria-label="Select" />
                  <th>Name</th>
                  <th>Type</th>
                  <th>Size</th>
                  <th>Samples</th>
                  <th>Status</th>
                  <th>Last Updated</th>
                  <th className="dsh-col-menu" aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {filtered.map((row) => (
                  <DatasetRow
                    key={row.id}
                    row={row}
                    active={selectedId === row.id}
                    onSelect={() => setSelectedId(row.id)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="dsh-card-grid">
            {filtered.map((row) => (
              <button
                key={row.id}
                type="button"
                className={`dsh-dataset-card${selectedId === row.id ? " active" : ""}`}
                onClick={() => setSelectedId(row.id)}
              >
                <span className="dsh-dataset-card-top">
                  <FbIcon name={row.icon} size={14} />
                  <strong>{row.name}</strong>
                </span>
                <span className="dsh-dataset-card-meta">{row.meta}</span>
                <span className="dsh-dataset-card-foot">
                  <span className={`dsh-type-pill ${row.typeTone}`}>{row.type}</span>
                  <StatusPill row={row} />
                </span>
              </button>
            ))}
          </div>
        )}
      </section>

      <footer className="dsh-stats-bar">
        <div className="dsh-stats-quote">
          <span className="dsh-stats-bust" aria-hidden="true">
            <FbIcon name="user" size={18} />
          </span>
          <p>
            “{DSH_PAGE_COPY.footerQuote}”
            <cite>— {DSH_PAGE_COPY.footerAttribution}</cite>
          </p>
        </div>
        <div className="dsh-stats-blocks">
          {DSH_FOOTER_STATS.map((stat) => (
            <div key={stat.id} className="dsh-stat-block">
              <strong>{stat.value}</strong>
              <span>{stat.label}</span>
            </div>
          ))}
        </div>
      </footer>
    </div>
  );

  const inspector = (
    <>
      <section className="insp-section dsh-insp">
        <h3 className="insp-title">Dataset Storage</h3>
        <div className="insp-card dsh-storage-card">
          <p className="dsh-storage-summary">
            Total Usage: <strong>{DSH_STORAGE.usedGb} GB</strong> / {DSH_STORAGE.totalTb} TB
          </p>
          <div className="dsh-storage-bar" aria-hidden="true">
            <i style={{ width: `${DSH_STORAGE.usedPct}%` }} />
          </div>
          <div className="dsh-donut-wrap">
            <svg viewBox="0 0 42 42" className="dsh-donut" aria-hidden="true">
              <circle cx="21" cy="21" r="14" fill="none" stroke="rgba(58, 199, 238, 0.12)" strokeWidth="5" />
              {storageDonut.map((seg, index) => (
                <circle
                  key={DSH_STORAGE.segments[index]!.label}
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
            <ul className="dsh-donut-legend">
              {DSH_STORAGE.segments.map((seg) => (
                <li key={seg.label}>
                  <i style={{ background: seg.color }} />
                  <span>{seg.label}</span>
                  <b>{seg.pct}%</b>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      <section className="insp-section dsh-insp">
        <h3 className="insp-title">Data Processing</h3>
        <div className="insp-card dsh-pipeline">
          <ul>
            {DSH_PIPELINE.map((step) => (
              <li key={step.id} className={`dsh-pipeline-row ${step.tone}`}>
                <span className="dsh-pipeline-ico">
                  <FbIcon name={step.icon} size={14} />
                </span>
                <div>
                  <strong>{step.title}</strong>
                  <span>{step.detail}</span>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section className="insp-section dsh-insp">
        <h3 className="insp-title">Quick Actions</h3>
        <div className="dsh-quick-grid">
          {DSH_QUICK_ACTIONS.map((action) => (
            <button key={action.id} type="button" className="dsh-quick-btn" data-toast={action.label}>
              <FbIcon name={action.icon} size={15} />
              <span>{action.label}</span>
            </button>
          ))}
        </div>
      </section>

      <section className="insp-section dsh-insp">
        <h3 className="insp-title">Recent Activity</h3>
        <div className="insp-card dsh-activity">
          <ul>
            {DSH_RECENT_ACTIVITY.map((item) => (
              <li key={item.id}>
                <span className={`dsh-activity-ico ${item.tone}`}>
                  <FbIcon name={item.icon} size={12} />
                </span>
                <div className="dsh-activity-copy">
                  <span>{item.text}</span>
                  <time>{item.when}</time>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </section>

      {selected ? (
        <section className="insp-section dsh-insp">
          <h3 className="insp-title">Selection</h3>
          <div className="insp-card">
            <div className="detail-row">
              <span className="k">Dataset</span>
              <span className="v">{selected.name}</span>
            </div>
            <div className="detail-row">
              <span className="k">Type</span>
              <span className="v">{selected.type}</span>
            </div>
            <div className="detail-row">
              <span className="k">Size</span>
              <span className="v">{selected.size}</span>
            </div>
            <button
              type="button"
              className="btn btn-sm btn-outline btn-block"
              style={{ marginTop: 8 }}
              onClick={() => onNavigate("knowledge")}
              data-toast="Open in Knowledge"
            >
              Knowledge Library
            </button>
          </div>
        </section>
      ) : null}
    </>
  );

  const footer = (
    <footer className="dash-footer dsh-footer">
      <span>HADES FINALBETA v0.9.0&nbsp;&nbsp;|&nbsp;&nbsp;Datasets Hub</span>
      <span className="motto">
        FUEL INTELLIGENCE. <b>━━</b>
      </span>
    </footer>
  );

  return (
    <FinalBetaShell
      page="datasets"
      body={body}
      inspector={inspector}
      onNavigate={onNavigate}
      appClassName="dsh-app"
      mainClassName="dsh-main"
      footer={footer}
    />
  );
}
