import { Button } from "../ui";
import type { ToolsLibraryItem } from "../../types/api";
import type { ToolsSortKey } from "../../pages/tools/useToolsWorkspace";

type Props = {
  rows: ToolsLibraryItem[];
  total: number;
  selectedId: string | null;
  onSelect: (id: string) => void;
  query: string;
  onQuery: (v: string) => void;
  category: string;
  onCategory: (v: string) => void;
  source: string;
  onSource: (v: string) => void;
  sort: ToolsSortKey;
  onSort: (v: ToolsSortKey) => void;
  categories: Array<{ key: string; label: string }>;
  loading?: boolean;
  onNewTool: () => void;
  onCopyId: (id: string) => void;
  onOpenLogs: (id: string) => void;
  onTest: (id: string) => void;
};

function relativeTime(iso?: string | null): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "—";
  const frozen =
    typeof window !== "undefined"
      ? (window as Window & { __LV_V2_FROZEN_NOW__?: string }).__LV_V2_FROZEN_NOW__
      : undefined;
  const now = frozen ? Date.parse(frozen) : Date.now();
  const diff = Math.max(0, now - t);
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "zojuist";
  if (mins < 60) return `${mins}m geleden`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}u geleden`;
  const days = Math.floor(hrs / 24);
  return `${days}d geleden`;
}

function statusClass(status?: string): string {
  if (status === "active") return "is-active";
  if (status === "inactive") return "is-inactive";
  return "is-unavailable";
}

const SOURCES = [
  { id: "all", label: "Alle bronnen" },
  { id: "core", label: "Core" },
  { id: "plugin", label: "Plugin" },
  { id: "mcp", label: "MCP" },
  { id: "function", label: "Function" },
  { id: "module", label: "Module" },
  { id: "custom", label: "Custom" },
  { id: "external", label: "External" },
];

export function ToolsLibrary({
  rows,
  total,
  selectedId,
  onSelect,
  query,
  onQuery,
  category,
  onCategory,
  source,
  onSource,
  sort,
  onSort,
  categories,
  loading,
  onNewTool,
  onCopyId,
  onOpenLogs,
  onTest,
}: Props) {
  return (
    <section className="lv-v2-tools-library" aria-label="Tools Bibliotheek">
      <header className="lv-v2-tools-panel__head">
        <div>
          <h3>Tools Bibliotheek</h3>
          <p className="lv-muted">{total} tools</p>
        </div>
        <Button variant="primary" size="sm" onClick={onNewTool}>
          + Nieuwe tool
        </Button>
      </header>

      <div className="lv-v2-tools-library__filters">
        <input
          className="lv-v2-input"
          value={query}
          onChange={(e) => onQuery(e.target.value)}
          placeholder="Zoek tools..."
          aria-label="Zoek tools in bibliotheek"
        />
        <select
          className="lv-v2-select"
          value={category}
          onChange={(e) => onCategory(e.target.value)}
          aria-label="Filter categorieën"
        >
          <option value="all">Alle categorieën</option>
          {categories.map((c) => (
            <option key={c.key} value={c.key}>
              {c.label}
            </option>
          ))}
        </select>
        <select
          className="lv-v2-select"
          value={source}
          onChange={(e) => onSource(e.target.value)}
          aria-label="Filter bronnen"
        >
          {SOURCES.map((s) => (
            <option key={s.id} value={s.id}>
              {s.label}
            </option>
          ))}
        </select>
        <select
          className="lv-v2-select"
          value={sort}
          onChange={(e) => onSort(e.target.value as ToolsSortKey)}
          aria-label="Sorteer tools"
        >
          <option value="name">Naam</option>
          <option value="category">Categorie</option>
          <option value="source">Bron</option>
          <option value="status">Status</option>
          <option value="version">Versie</option>
          <option value="-last_used">Laatst gebruikt</option>
        </select>
      </div>

      <div className="lv-v2-tools-table-wrap">
        <table className="lv-v2-tools-table">
          <thead>
            <tr>
              <th>Naam</th>
              <th>Categorie</th>
              <th>Bron</th>
              <th>Status</th>
              <th>Versie</th>
              <th>Laatst gebruikt</th>
              <th aria-label="Acties" />
            </tr>
          </thead>
          <tbody>
            {loading && rows.length === 0 ? (
              <tr>
                <td colSpan={7}>Tools laden…</td>
              </tr>
            ) : null}
            {!loading && rows.length === 0 ? (
              <tr>
                <td colSpan={7}>Geen tools gevonden.</td>
              </tr>
            ) : null}
            {rows.map((row) => (
              <tr
                key={row.id}
                className={selectedId === row.id ? "is-selected" : undefined}
                onClick={() => onSelect(row.id)}
              >
                <td>
                  <div className="lv-v2-tools-name">
                    <span className="lv-v2-tools-name__icon" aria-hidden="true">
                      ⚙
                    </span>
                    <strong title={row.id}>{row.name}</strong>
                  </div>
                </td>
                <td>
                  <span className={`lv-v2-tools-chip lv-v2-tools-chip--cat`}>{row.category_label ?? "Overig"}</span>
                </td>
                <td>
                  <span className={`lv-v2-tools-chip lv-v2-tools-chip--src`}>{row.source_label ?? "—"}</span>
                </td>
                <td>
                  <span className={`lv-v2-tools-status ${statusClass(row.status)}`}>
                    <i />
                    {row.status_label ?? "—"}
                  </span>
                </td>
                <td>{row.version ?? "—"}</td>
                <td>{relativeTime(row.last_used_at)}</td>
                <td>
                  <details className="lv-v2-tools-overflow" onClick={(e) => e.stopPropagation()}>
                    <summary aria-label={`Acties voor ${row.name}`}>⋯</summary>
                    <div className="lv-v2-tools-overflow__menu" role="menu">
                      <button type="button" role="menuitem" onClick={() => onTest(row.id)}>
                        Testen
                      </button>
                      <button type="button" role="menuitem" onClick={() => onCopyId(row.id)}>
                        Kopieer ID
                      </button>
                      <button type="button" role="menuitem" onClick={() => onOpenLogs(row.id)}>
                        Bekijk logs
                      </button>
                    </div>
                  </details>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
