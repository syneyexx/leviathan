import { Badge, Button } from "../ui";
import {
  moduleDescription,
  moduleId,
  moduleName,
  moduleVersion,
  statusTone,
  type ManagedModuleRow,
  type ModuleFilterId,
  type StatusTone,
} from "../../pages/plugin-runtime/modules/viewModels";
import { IconModule, IconRefresh, IconSearch } from "./ModulesIcons";

type Props = {
  rows: ManagedModuleRow[];
  selectedId: string | null;
  query: string;
  onQuery: (q: string) => void;
  filter: ModuleFilterId;
  onFilter: (f: ModuleFilterId) => void;
  counts: Record<ModuleFilterId, number>;
  loading: boolean;
  discovering: boolean;
  managerEnabled: boolean;
  loadError: string | null;
  onSelect: (id: string) => void;
  onDiscover: () => void;
  onRefresh: () => void;
  onSweepIdle?: () => void;
  lifecycleBusy?: boolean;
};

function badgeTone(tone: StatusTone): "success" | "warning" | "danger" | "info" | "muted" | "trading" {
  if (tone === "ok") return "success";
  if (tone === "warn") return "warning";
  if (tone === "err") return "danger";
  if (tone === "cyan") return "info";
  if (tone === "gold") return "trading";
  return "muted";
}

function tagsOf(row: ManagedModuleRow): string[] {
  const meta = row.manifest?.metadata;
  if (!meta || typeof meta !== "object") return [];
  const tags = (meta as Record<string, unknown>).tags;
  if (!Array.isArray(tags)) return [];
  return tags.map(String).filter(Boolean).slice(0, 4);
}

const FILTERS: { id: ModuleFilterId; label: string }[] = [
  { id: "all", label: "Alle" },
  { id: "installed", label: "Geïnstalleerd" },
  { id: "not_installed", label: "Niet geïnstalleerd" },
  { id: "updates", label: "Updates" },
];

export function ModulesLibrary({
  rows,
  selectedId,
  query,
  onQuery,
  filter,
  onFilter,
  counts,
  loading,
  discovering,
  managerEnabled,
  loadError,
  onSelect,
  onDiscover,
  onRefresh,
  onSweepIdle,
  lifecycleBusy = false,
}: Props) {
  return (
    <section className="lv-v2-modules-library" aria-label="Module bibliotheek">
      <div className="lv-v2-modules-library__head">
        <h3 className="lv-v2-modules-library__title">Modules</h3>
        <div className="lv-v2-modules-library__actions">
          <Button
            variant="secondary"
            size="sm"
            disabled={discovering || !managerEnabled}
            title={managerEnabled ? "POST /api/modules/discover" : "Module manager feature flag OFF"}
            loading={discovering}
            onClick={onDiscover}
          >
            Discover
          </Button>
          {onSweepIdle ? (
            <Button
              variant="ghost"
              size="sm"
              disabled={!managerEnabled || lifecycleBusy || discovering}
              title="Stop idle modules (POST /api/modules/sweep-idle)"
              onClick={onSweepIdle}
            >
              Sweep Idle
            </Button>
          ) : null}
          <Button
            variant="ghost"
            size="sm"
            disabled={loading || discovering}
            title="Snapshot vernieuwen"
            onClick={onRefresh}
            aria-label="Refresh"
          >
            <IconRefresh className="lv-v2-modules-icon" />
            Refresh
          </Button>
        </div>
      </div>

      <label className="lv-v2-modules-search">
        <IconSearch className="lv-v2-modules-icon" />
        <input
          value={query}
          onChange={(e) => onQuery(e.target.value)}
          placeholder="Zoek modules, tools of capabilities..."
          aria-label="Zoek modules"
        />
      </label>

      <div className="lv-v2-modules-filters" role="tablist" aria-label="Module filters">
        {FILTERS.map((f) => {
          const count = counts[f.id] ?? 0;
          const active = filter === f.id;
          return (
            <button
              key={f.id}
              type="button"
              role="tab"
              aria-selected={active}
              className={`lv-v2-chip${active ? " is-on" : ""}`}
              onClick={() => onFilter(f.id)}
              title={
                f.id === "updates" && count === 0
                  ? "Updates filter gebruikt alleen check-update evidence"
                  : undefined
              }
            >
              {f.label}{" "}
              <span className={`lv-v2-modules-filters__count${f.id === "updates" && count > 0 ? " is-alert" : ""}`}>
                {count}
              </span>
            </button>
          );
        })}
      </div>

      <div className="lv-v2-modules-rows">
        {loading && rows.length === 0 ? (
          <>
            <div className="lv-v2-skeleton lv-v2-modules-skel" />
            <div className="lv-v2-skeleton lv-v2-modules-skel" />
            <div className="lv-v2-skeleton lv-v2-modules-skel" />
          </>
        ) : null}
        {!loading && rows.length === 0 ? (
          <div className="lv-v2-modules-empty">
            {loadError
              ? "Module snapshot unavailable — fix backend/API, then Refresh."
              : !managerEnabled
                ? "Manager OFF — lege lijst is truthful."
                : "Geen modules in snapshot. Gebruik Discover om discovery roots te scannen."}
          </div>
        ) : null}
        {rows.map((row) => {
          const id = moduleId(row);
          const selected = selectedId === id;
          const tone = statusTone(row.status);
          const desc = moduleDescription(row) || row.adapter || "—";
          const ver = moduleVersion(row);
          const tags = tagsOf(row);
          return (
            <button
              key={id}
              type="button"
              className={`lv-v2-modules-row${selected ? " is-selected" : ""}`}
              onClick={() => onSelect(id)}
              aria-pressed={selected}
            >
              <div className="lv-v2-modules-row__icon" aria-hidden="true">
                <IconModule />
              </div>
              <div className="lv-v2-modules-row__body">
                <div className="lv-v2-modules-row__top">
                  <span className="lv-v2-modules-row__name">{moduleName(row)}</span>
                  <span className="lv-v2-modules-row__ver">{ver ? `v${ver}` : "—"}</span>
                  <Badge tone={badgeTone(tone)}>{(row.status ?? "—").toUpperCase()}</Badge>
                </div>
                <p className="lv-v2-modules-row__desc" title={desc}>
                  {desc}
                </p>
                {tags.length ? (
                  <div className="lv-v2-modules-row__tags">
                    {tags.map((t) => (
                      <span key={t} className="lv-v2-modules-tag">
                        {t}
                      </span>
                    ))}
                  </div>
                ) : null}
              </div>
            </button>
          );
        })}
      </div>
    </section>
  );
}
