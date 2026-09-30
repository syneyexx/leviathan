/**
 * Settings V2 workspace — canonical Settings Control Plane + Model Control Plane
 * + telemetry orchestration. No parallel settings store.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { SidebarStatusRow } from "../components/layout/AppSidebarV2";
import { normalizeSystemStatus } from "../lib/dashboardNormalize";
import {
  applyUiPreferences,
  desktopNotificationCapability,
  ensureDesktopNotificationPermission,
  readUiPrefsCache,
  SYSTEM_PANEL_KEYS,
  UI_SETTING_KEYS,
  writeUiPrefsCache,
  type UiPrefsCache,
} from "../lib/uiPreferences";
import { useAppToast } from "../state/useAppToast";
import type {
  HealthResponse,
  ModelDescriptor,
  ModelProvider,
  SettingMutationResult,
  SettingState,
  SettingsCategory,
  SystemTelemetryResponse,
} from "../types/api";

export type SettingsKpis = {
  systemLabel: string;
  systemTone: "success" | "warning" | "danger" | "muted" | "info";
  systemOperational: boolean;
  modelsAvailable: number | null;
  modelsRegistered: number | null;
  memoryLabel: string;
  memorySub: string;
  memoryPct: number | null;
  toolsActive: number | null;
  toolsRegistered: number | null;
  usersLabel: string;
  usersSub: string;
  memoryHistory: number[];
};

export type StartupRegistration = {
  platform: string;
  supported: boolean;
  desired: boolean;
  registered: boolean | null;
  status: string;
  detail: string;
};

const CATEGORY_ICONS: Record<string, string> = {
  algemeen: "sliders",
  llm_gedrag: "brain",
  reasoning: "brain",
  llm_studio: "cpu",
  rechten: "shield",
  benchmarks: "chart",
  mediacenter: "media",
  opslag: "disk",
  python: "server",
  console: "terminal",
  logs: "list",
  knowledge_rag: "book",
  memory: "memory",
  verification: "check",
  cognition_neuro: "network",
  learning_assimilation: "learn",
  agents_coding: "agents",
  tools_mcp: "tools",
  markt_sim: "trading",
  data_research: "data",
};

function errMsg(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return fallback;
}

function settingValue(setting: SettingState | undefined): unknown {
  if (!setting) return undefined;
  if (setting.secret) return "";
  return setting.desired_value ?? setting.effective_value;
}

function syncPrefsFromSettings(settings: SettingState[]): UiPrefsCache {
  const byKey = new Map(settings.map((s) => [s.key, s]));
  const pick = (key: string, fallback: unknown) => {
    const v = settingValue(byKey.get(key));
    return v === undefined || v === null ? fallback : v;
  };
  return writeUiPrefsCache({
    app_display_name: String(pick("ui.app_display_name", "Leviathan AI Control Center")),
    timezone: String(pick("ui.timezone", "Europe/Amsterdam")),
    locale: String(pick("ui.locale", "nl")),
    theme: String(pick("ui.theme", "dark_leviathan")),
    auto_refresh_seconds: Number(pick("ui.auto_refresh_seconds", 30)),
    sound_notifications: Boolean(pick("ui.sound_notifications", true)),
    desktop_notifications: Boolean(pick("ui.desktop_notifications", true)),
    prefer_local_data: Boolean(pick("ui.prefer_local_data", true)),
    optional_diagnostics_share: Boolean(pick("ui.optional_diagnostics_share", false)),
    crash_reports_enabled: Boolean(pick("ui.crash_reports_enabled", true)),
  });
}

export function useSettingsWorkspace() {
  const toast = useAppToast();
  const [searchParams, setSearchParams] = useSearchParams();
  const sectionParam = searchParams.get("section") || "algemeen";

  const [categories, setCategories] = useState<SettingsCategory[]>([]);
  const [settings, setSettings] = useState<SettingState[]>([]);
  const [drafts, setDrafts] = useState<Record<string, unknown>>({});
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [statusLine, setStatusLine] = useState("");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const [activeId, setActiveId] = useState(sectionParam);
  const [query, setQuery] = useState("");

  const [providers, setProviders] = useState<ModelProvider[]>([]);
  const [models, setModels] = useState<ModelDescriptor[]>([]);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthError, setHealthError] = useState(false);
  const [telemetry, setTelemetry] = useState<SystemTelemetryResponse | null>(null);
  const [memoryHistory, setMemoryHistory] = useState<number[]>([]);
  const [toolsActive, setToolsActive] = useState<number | null>(null);
  const [toolsRegistered, setToolsRegistered] = useState<number | null>(null);
  const [startup, setStartup] = useState<StartupRegistration | null>(null);
  const [desktopPerm, setDesktopPerm] = useState(() =>
    desktopNotificationCapability(readUiPrefsCache().desktop_notifications),
  );
  const [saveReceipt, setSaveReceipt] = useState<SettingMutationResult[] | null>(null);
  const [providerDrawerOpen, setProviderDrawerOpen] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);

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

  const inFlight = useRef(false);
  const mounted = useRef(true);

  const autoRefreshSeconds = Number(drafts["ui.auto_refresh_seconds"] ?? readUiPrefsCache().auto_refresh_seconds ?? 30);

  const hydrateDrafts = useCallback((items: SettingState[]) => {
    const next: Record<string, unknown> = {};
    for (const item of items) {
      next[item.key] = item.secret ? "" : item.desired_value ?? item.effective_value;
    }
    setDrafts(next);
  }, []);

  const loadBehavior = useCallback(async () => {
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
        max_output_tokens: generation.max_output_tokens == null ? "" : Number(generation.max_output_tokens),
        stream_enabled: Boolean(generation.stream_enabled ?? true),
        workers_profile_enabled: Boolean(workers.profile_enabled ?? true),
        workers_autostart: Boolean(workers.autostart ?? false),
      });
    } catch {
      /* optional during partial boots */
    }
  }, []);

  const loadLive = useCallback(async () => {
    const [healthRes, modelsRes, providersRes, telemetryRes, toolsRes, startupRes] = await Promise.all([
      api.health().then(
        (payload) => ({ ok: true as const, payload }),
        () => ({ ok: false as const, payload: null }),
      ),
      api.listModels().then(
        (payload) => ({ ok: true as const, payload }),
        () => ({ ok: false as const, payload: null }),
      ),
      api.listModelProviders().then(
        (payload) => ({ ok: true as const, payload }),
        () => ({ ok: false as const, payload: null }),
      ),
      api.systemTelemetry().then(
        (payload) => ({ ok: true as const, payload }),
        () => ({ ok: false as const, payload: null }),
      ),
      api.mcpTools().then(
        (payload) => ({ ok: true as const, payload }),
        () => ({ ok: false as const, payload: null }),
      ),
      api.getStartupRegistration().then(
        (payload) => ({ ok: true as const, payload }),
        () => ({ ok: false as const, payload: null }),
      ),
    ]);

    if (!mounted.current) return;

    if (healthRes.ok && healthRes.payload) {
      setHealth(healthRes.payload);
      setHealthError(false);
    } else {
      setHealthError(true);
    }

    if (modelsRes.ok && modelsRes.payload) {
      setModels(modelsRes.payload.models || []);
    }

    if (providersRes.ok && providersRes.payload) {
      setProviders(providersRes.payload.providers || []);
    }

    if (telemetryRes.ok && telemetryRes.payload) {
      setTelemetry(telemetryRes.payload);
      const ram = telemetryRes.payload.dashboard?.ramPct;
      if (typeof ram === "number" && Number.isFinite(ram)) {
        setMemoryHistory((prev) => {
          const next = [...prev, ram];
          return next.length > 24 ? next.slice(next.length - 24) : next;
        });
      }
    }

    if (toolsRes.ok && toolsRes.payload) {
      const tools = toolsRes.payload.tools || [];
      setToolsRegistered(tools.length);
      const active = tools.filter((t) => {
        const avail = String(t.availability || "").toLowerCase();
        return avail === "available" || avail === "ready" || avail === "enabled" || avail === "healthy";
      }).length;
      // If availability is blank, count registered but don't claim "active".
      setToolsActive(tools.some((t) => t.availability) ? active : tools.length ? null : 0);
    } else {
      setToolsRegistered(null);
      setToolsActive(null);
    }

    if (startupRes.ok && startupRes.payload?.startup) {
      setStartup(startupRes.payload.startup);
    }
  }, []);

  const load = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    setLoading(true);
    try {
      const snapshot = await api.getSettings();
      if (!mounted.current) return;
      setCategories(snapshot.categories);
      setSettings(snapshot.settings);
      hydrateDrafts(snapshot.settings);
      syncPrefsFromSettings(snapshot.settings);
      setDesktopPerm(desktopNotificationCapability(readUiPrefsCache().desktop_notifications));
      setLoadError(null);
      setStale(false);
      setLastUpdated(new Date().toISOString());
      setStatusLine(`Loaded ${snapshot.settings.length} settings`);
      await Promise.all([loadLive(), loadBehavior()]);
    } catch (error) {
      if (!mounted.current) return;
      const message = errMsg(error, "Failed to load settings");
      setLoadError(message);
      setStatusLine(message);
      toast(message);
      if (settings.length > 0) setStale(true);
    } finally {
      inFlight.current = false;
      if (mounted.current) setLoading(false);
    }
  }, [hydrateDrafts, loadBehavior, loadLive, settings.length, toast]);

  const refresh = useCallback(async () => {
    if (inFlight.current) return;
    setRefreshing(true);
    inFlight.current = true;
    try {
      const snapshot = await api.getSettings();
      if (!mounted.current) return;
      setCategories(snapshot.categories);
      setSettings(snapshot.settings);
      // Preserve unsaved drafts — only fill missing keys from server.
      setDrafts((prev) => {
        const next = { ...prev };
        for (const item of snapshot.settings) {
          const dirty =
            JSON.stringify(prev[item.key]) !==
            JSON.stringify(item.secret ? "" : item.desired_value ?? item.effective_value);
          if (!(item.key in prev) || !dirty) {
            next[item.key] = item.secret ? "" : item.desired_value ?? item.effective_value;
          }
        }
        return next;
      });
      syncPrefsFromSettings(snapshot.settings);
      await loadLive();
      setStale(false);
      setLastUpdated(new Date().toISOString());
      setStatusLine("Vernieuwd");
    } catch (error) {
      if (!mounted.current) return;
      setStale(true);
      toast(errMsg(error, "Refresh mislukt"));
    } finally {
      inFlight.current = false;
      if (mounted.current) setRefreshing(false);
    }
  }, [loadLive, toast]);

  useEffect(() => {
    mounted.current = true;
    applyUiPreferences(readUiPrefsCache());
    void load();
    return () => {
      mounted.current = false;
    };
  }, [load]);

  useEffect(() => {
    const exists = categories.some((item) => item.id === sectionParam);
    setActiveId(exists ? sectionParam : categories[0]?.id || "algemeen");
  }, [sectionParam, categories]);

  // Auto-refresh live KPIs/providers; pause when hidden; no overlap.
  useEffect(() => {
    const ms = Math.max(5, autoRefreshSeconds) * 1000;
    const id = window.setInterval(() => {
      if (document.visibilityState === "hidden") return;
      if (inFlight.current) return;
      void loadLive();
    }, ms);
    const onVis = () => {
      if (document.visibilityState === "visible") void loadLive();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [autoRefreshSeconds, loadLive]);

  const byKey = useMemo(() => new Map(settings.map((item) => [item.key, item])), [settings]);

  const dirtyKeys = useMemo(() => {
    const dirty: string[] = [];
    for (const item of settings) {
      if (!item.editable) continue;
      const draft = drafts[item.key];
      const baseline = item.secret ? "" : item.desired_value ?? item.effective_value;
      if (item.secret) {
        if (typeof draft === "string" && draft.length > 0) dirty.push(item.key);
        continue;
      }
      if (JSON.stringify(draft) !== JSON.stringify(baseline)) dirty.push(item.key);
    }
    return dirty;
  }, [settings, drafts]);

  const dirty = dirtyKeys.length > 0;

  const selectCategory = useCallback(
    (id: string) => {
      if (dirty && id !== activeId) {
        const ok = window.confirm("Je hebt niet-opgeslagen wijzigingen. Toch van categorie wisselen?");
        if (!ok) return;
      }
      setActiveId(id);
      setQuery("");
      setSearchParams(id === "algemeen" ? {} : { section: id }, { replace: true });
    },
    [activeId, dirty, setSearchParams],
  );

  const setDraft = useCallback((key: string, value: unknown) => {
    setDrafts((prev) => ({ ...prev, [key]: value }));
  }, []);

  const saveDirty = useCallback(async () => {
    if (!dirtyKeys.length) {
      toast("Geen wijzigingen om op te slaan");
      return;
    }
    const values: Record<string, unknown> = {};
    let confirmDangerous = false;
    for (const key of dirtyKeys) {
      const setting = byKey.get(key);
      if (!setting) continue;
      if (setting.dangerous) {
        const ok = window.confirm(
          `Security-sensitive setting:\n\n${setting.label}\n\n${setting.description}\n\nConfirm change?`,
        );
        if (!ok) return;
        confirmDangerous = true;
      }
      const draft = drafts[key];
      if (setting.secret && (draft === "" || draft == null)) continue;
      values[key] = draft;
    }
    if (!Object.keys(values).length) {
      toast("Geen wijzigingen om op te slaan");
      return;
    }
    setSaving(true);
    try {
      if (values["ui.desktop_notifications"] === true) {
        const perm = await ensureDesktopNotificationPermission();
        setDesktopPerm(desktopNotificationCapability(true));
        if (perm === "denied") {
          toast("Desktop notificaties opgeslagen, maar browser-toestemming is geweigerd");
        }
      }
      const result = await api.patchSettings(values, confirmDangerous);
      setSaveReceipt(result.results);
      setSettings(result.settings);
      hydrateDrafts(result.settings);
      syncPrefsFromSettings(result.settings);
      await loadLive();
      const restart = result.results.filter((r) => r.restart_required || r.status === "RESTART_REQUIRED");
      const failed = result.results.filter((r) => r.status === "FAILED" || r.status === "INVALID" || r.status === "BLOCKED");
      const applied = result.results.filter((r) => r.status === "APPLIED" || r.status === "SAVED");
      let msg = `${applied.length} opgeslagen`;
      if (restart.length) msg += ` · ${restart.length} herstart vereist`;
      if (failed.length) msg += ` · ${failed.length} mislukt`;
      setStatusLine(msg);
      toast(msg);
    } catch (error) {
      const message = errMsg(error, "Opslaan mislukt");
      setStatusLine(message);
      toast(message);
    } finally {
      setSaving(false);
    }
  }, [byKey, dirtyKeys, drafts, hydrateDrafts, loadLive, toast]);

  const resetCategory = useCallback(
    async (category: string) => {
      const ok = window.confirm(
        `Reset categorie “${category}” naar canonieke standaardwaarden? Dit overschrijft opgeslagen overrides voor deze categorie.`,
      );
      if (!ok) return;
      setSaving(true);
      try {
        const result = await api.resetSettingsCategory(category);
        setSaveReceipt(result.results);
        setSettings((prev) => {
          const map = new Map(result.settings.map((s) => [s.key, s]));
          return prev.map((s) => map.get(s.key) ?? s);
        });
        // Full reload keeps dependent effective flags truthful.
        const snapshot = await api.getSettings();
        setSettings(snapshot.settings);
        hydrateDrafts(snapshot.settings);
        syncPrefsFromSettings(snapshot.settings);
        await loadLive();
        const msg = `Categorie ${category} gereset`;
        setStatusLine(msg);
        toast(msg);
      } catch (error) {
        toast(errMsg(error, "Reset mislukt"));
      } finally {
        setSaving(false);
      }
    },
    [hydrateDrafts, loadLive, toast],
  );

  const resetAllVisible = useCallback(async () => {
    const ok = window.confirm(
      "Reset alle zichtbare systeeminstellingen in de huidige categorie naar standaardwaarden?",
    );
    if (!ok) return;
    await resetCategory(activeId);
  }, [activeId, resetCategory]);

  const applyOne = useCallback(
    async (key: string, value: unknown, confirmDangerous = false) => {
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
        setDrafts((prev) => ({
          ...prev,
          [key]: result.setting.secret ? "" : result.setting.desired_value ?? result.setting.effective_value,
        }));
        if (UI_SETTING_KEYS.includes(key as (typeof UI_SETTING_KEYS)[number])) {
          syncPrefsFromSettings(
            settings.map((s) => (s.key === result.setting.key ? result.setting : s)),
          );
        }
        const msg = result.result.message || result.result.status;
        setStatusLine(msg);
        toast(msg);
        const snapshot = await api.getSettings();
        setSettings(snapshot.settings);
        if (key === "ui.start_with_system") await loadLive();
      } catch (error) {
        toast(errMsg(error, "Update mislukt"));
      } finally {
        setBusyKey(null);
      }
    },
    [byKey, loadLive, settings, toast],
  );

  const resetOne = useCallback(
    async (key: string) => {
      setBusyKey(key);
      try {
        const result = await api.resetSetting(key);
        setStatusLine(result.result.message);
        toast(result.result.message);
        const snapshot = await api.getSettings();
        setSettings(snapshot.settings);
        hydrateDrafts(snapshot.settings);
        syncPrefsFromSettings(snapshot.settings);
      } catch (error) {
        toast(errMsg(error, "Reset mislukt"));
      } finally {
        setBusyKey(null);
      }
    },
    [hydrateDrafts, toast],
  );

  const clearSecret = useCallback(
    async (key: string) => {
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
        toast(errMsg(error, "Clear failed"));
      } finally {
        setBusyKey(null);
      }
    },
    [toast],
  );

  const kpis: SettingsKpis = useMemo(() => {
    const sys = normalizeSystemStatus(health, healthError);
    const registered = models.length;
    const available = models.filter((m) => {
      const life = String(m.lifecycleState || "").toLowerCase();
      if (m.loaded) return true;
      if (life.includes("available") || life.includes("loaded") || life.includes("ready")) return true;
      const healthState = String(m.health || "").toLowerCase();
      return healthState === "healthy" || healthState === "ready";
    }).length;

    const ramPct = telemetry?.dashboard?.ramPct ?? null;
    const usedBytes = telemetry?.memory?.usedBytes ?? null;
    const totalBytes = telemetry?.memory?.totalBytes ?? null;
    let memoryLabel = "UNMEASURED";
    let memorySub = "Host RAM niet beschikbaar";
    if (typeof ramPct === "number") {
      memoryLabel = `${Math.round(ramPct)}%`;
      if (typeof usedBytes === "number" && typeof totalBytes === "number" && totalBytes > 0) {
        memorySub = `${(usedBytes / 1024 ** 3).toFixed(1)} GB / ${(totalBytes / 1024 ** 3).toFixed(1)} GB host RAM`;
      } else {
        memorySub = "Host RAM gebruik";
      }
    }

    return {
      systemLabel: sys.label,
      systemTone: sys.tone,
      systemOperational: sys.operational,
      modelsAvailable: models.length === 0 ? null : available,
      modelsRegistered: models.length === 0 ? null : registered,
      memoryLabel,
      memorySub,
      memoryPct: typeof ramPct === "number" ? ramPct : null,
      toolsActive,
      toolsRegistered,
      usersLabel: "1",
      usersSub: "Lokale operator (geen multi-user authority)",
      memoryHistory,
    };
  }, [health, healthError, memoryHistory, models, telemetry, toolsActive, toolsRegistered]);

  const sidebarStatus = useMemo((): SidebarStatusRow[] => {
    const lm = providers.find((p) => p.type === "lm_studio" || /lm\s*studio/i.test(p.name)) || providers[0];
    const devices = telemetry?.gpu?.devices || [];
    const mem = telemetry?.memory;
    const rows: SidebarStatusRow[] = [
      {
        id: "lm-studio",
        label: lm?.name || "LM Studio",
        value: lm ? (lm.health === "healthy" ? "Running" : lm.health) : loading ? "…" : "UNMEASURED",
        tone: lm?.health === "healthy" ? "success" : lm?.health === "offline" ? "danger" : "muted",
      },
    ];
    if (devices.length) {
      devices.slice(0, 2).forEach((gpu, i) => {
        rows.push({
          id: `gpu-${i}`,
          label: gpu.name || `GPU ${i}`,
          value: "Ready",
          tone: "success",
        });
      });
    } else {
      rows.push({
        id: "gpu-0",
        label: "GPU 0",
        value: loading ? "…" : "UNMEASURED",
        tone: "muted",
      });
    }
    const ramLabel =
      typeof mem?.usedBytes === "number" && typeof mem?.totalBytes === "number" && mem.totalBytes > 0
        ? `${(mem.usedBytes / 1024 ** 3).toFixed(1)} / ${(mem.totalBytes / 1024 ** 3).toFixed(0)} GB`
        : loading
          ? "…"
          : "UNMEASURED";
    rows.push({ id: "ram", label: "RAM", value: ramLabel, tone: "info" });
    let vramUsed = 0;
    let vramTotal = 0;
    let vramKnown = false;
    for (const d of devices) {
      if (typeof d.vramUsedBytes === "number" && typeof d.vramTotalBytes === "number") {
        vramUsed += d.vramUsedBytes;
        vramTotal += d.vramTotalBytes;
        vramKnown = true;
      }
    }
    const vramLabel = vramKnown
      ? `${(vramUsed / 1024 ** 3).toFixed(1)} / ${(vramTotal / 1024 ** 3).toFixed(0)} GB`
      : loading
        ? "…"
        : "UNMEASURED";
    rows.push({ id: "vram", label: "VRAM Totaal", value: vramLabel, tone: "info" });
    return rows;
  }, [loading, providers, telemetry]);

  const online: boolean | null = healthError ? false : health?.ok === true ? true : health ? false : null;

  const activeCategory = categories.find((c) => c.id === activeId);
  const categorySettings = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return settings.filter((s) => s.category === activeId);
    return settings.filter((s) => {
      const hay = `${s.label} ${s.description} ${s.key} ${s.category}`.toLowerCase();
      return hay.includes(q);
    });
  }, [settings, activeId, query]);

  const navCategories = useMemo(
    () =>
      [...categories].sort((a, b) => a.order - b.order).map((c) => ({
        ...c,
        icon: CATEGORY_ICONS[c.id] || "sliders",
      })),
    [categories],
  );

  const prefs = readUiPrefsCache();

  return {
    loading,
    refreshing,
    saving,
    busyKey,
    statusLine,
    loadError,
    stale,
    lastUpdated,
    online,
    sidebarStatus,
    refresh,
    load,

    categories: navCategories,
    activeId,
    activeCategory,
    selectCategory,
    query,
    setQuery,
    categorySettings,
    settings,
    drafts,
    setDraft,
    byKey,
    dirty,
    dirtyKeys,
    saveDirty,
    resetCategory,
    resetAllVisible,
    applyOne,
    resetOne,
    clearSecret,
    saveReceipt,

    providers,
    providerDrawerOpen,
    setProviderDrawerOpen,
    advancedOpen,
    setAdvancedOpen,

    kpis,
    telemetry,
    startup,
    desktopPerm,
    prefs,
    systemPanelKeys: SYSTEM_PANEL_KEYS,

    systemPrompt,
    setSystemPrompt,
    systemPromptDefault,
    systemPromptBusy,
    setSystemPromptBusy,
    systemPromptHash,
    behaviorDraft,
    setBehaviorDraft,
    reloadBehavior: loadBehavior,
    toast,
  };
}

export type SettingsWorkspace = ReturnType<typeof useSettingsWorkspace>;
