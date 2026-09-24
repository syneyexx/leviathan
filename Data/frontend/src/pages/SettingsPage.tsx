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

const INTELLIGENCE_BANNER_CATEGORIES = new Set([
  "reasoning",
  "knowledge_rag",
  "memory",
  "cognition_neuro",
  "verification",
  "learning_assimilation",
]);

type IntelligenceStackSummary = {
  status?: string;
  label?: string;
  reasoning_mode?: string;
  rag?: string;
  semantic_retrieval?: string;
  memory?: string;
  cognition?: string;
  neuro?: string;
  cortex?: string;
  residual?: string;
  verification?: string;
  learning?: string;
};

function stackSummaryFromHealth(health: Record<string, unknown> | null): IntelligenceStackSummary | null {
  if (!health) return null;
  const raw = health.stack_summary;
  if (!raw || typeof raw !== "object") return null;
  return raw as IntelligenceStackSummary;
}

const FALLBACK_CATEGORIES: SettingsCategory[] = [
  { id: "algemeen", label: "Algemeen", description: "App defaults", order: 1, setting_count: 0 },
  { id: "llm_gedrag", label: "LLM Gedrag", description: "Response style & limits", order: 2, setting_count: 0 },
  { id: "reasoning", label: "Reasoning", description: "Modes, budgets & gates", order: 3, setting_count: 0 },
  { id: "llm_studio", label: "LLM Studio", description: "Legacy endpoint fallback", order: 4, setting_count: 0 },
  { id: "rechten", label: "Rechten & Security", description: "Access & network", order: 5, setting_count: 0 },
  { id: "benchmarks", label: "Model Benchmarks", description: "Eval defaults", order: 6, setting_count: 0 },
  { id: "mediacenter", label: "Mediacenter", description: "Media defaults", order: 7, setting_count: 0 },
  { id: "opslag", label: "Opslag", description: "Storage & backups", order: 8, setting_count: 0 },
  { id: "python", label: "Python & Runtime", description: "Runtime & concurrency", order: 9, setting_count: 0 },
  { id: "console", label: "Console", description: "Operator console", order: 10, setting_count: 0 },
  { id: "logs", label: "Logs", description: "Retention & verbosity", order: 11, setting_count: 0 },
  { id: "knowledge_rag", label: "Knowledge & RAG", description: "Retrieval & RAG V3", order: 12, setting_count: 0 },
  { id: "memory", label: "Memory", description: "Tiers & semantic memory", order: 13, setting_count: 0 },
  { id: "verification", label: "Verification", description: "Grounding & evidence", order: 14, setting_count: 0 },
  { id: "cognition_neuro", label: "Cognition & Neuro", description: "Cognitive Runtime", order: 15, setting_count: 0 },
  {
    id: "learning_assimilation",
    label: "Learning & Assimilation",
    description: "Research & dataset promotion",
    order: 16,
    setting_count: 0,
  },
  { id: "agents_coding", label: "Agents & Coding", description: "Agent defaults", order: 17, setting_count: 0 },
  { id: "tools_mcp", label: "Tools & MCP", description: "MCP policy", order: 18, setting_count: 0 },
  { id: "markt_sim", label: "Markt Simulatie", description: "Simulation defaults", order: 19, setting_count: 0 },
  { id: "data_research", label: "Data & Research", description: "HF & web search", order: 20, setting_count: 0 },
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
  const [intelligenceHealth, setIntelligenceHealth] = useState<Record<string, unknown> | null>(null);
  const [intelligenceHealthError, setIntelligenceHealthError] = useState(false);
  const [systemPrompt, setSystemPrompt] = useState("");
  const [systemPromptDefault, setSystemPromptDefault] = useState("");
  const [systemPromptBusy, setSystemPromptBusy] = useState(false);
  const [systemPromptHash, setSystemPromptHash] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [snapshot, healthResult] = await Promise.all([
        api.getSettings(),
        api.intelligenceHealth().then(
          (payload) => ({ ok: true as const, payload }),
          () => ({ ok: false as const, payload: null }),
        ),
      ]);
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
      if (healthResult.ok && healthResult.payload) {
        setIntelligenceHealth(healthResult.payload);
        setIntelligenceHealthError(false);
      } else {
        setIntelligenceHealth(null);
        setIntelligenceHealthError(true);
      }
      try {
        const behavior = await api.getBehaviorProfile();
        const profile = behavior.profile || {};
        setSystemPrompt(String(profile.system_prompt ?? ""));
        setSystemPromptDefault(String(profile.default_system_prompt ?? ""));
        setSystemPromptHash(typeof profile.hash === "string" ? profile.hash : null);
      } catch {
        /* behavior profile optional during partial boots */
      }
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
  const showIntelligenceBanner = INTELLIGENCE_BANNER_CATEGORIES.has(activeId);
  const stackSummary = stackSummaryFromHealth(intelligenceHealth);

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

            {showIntelligenceBanner ? (
              <article className="lv-panel lv-settings-card span-2" role="status">
                <div className="lv-section-label">Intelligence status</div>
                {intelligenceHealthError || !stackSummary ? (
                  <p className="lv-muted">Intelligence status unavailable</p>
                ) : (
                  <div className="lv-settings-grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(9rem, 1fr))", gap: "0.5rem 1rem" }}>
                    <div>
                      <small className="lv-muted">Intelligence Stack</small>
                      <div>{stackSummary.label || stackSummary.status || "—"}</div>
                    </div>
                    <div>
                      <small className="lv-muted">Reasoning</small>
                      <div>{stackSummary.reasoning_mode || "—"}</div>
                    </div>
                    <div>
                      <small className="lv-muted">RAG</small>
                      <div>{stackSummary.rag || "—"}</div>
                    </div>
                    <div>
                      <small className="lv-muted">Semantic Retrieval</small>
                      <div>{stackSummary.semantic_retrieval || "—"}</div>
                    </div>
                    <div>
                      <small className="lv-muted">Memory</small>
                      <div>{stackSummary.memory || "—"}</div>
                    </div>
                    <div>
                      <small className="lv-muted">Cognition</small>
                      <div>{stackSummary.cognition || "—"}</div>
                    </div>
                    <div>
                      <small className="lv-muted">Neuro</small>
                      <div>{stackSummary.neuro || "—"}</div>
                    </div>
                    <div>
                      <small className="lv-muted">Cortex</small>
                      <div>{stackSummary.cortex || "—"}</div>
                    </div>
                    <div>
                      <small className="lv-muted">Residual</small>
                      <div>{stackSummary.residual || "—"}</div>
                    </div>
                    <div>
                      <small className="lv-muted">Verification</small>
                      <div>{stackSummary.verification || "—"}</div>
                    </div>
                    <div>
                      <small className="lv-muted">Learning</small>
                      <div>{stackSummary.learning || "—"}</div>
                    </div>
                  </div>
                )}
              </article>
            ) : null}

            {activeId === "llm_gedrag" ? (
              <article className="lv-panel lv-settings-card span-2">
                <div className="lv-section-label">System Prompt (BehaviorProfile)</div>
                <p className="lv-muted">
                  Operator-editable LEVIATHAN behavioral identity. This is behavior, not authority — it cannot
                  bypass ExecutionGateway, approvals, or workspace confinement.
                </p>
                <textarea
                  className="lv-input"
                  rows={6}
                  value={systemPrompt}
                  onChange={(e) => setSystemPrompt(e.target.value)}
                  aria-label="System prompt"
                  style={{ width: "100%", marginTop: "0.75rem", font: "inherit" }}
                />
                <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.75rem", flexWrap: "wrap" }}>
                  <button
                    type="button"
                    className="lv-btn"
                    disabled={systemPromptBusy || !systemPrompt.trim()}
                    onClick={() => {
                      void (async () => {
                        setSystemPromptBusy(true);
                        try {
                          const res = await api.putBehaviorSystemPrompt(systemPrompt);
                          const effective = res.effective || res.profile || {};
                          setSystemPrompt(String(effective.system_prompt ?? systemPrompt));
                          setSystemPromptHash(typeof effective.hash === "string" ? effective.hash : null);
                          toast("System prompt saved");
                          setStatusLine("BehaviorProfile system prompt updated");
                        } catch (error) {
                          toast(error instanceof ApiError ? error.message : "Failed to save system prompt");
                        } finally {
                          setSystemPromptBusy(false);
                        }
                      })();
                    }}
                  >
                    Save system prompt
                  </button>
                  <button
                    type="button"
                    className="lv-btn"
                    disabled={systemPromptBusy}
                    onClick={() => {
                      void (async () => {
                        setSystemPromptBusy(true);
                        try {
                          const res = await api.resetBehaviorProfile();
                          const effective = res.effective || res.profile || {};
                          setSystemPrompt(String(effective.system_prompt ?? systemPromptDefault));
                          setSystemPromptHash(typeof effective.hash === "string" ? effective.hash : null);
                          toast("System prompt reset to default");
                        } catch (error) {
                          toast(error instanceof ApiError ? error.message : "Failed to reset system prompt");
                        } finally {
                          setSystemPromptBusy(false);
                        }
                      })();
                    }}
                  >
                    Reset to default
                  </button>
                </div>
                <p className="lv-muted" style={{ marginTop: "0.5rem" }}>
                  Effective hash: {systemPromptHash ?? "—"}
                </p>
              </article>
            ) : null}

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
