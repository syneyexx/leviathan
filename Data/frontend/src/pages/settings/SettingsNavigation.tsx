import type { SettingsCategory } from "../../types/api";

type Props = {
  categories: SettingsCategory[];
  activeId: string;
  onSelect: (id: string) => void;
  query: string;
  onQueryChange: (value: string) => void;
};

export function SettingsNavigation({ categories, activeId, onSelect, query, onQueryChange }: Props) {
  return (
    <aside className="lv-panel lv-settings-nav">
      <div className="lv-form-field" style={{ marginBottom: 8 }}>
        <label htmlFor="settings-search">Search</label>
        <input
          id="settings-search"
          className="lv-input"
          style={{ width: "100%" }}
          value={query}
          placeholder="Filter settings…"
          onChange={(event) => onQueryChange(event.target.value)}
        />
      </div>
      {categories.map((item) => (
        <button
          key={item.id}
          className={`lv-settings-nav-item${item.id === activeId ? " is-active" : ""}`}
          type="button"
          onClick={() => onSelect(item.id)}
        >
          <strong>{item.label}</strong>
          <small>
            {item.description}
            {item.setting_count ? ` · ${item.setting_count}` : ""}
          </small>
        </button>
      ))}
    </aside>
  );
}
