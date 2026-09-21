import type { KeyboardEvent } from "react";
import type { FilterKey, SortKey } from "./types";
import type { ModelDescriptor, ModelProvider } from "../../types/api";

function dash(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

export function ModelCatalog({
  rows,
  selectedId,
  query,
  filter,
  sort,
  providerFilters,
  onQuery,
  onFilter,
  onSort,
  onSelect,
  onActivate,
  onLoad,
  onUnload,
  providers,
  busy,
}: {
  rows: ModelDescriptor[];
  selectedId: string | null;
  query: string;
  filter: FilterKey;
  sort: SortKey;
  providerFilters: string[];
  onQuery: (q: string) => void;
  onFilter: (f: FilterKey) => void;
  onSort: (s: SortKey) => void;
  onSelect: (id: string) => void;
  onActivate: (id: string) => void;
  onLoad: (id: string) => void;
  onUnload: (id: string) => void;
  providers: ModelProvider[];
  busy: boolean;
}) {
  const filters: { key: FilterKey; label: string }[] = [
    { key: "all", label: "All" },
    { key: "local", label: "Local" },
    { key: "remote", label: "Remote" },
    { key: "api", label: "API" },
    { key: "loaded", label: "Loaded" },
    { key: "available", label: "Available" },
    { key: "active", label: "Active" },
    { key: "offline", label: "Offline" },
    { key: "error", label: "Error" },
    ...providerFilters.map((t) => ({ key: t as FilterKey, label: t })),
  ];

  function onKeyNav(event: KeyboardEvent<HTMLTableSectionElement>) {
    if (!rows.length) return;
    const idx = rows.findIndex((r) => r.id === selectedId);
    if (event.key === "ArrowDown") {
      event.preventDefault();
      const next = rows[Math.min(rows.length - 1, Math.max(0, idx) + 1)];
      onSelect(next.id);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      const prev = rows[Math.max(0, idx - 1)];
      onSelect(prev.id);
    } else if (event.key === "Enter" && selectedId) {
      event.preventDefault();
      onActivate(selectedId);
    }
  }

  function capsFor(providerId: string) {
    return providers.find((p) => p.id === providerId)?.capabilities;
  }

  return (
    <section className="lv-models-catalog">
      <div className="lv-toolbar lv-models-toolbar">
        <input
          className="lv-input"
          style={{ minWidth: 220, flex: 1 }}
          value={query}
          onChange={(e) => onQuery(e.target.value)}
          placeholder="Search id, name, provider, family…"
          aria-label="Search models"
        />
        <select
          className="lv-select"
          value={filter}
          onChange={(e) => onFilter(e.target.value as FilterKey)}
          aria-label="Filter"
        >
          {filters.map((f) => (
            <option key={f.key} value={f.key}>
              {f.label}
            </option>
          ))}
        </select>
        <select
          className="lv-select"
          value={sort}
          onChange={(e) => onSort(e.target.value as SortKey)}
          aria-label="Sort"
        >
          <option value="name">Name</option>
          <option value="provider">Provider</option>
          <option value="recent">Recently Used</option>
          <option value="size">Size</option>
          <option value="parameters">Parameters</option>
          <option value="context">Context</option>
          <option value="status">Status</option>
        </select>
      </div>

      <div className="lv-models-table-wrap">
        <table className="lv-models-table" role="grid">
          <thead>
            <tr>
              <th>Model</th>
              <th>Provider</th>
              <th>Runtime</th>
              <th>Format</th>
              <th>Size</th>
              <th>Context</th>
              <th>Capabilities</th>
              <th>Lifecycle</th>
              <th>Health</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody tabIndex={0} onKeyDown={onKeyNav}>
            {rows.map((model) => {
              const caps = capsFor(model.providerId);
              const isSelected = model.id === selectedId;
              return (
                <tr
                  key={model.id}
                  className={isSelected ? "is-selected" : undefined}
                  onClick={() => onSelect(model.id)}
                  aria-selected={isSelected}
                >
                  <td>
                    <div className="lv-model-name">
                      <strong>
                        {model.displayName}
                        {model.active ? <span className="lv-tag gold">ACTIVE</span> : null}
                        {isSelected && !model.active ? <span className="lv-tag">SELECTED</span> : null}
                      </strong>
                      <small>{model.id}</small>
                    </div>
                  </td>
                  <td>{model.providerId}</td>
                  <td>{dash(model.runtimeId)}</td>
                  <td>{dash(model.format)}</td>
                  <td>{formatBytes(model.diskSizeBytes)}</td>
                  <td>{dash(model.contextWindow)}</td>
                  <td>
                    <span className="lv-cap-chips">
                      {model.capabilities.streaming !== "unsupported" ? "stream" : null}
                      {model.capabilities.chat !== "unsupported" ? " chat" : null}
                    </span>
                  </td>
                  <td>
                    <span className={`lv-lifecycle lv-lifecycle--${model.lifecycleState}`}>
                      {model.lifecycleState}
                    </span>
                  </td>
                  <td>
                    <span className={`lv-health lv-health--${model.health}`}>{model.health}</span>
                  </td>
                  <td>
                    <div className="lv-row-actions" onClick={(e) => e.stopPropagation()}>
                      {!model.active ? (
                        <button
                          className="lv-btn lv-btn-gold"
                          type="button"
                          disabled={busy}
                          onClick={() => onActivate(model.id)}
                        >
                          Activate
                        </button>
                      ) : null}
                      {caps?.loadModel ? (
                        <button className="lv-btn" type="button" disabled={busy} onClick={() => onLoad(model.id)}>
                          Load
                        </button>
                      ) : null}
                      {caps?.unloadModel ? (
                        <button className="lv-btn" type="button" disabled={busy} onClick={() => onUnload(model.id)}>
                          Unload
                        </button>
                      ) : caps && !caps.loadModel && !caps.unloadModel ? (
                        <span className="lv-muted" title="Managed externally">
                          Ext.
                        </span>
                      ) : null}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
