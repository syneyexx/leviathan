import type { SettingsWorkspace } from "../../hooks/useSettingsWorkspace";
import { api, ApiError } from "../../api/client";
import { SettingField } from "../../pages/settings/SettingField";
import { SqliteManagerPanel } from "../../pages/settings/SqliteManagerPanel";
import type { SettingState } from "../../types/api";
import { Button } from "../ui";
import { SettingsGeneralPanel } from "./SettingsGeneralPanel";
import { SettingsProvidersPanel } from "./SettingsProvidersPanel";
import { SettingsSystemConfigPanel } from "./SettingsSystemConfigPanel";
import { Link } from "react-router-dom";

type Props = {
  ws: SettingsWorkspace;
};

const EMPTY_CATEGORY_NOTES: Record<string, string> = {
  benchmarks:
    "Benchmark runs are owned by Models → Benchmarks. No separate global benchmark defaults exist.",
  mediacenter:
    "Media automation backend is not production-complete. No operator-adjustable media settings are exposed.",
  console:
    "No global console preferences are implemented. Use the Console product page for operator actions.",
  logs: "No operator-adjustable logging retention/verbosity settings are implemented yet.",
};

function parentDisabled(setting: SettingState, byKey: Map<string, SettingState>): boolean {
  return setting.requires.some((parentKey) => {
    const parent = byKey.get(parentKey);
    const value = parent?.desired_value ?? parent?.effective_value;
    return parent ? !value : false;
  });
}

export function SettingsCategoryContent({ ws }: Props) {
  if (ws.activeId === "algemeen") {
    return (
      <div className="lv-v2-settings-algemeen">
        <SettingsGeneralPanel ws={ws} />
        <div className="lv-v2-settings-side-col">
          <SettingsProvidersPanel ws={ws} />
          <SettingsSystemConfigPanel ws={ws} />
        </div>
      </div>
    );
  }

  const emptyNote = EMPTY_CATEGORY_NOTES[ws.activeId];
  const isBehavior = ws.activeId === "llm_gedrag";

  return (
    <div className="lv-v2-settings-catalog">
      <div className="lv-v2-settings-panel-head">
        <div>
          <h3>{ws.activeCategory?.label || ws.activeId}</h3>
          <p>{ws.activeCategory?.description}</p>
        </div>
        <div className="lv-v2-settings-panel-head__actions">
          <input
            className="lv-v2-input"
            placeholder="Filter settings…"
            value={ws.query}
            onChange={(e) => ws.setQuery(e.target.value)}
          />
          <Button variant="secondary" size="sm" onClick={() => void ws.resetCategory(ws.activeId)}>
            Standaardwaarden
          </Button>
        </div>
      </div>

      <p className="lv-v2-settings-statusline" role="status">
        {ws.loading ? "Laden…" : ws.statusLine}
      </p>

      {isBehavior ? <BehaviorProfileBlock ws={ws} /> : null}

      {ws.activeId === "python" || ws.activeId === "opslag" ? <SqliteManagerPanel /> : null}

      {emptyNote && ws.categorySettings.length === 0 ? (
        <article className="lv-v2-panel lv-v2-settings-empty">
          <p>{emptyNote}</p>
          {ws.activeId === "benchmarks" ? (
            <p>
              Open <Link to="/models">Models → Benchmarks</Link>.
            </p>
          ) : null}
        </article>
      ) : null}

      <div className="lv-v2-settings-fields">
        {ws.categorySettings.map((setting) => (
          <article key={setting.key} className="lv-v2-panel lv-v2-settings-field-card" id={`field-${setting.key}`}>
            <SettingField
              setting={setting}
              draft={ws.drafts[setting.key]}
              disabled={parentDisabled(setting, ws.byKey) || ws.busyKey === setting.key}
              busy={ws.busyKey === setting.key}
              onChange={(value) => ws.setDraft(setting.key, value)}
              onSave={() => void ws.applyOne(setting.key, ws.drafts[setting.key])}
              onReset={() => void ws.resetOne(setting.key)}
              onClearSecret={setting.secret ? () => void ws.clearSecret(setting.key) : undefined}
            />
          </article>
        ))}
      </div>
    </div>
  );
}

function BehaviorProfileBlock({ ws }: Props) {
  const saveBehavior = async () => {
    ws.setSystemPromptBusy(true);
    try {
      const payload = {
        assistant_display_name: ws.behaviorDraft.assistant_display_name,
        identity_description: ws.behaviorDraft.identity_description,
        language_mode: ws.behaviorDraft.language_mode,
        language_explicit: ws.behaviorDraft.language_explicit,
        language_fallback: ws.behaviorDraft.language_fallback,
        reasoning_mode_default: ws.behaviorDraft.reasoning_mode_default,
        tool_use_style: ws.behaviorDraft.tool_use_style,
        retrieval: {
          mode: ws.behaviorDraft.retrieval_mode,
          top_k: ws.behaviorDraft.retrieval_top_k,
          relevance_threshold: ws.behaviorDraft.retrieval_relevance_threshold,
          deep_recall: ws.behaviorDraft.retrieval_deep_recall,
          debug_provenance: ws.behaviorDraft.retrieval_debug_provenance,
        },
        memory: {
          enabled: ws.behaviorDraft.memory_enabled,
          top_k: ws.behaviorDraft.memory_top_k,
        },
        generation: {
          temperature: ws.behaviorDraft.temperature === "" ? null : Number(ws.behaviorDraft.temperature),
          top_p: ws.behaviorDraft.top_p === "" ? null : Number(ws.behaviorDraft.top_p),
          max_output_tokens:
            ws.behaviorDraft.max_output_tokens === "" ? null : Number(ws.behaviorDraft.max_output_tokens),
          stream_enabled: ws.behaviorDraft.stream_enabled,
        },
        workers: {
          profile_enabled: ws.behaviorDraft.workers_profile_enabled,
          autostart: ws.behaviorDraft.workers_autostart,
        },
      };
      await api.patchBehaviorProfile(payload);
      if (ws.systemPrompt.trim()) {
        await api.putBehaviorSystemPrompt(ws.systemPrompt);
      }
      await ws.reloadBehavior();
      ws.toast("Applied — active from next turn");
    } catch (error) {
      ws.toast(error instanceof ApiError ? error.message : "Behavior save failed");
    } finally {
      ws.setSystemPromptBusy(false);
    }
  };

  return (
    <article className="lv-v2-panel lv-v2-settings-behavior">
      <div className="lv-v2-settings-panel-head">
        <div>
          <h4>LLM Gedrag / BehaviorProfile</h4>
          <p>Hot-applied identity & generation defaults — not authority settings.</p>
        </div>
        <Button variant="primary" size="sm" loading={ws.systemPromptBusy} onClick={() => void saveBehavior()}>
          Gedrag opslaan
        </Button>
      </div>
      <div className="lv-v2-settings-general__grid">
        <label className="lv-v2-settings-field">
          <span className="lv-v2-settings-field__label">Assistant display name</span>
          <input
            className="lv-v2-input"
            value={ws.behaviorDraft.assistant_display_name}
            onChange={(e) =>
              ws.setBehaviorDraft({ ...ws.behaviorDraft, assistant_display_name: e.target.value })
            }
          />
        </label>
        <label className="lv-v2-settings-field span-2">
          <span className="lv-v2-settings-field__label">Identity description</span>
          <textarea
            className="lv-v2-input lv-textarea lv-textarea--identity"
            rows={6}
            value={ws.behaviorDraft.identity_description}
            onChange={(e) =>
              ws.setBehaviorDraft({ ...ws.behaviorDraft, identity_description: e.target.value })
            }
          />
        </label>
        <label className="lv-v2-settings-field span-2">
          <span className="lv-v2-settings-field__label">System Prompt</span>
          <textarea
            className="lv-v2-input lv-textarea lv-textarea--system-prompt"
            rows={12}
            value={ws.systemPrompt}
            onChange={(e) => ws.setSystemPrompt(e.target.value)}
          />
          {ws.systemPromptHash ? (
            <small className="lv-v2-settings-field__hint">hash {ws.systemPromptHash.slice(0, 12)}…</small>
          ) : null}
        </label>
      </div>
    </article>
  );
}
