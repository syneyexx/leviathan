import { useState } from "react";
import type { ModelDescriptor, RouterConfig } from "../../types/api";

const ROLE_KEYS = [
  { key: "chat", label: "General" },
  { key: "coding", label: "Coding" },
  { key: "research", label: "Research" },
  { key: "analysis", label: "Analysis" },
  { key: "fast", label: "Fast" },
] as const;

export function ModelRouterPanel({
  router,
  models,
  onSave,
}: {
  router: RouterConfig;
  models: ModelDescriptor[];
  onSave: (next: Partial<RouterConfig>) => Promise<void>;
}) {
  const [draft, setDraft] = useState(router);
  const [routerKey, setRouterKey] = useState(JSON.stringify(router));
  const incomingKey = JSON.stringify(router);
  if (incomingKey !== routerKey) {
    setRouterKey(incomingKey);
    setDraft(router);
  }
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await onSave(draft);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="lv-panel lv-card">
      <div className="lv-section-label">Model Assignments</div>
      {error ? <p className="lv-muted">{error}</p> : null}

      <label className="lv-models-field">
        Fallback order (drag not required — comma or newline separated model ids)
        <textarea
          className="lv-input"
          rows={3}
          value={draft.fallbackOrder.join("\n")}
          onChange={(e) =>
            setDraft({
              ...draft,
              fallbackOrder: e.target.value
                .split(/[\n,]/)
                .map((s) => s.trim())
                .filter(Boolean),
            })
          }
        />
      </label>

      <div className="lv-section-label">Role overrides</div>
      <div className="lv-models-roles">
        {ROLE_KEYS.map(({ key, label }) => (
          <label key={key} className="lv-models-field">
            {label}
            <select
              className="lv-select"
              value={draft.roleModelOverrides[key] ?? ""}
              onChange={(e) => {
                const next = { ...draft.roleModelOverrides };
                if (!e.target.value) delete next[key];
                else next[key] = e.target.value;
                setDraft({ ...draft, roleModelOverrides: next });
              }}
            >
              <option value="">Default / Auto</option>
              {models.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.displayName}
                </option>
              ))}
            </select>
          </label>
        ))}
      </div>

      <label className="lv-models-check">
        <input
          type="checkbox"
          checked={draft.streaming}
          onChange={(e) => setDraft({ ...draft, streaming: e.target.checked })}
        />
        Streaming preferred when runtime supports it
      </label>
      <label className="lv-models-check">
        <input
          type="checkbox"
          checked={draft.streamProvisionalText}
          onChange={(e) => setDraft({ ...draft, streamProvisionalText: e.target.checked })}
        />
        Stream provisional text (distinct from final persisted response)
      </label>
      <label className="lv-models-check">
        <input
          type="checkbox"
          checked={draft.progressEventsEnabled}
          onChange={(e) => setDraft({ ...draft, progressEventsEnabled: e.target.checked })}
        />
        Progress events enabled
      </label>
      <label className="lv-models-check">
        <input
          type="checkbox"
          checked={draft.cloudFallbackAllowed}
          onChange={(e) => setDraft({ ...draft, cloudFallbackAllowed: e.target.checked })}
        />
        Allow cloud fallback (explicit)
      </label>

      <button className="lv-btn lv-btn-gold" type="button" disabled={busy} onClick={() => void save()}>
        Save router
      </button>
    </article>
  );
}
