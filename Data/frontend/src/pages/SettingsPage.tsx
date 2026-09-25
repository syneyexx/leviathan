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
  const [behaviorDraft, setBehaviorDraft] = useState({
    assistant_display_name: "",
    identity_description: "",
    language_mode: "auto_follow_user",
    language_explicit: "nl",
    language_fallback: "en",
    reasoning_mode_default: "auto",
    tool_use_style: "balanced",
    retrieval_mode: "auto",
    retrieval_top_k: 8,
    retrieval_relevance_threshold: 0.35,
    retrieval_deep_recall: true,
    retrieval_debug_provenance: false,
    memory_enabled: true,
    memory_top_k: 5,
    temperature: "" as string | number,
    top_p: "" as string | number,
    max_output_tokens: "" as string | number,
    stream_enabled: true,
    workers_profile_enabled: true,
    workers_autostart: false,
  });

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
        const retrieval = (profile.retrieval || {}) as Record<string, unknown>;
        const memory = (profile.memory || {}) as Record<string, unknown>;
        const generation = (profile.generation || {}) as Record<string, unknown>;
        const workers = (profile.workers || {}) as Record<string, unknown>;
        setBehaviorDraft({
          assistant_display_name: String(profile.assistant_display_name ?? ""),
          identity_description: String(profile.identity_description ?? ""),
          language_mode: String(profile.language_mode ?? "auto_follow_user"),
          language_explicit: String(profile.language_explicit ?? "nl"),
          language_fallback: String(profile.language_fallback ?? "en"),
          reasoning_mode_default: String(profile.reasoning_mode_default ?? "auto"),
          tool_use_style: String(profile.tool_use_style ?? "balanced"),
          retrieval_mode: String(retrieval.mode ?? "auto"),
          retrieval_top_k: Number(retrieval.top_k ?? 8),
          retrieval_relevance_threshold: Number(retrieval.relevance_threshold ?? 0.35),
          retrieval_deep_recall: Boolean(retrieval.deep_recall ?? true),
          retrieval_debug_provenance: Boolean(retrieval.debug_provenance ?? false),
          memory_enabled: Boolean(memory.enabled ?? true),
          memory_top_k: Number(memory.top_k ?? 5),
          temperature: generation.temperature == null ? "" : Number(generation.temperature),
          top_p: generation.top_p == null ? "" : Number(generation.top_p),
          max_output_tokens:
            generation.max_output_tokens == null ? "" : Number(generation.max_output_tokens),
          stream_enabled: Boolean(generation.stream_enabled ?? true),
          workers_profile_enabled: Boolean(workers.profile_enabled ?? true),
          workers_autostart: Boolean(workers.autostart ?? false),
        });
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
                <div className="lv-section-label">Assistant / Behavior</div>
                <p className="lv-muted">
                  Operator-editable identity, language, generation, Brain retrieval, memory, and worker
                  knobs. Behavior is not authority — it cannot bypass ExecutionGateway, approvals, or
                  workspace confinement. Behavior-only changes apply on the next chat turn without restart.
                </p>
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                    gap: "0.75rem",
                    marginTop: "0.75rem",
                  }}
                >
                  <label>
                    Assistant name
                    <input
                      className="lv-input"
                      value={behaviorDraft.assistant_display_name}
                      onChange={(e) =>
                        setBehaviorDraft((d) => ({ ...d, assistant_display_name: e.target.value }))
                      }
                    />
                  </label>
                  <label>
                    Language mode
                    <select
                      className="lv-input"
                      value={behaviorDraft.language_mode}
                      onChange={(e) =>
                        setBehaviorDraft((d) => ({ ...d, language_mode: e.target.value }))
                      }
                    >
                      <option value="auto_follow_user">Auto — follow user</option>
                      <option value="explicit">Always / explicit language</option>
                      <option value="custom">Custom policy</option>
                    </select>
                  </label>
                  {behaviorDraft.language_mode === "explicit" ? (
                    <label>
                      Explicit language
                      <select
                        className="lv-input"
                        value={behaviorDraft.language_explicit || "nl"}
                        onChange={(e) =>
                          setBehaviorDraft((d) => ({ ...d, language_explicit: e.target.value }))
                        }
                      >
                        <option value="nl">Dutch</option>
                        <option value="en">English</option>
                        <option value="de">German</option>
                        <option value="fr">French</option>
                        <option value="es">Spanish</option>
                      </select>
                    </label>
                  ) : null}
                  <label>
                    Fallback language
                    <select
                      className="lv-input"
                      value={behaviorDraft.language_fallback}
                      onChange={(e) =>
                        setBehaviorDraft((d) => ({ ...d, language_fallback: e.target.value }))
                      }
                    >
                      <option value="en">English</option>
                      <option value="nl">Dutch</option>
                      <option value="de">German</option>
                      <option value="fr">French</option>
                      <option value="es">Spanish</option>
                    </select>
                  </label>
                  <label>
                    Reasoning default
                    <select
                      className="lv-input"
                      value={behaviorDraft.reasoning_mode_default}
                      onChange={(e) =>
                        setBehaviorDraft((d) => ({ ...d, reasoning_mode_default: e.target.value }))
                      }
                    >
                      <option value="auto">Auto</option>
                      <option value="fast">Fast</option>
                      <option value="standard">Standard</option>
                      <option value="deep">Deep</option>
                    </select>
                  </label>
                  <label>
                    Tool style
                    <input
                      className="lv-input"
                      value={behaviorDraft.tool_use_style}
                      onChange={(e) =>
                        setBehaviorDraft((d) => ({ ...d, tool_use_style: e.target.value }))
                      }
                    />
                  </label>
                  <label>
                    Retrieval mode
                    <select
                      className="lv-input"
                      value={behaviorDraft.retrieval_mode}
                      onChange={(e) =>
                        setBehaviorDraft((d) => ({ ...d, retrieval_mode: e.target.value }))
                      }
                    >
                      <option value="auto">auto</option>
                      <option value="forced_on">forced_on</option>
                      <option value="forced_off">forced_off</option>
                    </select>
                  </label>
                  <label>
                    Retrieval top_k
                    <input
                      className="lv-input"
                      type="number"
                      value={behaviorDraft.retrieval_top_k}
                      onChange={(e) =>
                        setBehaviorDraft((d) => ({
                          ...d,
                          retrieval_top_k: Number(e.target.value),
                        }))
                      }
                    />
                  </label>
                  <label>
                    Relevance threshold
                    <input
                      className="lv-input"
                      type="number"
                      step="0.01"
                      min={0}
                      max={1}
                      value={behaviorDraft.retrieval_relevance_threshold}
                      onChange={(e) =>
                        setBehaviorDraft((d) => ({
                          ...d,
                          retrieval_relevance_threshold: Number(e.target.value),
                        }))
                      }
                    />
                  </label>
                  <label>
                    Temperature
                    <input
                      className="lv-input"
                      type="number"
                      step="0.01"
                      value={behaviorDraft.temperature}
                      onChange={(e) =>
                        setBehaviorDraft((d) => ({ ...d, temperature: e.target.value }))
                      }
                      placeholder="provider default"
                    />
                  </label>
                  <label>
                    Max output tokens
                    <input
                      className="lv-input"
                      type="number"
                      value={behaviorDraft.max_output_tokens}
                      onChange={(e) =>
                        setBehaviorDraft((d) => ({ ...d, max_output_tokens: e.target.value }))
                      }
                      placeholder="provider default"
                    />
                  </label>
                </div>
                <label style={{ display: "block", marginTop: "0.75rem" }}>
                  Identity description
                  <textarea
                    className="lv-input"
                    rows={2}
                    value={behaviorDraft.identity_description}
                    onChange={(e) =>
                      setBehaviorDraft((d) => ({ ...d, identity_description: e.target.value }))
                    }
                    style={{ width: "100%", font: "inherit" }}
                  />
                </label>
                <div className="lv-section-label" style={{ marginTop: "1rem" }}>
                  System Prompt
                </div>
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
                          const values: Record<string, unknown> = {
                            system_prompt: systemPrompt,
                            assistant_display_name: behaviorDraft.assistant_display_name,
                            identity_description: behaviorDraft.identity_description,
                            language_mode: behaviorDraft.language_mode,
                            language_explicit: behaviorDraft.language_explicit,
                            language_fallback: behaviorDraft.language_fallback,
                            reasoning_mode_default: behaviorDraft.reasoning_mode_default,
                            tool_use_style: behaviorDraft.tool_use_style,
                            retrieval_mode: behaviorDraft.retrieval_mode,
                            retrieval_top_k: behaviorDraft.retrieval_top_k,
                            retrieval_relevance_threshold: behaviorDraft.retrieval_relevance_threshold,
                            retrieval_deep_recall: behaviorDraft.retrieval_deep_recall,
                            retrieval_debug_provenance: behaviorDraft.retrieval_debug_provenance,
                            memory_enabled: behaviorDraft.memory_enabled,
                            memory_top_k: behaviorDraft.memory_top_k,
                            stream_enabled: behaviorDraft.stream_enabled,
                            workers_profile_enabled: behaviorDraft.workers_profile_enabled,
                            workers_autostart: behaviorDraft.workers_autostart,
                          };
                          if (behaviorDraft.temperature !== "") {
                            values.temperature = Number(behaviorDraft.temperature);
                          }
                          if (behaviorDraft.top_p !== "") {
                            values.top_p = Number(behaviorDraft.top_p);
                          }
                          if (behaviorDraft.max_output_tokens !== "") {
                            values.max_output_tokens = Number(behaviorDraft.max_output_tokens);
                          }
                          const res = await api.patchBehaviorProfile(values);
                          const effective = res.effective || res.profile || {};
                          const persistedPrompt = String(effective.system_prompt ?? "");
                          const persistedHash = typeof effective.hash === "string" ? effective.hash : null;
                          if (persistedPrompt.trim() !== systemPrompt.trim()) {
                            throw new Error("Save verification failed: system prompt did not persist");
                          }
                          setSystemPrompt(persistedPrompt || systemPrompt);
                          setSystemPromptHash(persistedHash);
                          toast(`Behavior settings saved · hash ${persistedHash?.slice(0, 10) ?? "—"}`);
                          setStatusLine("Applied — active from next turn");
                          // Confirm round-trip from backend (authority). No reload / new chat.
                          const verified = await api.getBehaviorProfile();
                          const verifiedPrompt = String(verified.profile?.system_prompt ?? "");
                          if (verifiedPrompt.trim() !== systemPrompt.trim()) {
                            throw new Error("Reload verification failed: stored prompt mismatch");
                          }
                        } catch (error) {
                          toast(error instanceof ApiError ? error.message : "Failed to save behavior");
                        } finally {
                          setSystemPromptBusy(false);
                        }
                      })();
                    }}
                  >
                    Save behavior settings
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
                          toast("Behavior reset to canonical seed");
                          await load();
                        } catch (error) {
                          toast(error instanceof ApiError ? error.message : "Failed to reset behavior");
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
                  Effective hash: {systemPromptHash ?? "—"} · applies live (no restart)
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
