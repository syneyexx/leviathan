import {
  ALL_ENVIRONMENTS,
  ALL_MODELS,
  ALL_ROLES,
  ALL_STATUS,
  ALL_TEAMS,
  isDefaultDashboardFilters,
  type DashboardFilters,
} from "./helpers";

type Options = {
  teams: string[];
  statuses: string[];
  roles: string[];
  models: string[];
  environments: string[];
};

function FilterSelect({
  label,
  value,
  allLabel,
  options,
  onChange,
}: {
  label: string;
  value: string;
  allLabel: string;
  options: string[];
  onChange: (v: string) => void;
}) {
  return (
    <label className="lv-ag-filter">
      <span>{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)} aria-label={`Filter by ${label}`}>
        <option value={allLabel}>{allLabel}</option>
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </label>
  );
}

export function AgentsToolbar({
  busy,
  filters,
  options,
  architectureView,
  onFilters,
  onNewAgent,
  onSpawnWorker,
  onStartAll,
  onPauseAll,
  onToggleArchitecture,
  onReconcile,
  onRefresh,
  onTradeOrchestra,
}: {
  busy: boolean;
  filters: DashboardFilters;
  options: Options;
  architectureView: boolean;
  onFilters: (next: DashboardFilters) => void;
  onNewAgent: () => void;
  onSpawnWorker: () => void;
  onStartAll: () => void;
  onPauseAll: () => void;
  onToggleArchitecture: () => void;
  onReconcile: () => void;
  onRefresh: () => void;
  onTradeOrchestra: () => void;
}) {
  const set = (patch: Partial<DashboardFilters>) => onFilters({ ...filters, ...patch });
  return (
    <section className="lv-ag-toolbar" aria-label="Agent fleet controls">
      <div className="lv-ag-toolbar-actions">
        <button type="button" className="lv-ag-tb-btn is-gold" disabled={busy} onClick={onNewAgent}>
          <b>+</b> New Agent
        </button>
        <button type="button" className="lv-ag-tb-btn" disabled={busy} onClick={onSpawnWorker}>
          <b>⚙</b> Spawn Worker
        </button>
        <button
          type="button"
          className="lv-ag-tb-btn"
          disabled={busy}
          onClick={onStartAll}
          title="Enable all USER fleet agents (SYSTEM agents are protected)"
        >
          <b>▶</b> Start All
        </button>
        <button
          type="button"
          className="lv-ag-tb-btn"
          disabled={busy}
          onClick={onPauseAll}
          title="Disable all USER fleet agents (SYSTEM agents are protected)"
        >
          <b>❚❚</b> Pause All
        </button>
        <button
          type="button"
          className={`lv-ag-tb-btn${architectureView ? " is-active" : ""}`}
          onClick={onToggleArchitecture}
          aria-pressed={architectureView}
        >
          <b>⌬</b> Architecture View
        </button>
        <span className="lv-ag-toolbar-sep" aria-hidden="true" />
        <button
          type="button"
          className="lv-ag-tb-btn is-sm"
          disabled={busy}
          onClick={onReconcile}
          title="Mark orphaned active missions interrupted"
        >
          Reconcile
        </button>
        <button type="button" className="lv-ag-tb-btn is-sm" onClick={onTradeOrchestra}>
          Trade Orchestra
        </button>
        <button type="button" className="lv-ag-tb-btn is-sm" disabled={busy} onClick={onRefresh}>
          Refresh
        </button>
      </div>
      <div className="lv-ag-toolbar-filters">
        <FilterSelect label="Team" value={filters.team} allLabel={ALL_TEAMS} options={options.teams} onChange={(v) => set({ team: v })} />
        <FilterSelect label="Status" value={filters.status} allLabel={ALL_STATUS} options={options.statuses} onChange={(v) => set({ status: v })} />
        <FilterSelect label="Role" value={filters.role} allLabel={ALL_ROLES} options={options.roles} onChange={(v) => set({ role: v })} />
        <FilterSelect label="Model" value={filters.model} allLabel={ALL_MODELS} options={options.models} onChange={(v) => set({ model: v })} />
        <FilterSelect
          label="Environment"
          value={filters.environment}
          allLabel={ALL_ENVIRONMENTS}
          options={options.environments}
          onChange={(v) => set({ environment: v })}
        />
        {!isDefaultDashboardFilters(filters) ? (
          <button
            type="button"
            className="lv-ag-btn-ghost is-xs"
            onClick={() =>
              onFilters({
                team: ALL_TEAMS,
                status: ALL_STATUS,
                role: ALL_ROLES,
                model: ALL_MODELS,
                environment: ALL_ENVIRONMENTS,
                query: "",
              })
            }
          >
            Clear
          </button>
        ) : null}
      </div>
    </section>
  );
}
