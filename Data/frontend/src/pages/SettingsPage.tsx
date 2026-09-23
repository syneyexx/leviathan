import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { media } from "../assets/media";
import { AppShell } from "../layouts/AppShell";
import { useAppToast } from "../state/useAppToast";
import type { SettingState, SettingsCategory } from "../types/api";
import { SettingField } from "./settings/SettingField";
import { SettingsNavigation } from "./settings/SettingsNavigation";

const EMPTY_CATEGORY_NOTES: Record<string, string> = {
  algemeen:
    "No application-level preferences are implemented yet. Domain configuration lives in specialized pages.",
  benchmarks:
    "Benchmark runs are owned by Models → Benchmarks. No separate global benchmark defaults exist.",
  mediacenter:
    "Media automation backend is not production-complete. No operator-adjustable media settings are exposed.",
  console:
    "No global console preferences are implemented. Use the Console product page for operator actions.",
  logs: "No operator-adjustable logging retention/verbosity settings are implemented yet.",
};

const FALLBACK_CATEGORIES: SettingsCategory[] = [
  { id: "algemeen", label: "Algemeen", description: "App defaults", order: 1, setting_count: 0 },
  { id: "llm_gedrag", label: "LLM Gedrag", description: "Response style & limits", order: 2, setting_count: 0 },
  { id: "llm_studio", label: "LLM Studio", description: "Legacy endpoint fallback", order: 3, setting_count: 0 },
  { id: "rechten", label: "Rechten & Security", description: "Access & network", order: 4, setting_count: 0 },
  { id: "benchmarks", label: "Model Benchmarks", description: "Eval defaults", order: 5, setting_count: 0 },
  { id: "mediacenter", label: "Mediacenter", description: "Media defaults", order: 6, setting_count: 0 },
  { id: "opslag", label: "Opslag", description: "Storage & backups", order: 7, setting_count: 0 },
  { id: "python", label: "Python & Runtime", description: "Runtime & concurrency", order: 8, setting_count: 0 },
  { id: "console", label: "Console", description: "Operator console", order: 9, setting_count: 0 },
  { id: "logs", label: "Logs", description: "Retention & verbosity", order: 10, setting_count: 0 },
  { id: "knowledge_rag", label: "Knowledge & RAG", description: "Retrieval & RAG V3", order: 11, setting_count: 0 },
  { id: "cognition_neuro", label: "Cognition & Neuro", description: "Cognitive Runtime", order: 12, setting_count: 0 },
  { id: "agents_coding", label: "Agents & Coding", description: "Agent defaults", order: 13, setting_count: 0 },
  { id: "tools_mcp", label: "Tools & MCP", description: "MCP policy", order: 14, setting_count: 0 },
  { id: "markt_sim", label: "Markt Simulatie", description: "Simulation defaults", order: 15, setting_count: 0 },
  { id: "data_research", label: "Data & Research", description: "HF & web search", order: 16, setting_count: 0 },
];

function parentDisabled(setting: SettingState, byKey: Map<string, SettingState>): boolean {
  return setting.requires.some((parentKey) => {
    const parent = byKey.get(parentKey);
    const value = parent?.desired_value ?? parent?.effective_value;
    return parent ? !value : false;
  });
}

export function SettingsPage() {
  const toast = useAppToast();
  const [searchParams, setSearchParams] = useSearchParams();
  const sectionParam = searchParams.get("section") || "llm_gedrag";

  const [categories, setCategories] = useState<SettingsCategory[]>(FALLBACK_CATEGORIES);
  const [settings, setSettings] = useState<SettingState[]>([]);
  const [drafts, setDrafts] = useState<Record<string, unknown>>({});
  const [loading, setLoading] = useState(true);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [activeId, setActiveId] = useState(sectionParam);
  const [statusLine, setStatusLine] = useState<string>("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const snapshot = await api.getSettings();
      setCategories(snapshot.categories.length ? snapshot.categories : FALLBACK_CATEGORIES);
      setSettings(snapshot.settings);
      const nextDrafts: Record<string, unknown> = {};
      for (const item of snapshot.settings) {
        if (item.secret) {
          nextDrafts[item.key] = "";
        } else {
          nextDrafts[item.key] = item.desired_value ?? item.effective_value;
        }
      }
      setDrafts(nextDrafts);
      setStatusLine(`Loaded ${snapshot.settings.length} settings`);
    } catch (error) {
      const message = error instanceof ApiError ? error.message : "Failed to load settings";
      toast(message);
      setStatusLine(message);
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const exists = categories.some((item) => item.id === sectionParam);
    setActiveId(exists ? sectionParam : categories[0]?.id || "llm_gedrag");
  }, [sectionParam, categories]);

  const byKey = useMemo(() => new Map(settings.map((item) => [item.key, item])), [settings]);

  const filteredSettings = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) {
      return settings.filter((item) => item.category === activeId);
    }
    return settings.filter((item) => {
      const hay = `${item.label} ${item.description} ${item.key} ${item.category}`.toLowerCase();
      return hay.includes(q);
    });
  }, [settings, activeId, query]);

  const selectCategory = (id: string) => {
    setActiveId(id);
    setQuery("");
    setSearchParams(id === "llm_gedrag" ? {} : { section: id }, { replace: true });
  };

  const applyOne = async (key: string, value: unknown, confirmDangerous = false) => {
    const setting = byKey.get(key);
    if (!setting) return;
    if (setting.dangerous && !confirmDangerous) {
      const ok = window.confirm(
        `Security-sensitive setting:\n\n${setting.label}\n\n${setting.description}\n\nConfirm change?`,
      );
      if (!ok) return;
      confirmDangerous = true;
    }
    setBusyKey(key);
    try {
      const result = await api.patchSetting(key, value, { confirmDangerous });
      setSettings((prev) => prev.map((item) => (item.key === result.setting.key ? result.setting : item)));
      if (!result.setting.secret) {
        setDrafts((prev) => ({
          ...prev,
          [key]: result.setting.desired_value ?? result.setting.effective_value,
        }));
      } else {
        setDrafts((prev) => ({ ...prev, [key]: "" }));
      }
      const msg = result.result.message || result.result.status;
      setStatusLine(msg);
      toast(msg);
      // Refresh full snapshot so dependent effective flags stay truthful.
      const snapshot = await api.getSettings();
      setSettings(snapshot.settings);
    } catch (error) {
      const message = error instanceof ApiError ? error.message : "Update failed";
      setStatusLine(message);
      toast(message);
    } finally {
      setBusyKey(null);
    }
  };

  const resetOne = async (key: string) => {
    setBusyKey(key);
    try {
      const result = await api.resetSetting(key);
      setStatusLine(result.result.message);
      toast(result.result.message);
      const snapshot = await api.getSettings();
      setSettings(snapshot.settings);
      setDrafts((prev) => {
        const next = { ...prev };
        for (const item of snapshot.settings) {
          next[item.key] = item.secret ? "" : item.desired_value ?? item.effective_value;
        }
        return next;
      });
    } catch (error) {
      const message = error instanceof ApiError ? error.message : "Reset failed";
      toast(message);
    } finally {
      setBusyKey(null);
    }
  };

  const clearSecret = async (key: string) => {
    const ok = window.confirm("Clear this secret? This cannot be undone from the UI.");
    if (!ok) return;
    setBusyKey(key);
    try {
      const result = await api.patchSetting(key, null, { clearSecret: true });
      toast(result.result.message);
      const snapshot = await api.getSettings();
      setSettings(snapshot.settings);
      setDrafts((prev) => ({ ...prev, [key]: "" }));
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "Clear failed");
    } finally {
      setBusyKey(null);
    }
  };

  const activeCategory = categories.find((item) => item.id === activeId);
  const emptyNote = EMPTY_CATEGORY_NOTES[activeId];

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Settings Mode"
      searchPlaceholder="Search settings, configurations, tools..."
      layout="wide"
      pageClass="lv-app--settings"
    >
      <main className="lv-main">
        <section className="lv-page-hero">
          <div className="lv-hero-media">
            <img src={media.globe} alt="" width={1400} height={380} />
          </div>
          <div className="lv-hero-shade" />
          <div className="lv-hero-content">
            <div className="lv-hero-kicker">
              <span />
              Configure. Optimize. Control.
              <span />
            </div>
            <h1 className="lv-hero-title">Settings</h1>
            <p className="lv-page-quote">“One control. One canonical value. One truthful effective state.”</p>
          </div>
          <div className="lv-hero-rail" aria-hidden="true">
            <span>Control</span>
            <span>Persist</span>
            <span>Apply</span>
            <span>Verify</span>
          </div>
        </section>

        <div className="lv-settings-layout">
          <SettingsNavigation
            categories={categories}
            activeId={activeId}
            onSelect={selectCategory}
            query={query}
            onQueryChange={(value) => {
              setQuery(value);
              if (value.trim()) {
                const match = settings.find((item) => {
                  const hay = `${item.label} ${item.description} ${item.key}`.toLowerCase();
                  return hay.includes(value.trim().toLowerCase());
                });
                if (match) setActiveId(match.category);
              }
            }}
          />

          <div className="lv-settings-content">
            <div className="lv-settings-content-head">
              <div>
                <div className="lv-section-label">{activeCategory?.label ?? activeId}</div>
                <p className="lv-muted">{activeCategory?.description}</p>
              </div>
              <div className="lv-settings-status">{loading ? "Loading…" : statusLine}</div>
            </div>

            {activeId === "llm_studio" ? (
              <article className="lv-panel lv-settings-card span-2">
                <div className="lv-section-label">Models Control Plane</div>
                <p className="lv-muted">
                  Managed providers, profiles, and routing live under Models. This category only edits the
                  legacy OpenAI-compatible fallback used when the registry is empty.
                </p>
                <Link className="lv-btn" to="/models">
                  Open Models →
                </Link>
              </article>
            ) : null}

            {activeId === "tools_mcp" ? (
              <article className="lv-panel lv-settings-card span-2">
                <div className="lv-section-label">MCP servers</div>
                <p className="lv-muted">
                  Server registration, transports, and tool calls are owned by the MCP operator page.
                  Settings only controls global MCP capability flags.
                </p>
                <Link className="lv-btn" to="/mcp">
                  Open MCP →
                </Link>
              </article>
            ) : null}

            {filteredSettings.length === 0 ? (
              <article className="lv-panel lv-settings-card span-2">
                <p className="lv-muted">{emptyNote || "No settings in this category."}</p>
              </article>
            ) : (
              <div className="lv-settings-grid lv-settings-grid--fields">
                {filteredSettings.map((setting) => (
                  <article key={setting.key} className="lv-panel lv-settings-card" id={`field-${setting.key}`}>
                    <SettingField
                      setting={setting}
                      draft={drafts[setting.key]}
                      disabled={parentDisabled(setting, byKey)}
                      busy={busyKey === setting.key}
                      onChange={(value) => {
                        setDrafts((prev) => ({ ...prev, [setting.key]: value }));
                        if (setting.type === "boolean") {
                          void applyOne(setting.key, value);
                        }
                      }}
                      onSave={() => void applyOne(setting.key, drafts[setting.key])}
                      onReset={() => void resetOne(setting.key)}
                      onClearSecret={setting.secret ? () => void clearSecret(setting.key) : undefined}
                    />
                  </article>
                ))}
              </div>
            )}
          </div>
        </div>
      </main>
    </AppShell>
  );
}
