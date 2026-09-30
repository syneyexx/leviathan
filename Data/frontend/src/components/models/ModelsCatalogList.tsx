import type { ModelsWorkspace } from "../../hooks/useModelsWorkspace";
import { Panel } from "../ui";
import { formatParams } from "./modelsHelpers";

type Props = {
  ws: ModelsWorkspace;
};

const AVATAR_PALETTE = ["#3b82f6", "#a855f7", "#f97316", "#14b8a6", "#ec4899", "#22c55e", "#eab308"];

function avatarColor(seed: string): string {
  let hash = 0;
  for (let i = 0; i < seed.length; i += 1) hash = (hash * 31 + seed.charCodeAt(i)) >>> 0;
  return AVATAR_PALETTE[hash % AVATAR_PALETTE.length];
}

function ModelIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
      <rect x="4" y="4" width="16" height="16" rx="3" />
      <path d="M8 9h8M8 12h8M8 15h5" />
    </svg>
  );
}

function RefreshIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <path d="M20 12a8 8 0 1 1-2.2-5.5" />
      <path d="M20 4v5h-5" />
    </svg>
  );
}

export function ModelsCatalogList({ ws }: Props) {
  return (
    <Panel
      title="Model"
      icon={<ModelIcon />}
      className="lv-v2-models-catalog"
      action={
        <button
          type="button"
          className="lv-v2-topbar__icon-btn"
          aria-label="Modellen vernieuwen"
          title="Modellen vernieuwen"
          onClick={() => void ws.refresh()}
        >
          <RefreshIcon />
        </button>
      }
    >
      <div className="lv-v2-research-search lv-v2-models-catalog__search">
        <input
          type="text"
          placeholder="Zoek modellen…"
          value={ws.query}
          onChange={(e) => ws.setQuery(e.target.value)}
          aria-label="Zoek modellen"
        />
      </div>

      {ws.loading && ws.filteredModels.length === 0 ? (
        <p className="lv-v2-muted">Modellen laden…</p>
      ) : ws.filteredModels.length === 0 ? (
        <p className="lv-v2-muted">Geen modellen gevonden.</p>
      ) : (
        <ul className="lv-v2-models-catalog__list">
          {ws.filteredModels.map((model) => {
            const selected = model.id === ws.selectedId;
            const initials = (model.family || model.displayName || model.id).slice(0, 2).toUpperCase();
            const params = formatParams(model.parameterCount);
            const subtitle = [model.family, params].filter(Boolean).join(" / ") || model.providerId;
            return (
              <li key={model.id}>
                <button
                  type="button"
                  className={`lv-v2-models-catalog__row${selected ? " is-selected" : ""}`}
                  onClick={() => ws.selectModel(model.id)}
                  aria-pressed={selected}
                >
                  <span
                    className="lv-v2-models-catalog__avatar"
                    style={{ background: avatarColor(model.family || model.providerId) }}
                    aria-hidden="true"
                  >
                    {initials}
                  </span>
                  <span className="lv-v2-models-catalog__main">
                    <strong>{model.displayName || model.id}</strong>
                    <span>
                      {subtitle}
                      {model.quantization ? ` / ${model.quantization}` : ""}
                    </span>
                  </span>
                  {model.format ? <span className="lv-v2-badge lv-v2-badge--muted">{model.format.toUpperCase()}</span> : null}
                  {model.loaded ? <span className="lv-v2-status-dot lv-v2-status-dot--success" title="Geladen" /> : null}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}
