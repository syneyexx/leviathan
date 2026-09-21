"use client";

import { ChangeEvent, useCallback, useEffect, useRef, useState } from "react";
import { Activity, Check, Database, Download, HardDrive, KeyRound, Loader2, Network, RefreshCcw, RotateCcw, Save, Server, ServerOff, ShieldCheck, Upload } from "lucide-react";
import { toast } from "sonner";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { PageHeader, Panel, StatusBadge, checkStatusTone, overallHealthLabel, overallHealthTone } from "@/components/hades/ui";
import { ReleaseConfidencePanel } from "@/components/hades/release-confidence-panel";
import { HadesControlCenter } from "@/components/hades/control-center";
import { MeetDitModelPanel } from "@/components/hades/meet-dit-model-panel";
import { VoiceSettingsPanel } from "@/components/hades/voice/voice-settings-panel";
import { SpeechSettingsPanel } from "@/components/hades/speech-settings-panel";
import { NativeRuntimePanel } from "@/components/hades/native-runtime-panel";
import { AppSettings, formatBytes, hadesApi, ModelProfile, SystemHealth } from "@/lib/hades-api";
import { HADES_SETTINGS_UPDATED_EVENT } from "@/components/hades/features/settings/settings-events";
import { normalizeReasoningMode, type ProductReasoningMode } from "@/lib/reasoning-mode";

const settingTabs = ["Algemeen", "Interface", "LM Studio", "Spraak", "Python & Runtime", "Opslag", "Beveiliging", "Prestaties", "Advanced", "Logs"] as const;

type SettingTab = typeof settingTabs[number];

/** Keep API null (= Unlimited) intact; only fill missing keys from defaults. */
type SettingsForm = AppSettings;

const NULLABLE_CEILING_KEYS = [
  "request_timeout_seconds",
  "model_refresh_seconds",
  "max_concurrent_tasks",
  "max_retrieval_items",
  "max_retrieval_chars",
  "max_retrieval_chars_per_hit",
  "max_tool_rounds",
  "expert_max_cycles",
  "max_model_calls_per_task",
  "max_specialist_steps",
  "max_subtasks",
  "max_dependency_depth",
  "max_parallel_steps",
  "max_model_concurrency",
  "retrieval_diversity_window",
  "research_max_questions",
] as const;

const fallbackSettings: SettingsForm = {
  lm_studio_base_url: "http://127.0.0.1:1234/v1", lm_studio_api_key: "lm-studio",
  request_timeout_seconds: 120, model_refresh_seconds: 60, streaming: false,
  auto_connect: true, language: "nl", theme: "light", ui_style: "lux", motion_level: "standard", native_runtime_mode: "auto", max_concurrent_tasks: 2,
  file_read_policy: "allow", file_write_policy: "ask", network_policy: "block", subprocess_policy: "allow",

  reasoning_profile: "adaptive", conversation_learning: true, auto_memory_mode: "project",
  max_retrieval_items: 8, max_retrieval_chars: 6000, max_retrieval_chars_per_hit: 1200, research_default_depth: "deep",
  system_prompt: "Je bent HADES, een scherpe lokale AI-assistent.", plugin_autonomous_tools: true, auto_web_research: true,
  plugin_auto_install_dependencies: true, max_tool_rounds: 3, expert_mastery_target: 90, expert_max_cycles: 6,
  max_model_calls_per_task: 24, max_specialist_steps: 32, max_subtasks: 8, max_dependency_depth: 6,
  max_parallel_steps: 2, max_model_concurrency: 1, model_fallback_order: [], role_model_overrides: {},
  allow_cloud_model_fallback: false, retrieval_lexical_weight: 0.55, retrieval_semantic_weight: 0.45,
  retrieval_multilingual_expand: false,
  enable_semantic_retrieval: false, enable_context_compiler_chat: false, embedding_model_id: "", embedding_timeout_seconds: 30, embedding_batch_size: 16, retrieval_diversity_window: 3,
  memory_auto_promote: false, memory_write_enabled: true, memory_default_scope: "project", research_max_questions: 8,
  research_prefer_local: true,   progress_events_enabled: true, stream_provisional_text: true,
  terminal_allowlist: [], onboarding_completed_at: "",
  config_revision: 0,
  voice_enabled: true, voice_asr_provider: "faster_whisper", voice_asr_model: "base",
  voice_asr_device: "auto", voice_asr_compute_type: "auto", voice_tts_provider: "piper",
  voice_tts_voice: "nl_NL-pim-medium", voice_tts_speed: 1, voice_tts_volume: 1,
  voice_language: "nl", voice_spoken_answers_default: false, voice_speak_style: "compact",
  voice_turn_mode: "manual", voice_vad_sensitivity: 0.55, voice_vad_end_silence_ms: 900,
  voice_barge_in: true, voice_wake_word_enabled: false, voice_session_idle_seconds: 120,
  voice_keep_recordings: false, voice_input_device_id: "", voice_output_device_id: "",
  voice_setup_completed_at: "",
  spoken_answers_enabled: false, tts_provider: "none", tts_base_url: "http://127.0.0.1:3900/v1", tts_api_key: "",
  tts_voice_id: "default", tts_model: "tts-1", tts_speed: 1.0, tts_language: "nl", tts_response_format: "wav",
  tts_sentence_chunking: true, tts_min_free_ram_mb: 1500, tts_min_free_vram_mb: 0, tts_instruct: "", tts_description: "",
  stt_provider: "paste", stt_base_url: "http://127.0.0.1:3900/v1", stt_api_key: "", stt_model: "whisper-1",
  stt_language: "nl", stt_echo_guard_ms: 750,

};

/** Preserve explicit null (Unlimited). Only undefined / missing keys take fallback defaults. */
export function toSettingsForm(values: AppSettings | Partial<AppSettings>): SettingsForm {
  const incoming = { ...fallbackSettings, ...values } as SettingsForm & Record<string, unknown>;
  for (const [key, value] of Object.entries(fallbackSettings)) {
    if (incoming[key] === undefined) {
      incoming[key] = value;
    }
  }
  return incoming as SettingsForm;
}

export function diffSettingsPatch(baseline: AppSettings, current: AppSettings): Partial<AppSettings> {
  const patch: Partial<AppSettings> = {};
  const keys = new Set([...Object.keys(baseline), ...Object.keys(current)]) as Set<keyof AppSettings>;
  for (const key of keys) {
    if (key === "config_revision") continue;
    if (JSON.stringify(baseline[key]) !== JSON.stringify(current[key])) {
      (patch as Record<string, unknown>)[key] = current[key];
    }
  }
  return patch;
}

function nullableNumberDisplay(value: number | null | undefined): string {
  return value === null || value === undefined ? "" : String(value);
}

function parseNullableNumber(raw: string): number | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  const n = Number(trimmed);
  return Number.isFinite(n) ? n : null;
}

type PolicyKey = "file_read_policy" | "file_write_policy" | "network_policy" | "subprocess_policy";

export function SettingsPage() {
  const [activeTab, setActiveTab] = useState<SettingTab>("LM Studio");
  const [settings, setSettingsState] = useState<SettingsForm>(fallbackSettings);
  const baselineRef = useRef<SettingsForm>(fallbackSettings);
  const settingsRef = useRef<SettingsForm>(fallbackSettings);
  const [configRevision, setConfigRevisionState] = useState(0);
  const configRevisionRef = useRef(0);
  const [activeProfile, setActiveProfile] = useState<ModelProfile | null>(null);
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [storage, setStorage] = useState({ path: "backend/data/hades.db", size_bytes: 0 });
  const [restoreArchivePath, setRestoreArchivePath] = useState("");
  const [restoreBusy, setRestoreBusy] = useState(false);
  const [version, setVersion] = useState("—");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [healthRefreshing, setHealthRefreshing] = useState(false);
  const [applyingUiStyle, setApplyingUiStyle] = useState(false);
  const [persistingPolicy, setPersistingPolicy] = useState<PolicyKey | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  /** Keep a sync ref so Select→ghost-click→Save in the same turn still sees the new value. */
  const setSettings = (next: SettingsForm | ((prev: SettingsForm) => SettingsForm)) => {
    if (typeof next === "function") {
      setSettingsState((prev) => {
        const resolved = next(prev);
        settingsRef.current = resolved;
        return resolved;
      });
      return;
    }
    settingsRef.current = next;
    setSettingsState(next);
  };

  const setConfigRevision = (revision: number) => {
    configRevisionRef.current = revision;
    setConfigRevisionState(revision);
  };

  useEffect(() => {
    const tab = sessionStorage.getItem("hades-settings-tab");
    if (tab && (settingTabs as readonly string[]).includes(tab)) {
      setActiveTab(tab as SettingTab);
      sessionStorage.removeItem("hades-settings-tab");
    }
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [config, status, modelData] = await Promise.all([hadesApi.settings(), hadesApi.health(), hadesApi.models().catch(() => null)]);
      const form = toSettingsForm(config.values);
      setSettings(form);
      baselineRef.current = form;
      setConfigRevision(Number(config.config_revision ?? form.config_revision ?? 0));
      setActiveProfile(modelData?.active_profile ?? null);
      setStorage(config.storage);
      setVersion(config.version);
      setHealth(status);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Instellingen laden is mislukt.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const applyLiveDocumentStyle = (values: Pick<AppSettings, "language" | "theme" | "ui_style" | "motion_level">) => {
    document.documentElement.lang = values.language;
    document.documentElement.dataset.theme = values.theme;
    document.documentElement.style.colorScheme = values.theme === "system" ? "light dark" : values.theme;
    document.documentElement.dataset.hadesStyle = values.ui_style;
    document.documentElement.dataset.motion = values.motion_level;
  };

  const commitPatchedKeys = (
    saved: SettingsForm,
    revision: number,
    keys: Array<keyof AppSettings>,
  ) => {
    const patchLocal: Partial<SettingsForm> = { config_revision: revision };
    for (const key of keys) {
      (patchLocal as Record<string, unknown>)[key as string] = saved[key];
    }
    const merged = { ...settingsRef.current, ...patchLocal };
    setSettings(merged);
    baselineRef.current = { ...baselineRef.current, ...patchLocal };
    setConfigRevision(revision);
    applyLiveDocumentStyle({
      language: merged.language,
      theme: merged.theme,
      ui_style: merged.ui_style,
      motion_level: merged.motion_level,
    });
    window.dispatchEvent(new CustomEvent(HADES_SETTINGS_UPDATED_EVENT, { detail: patchLocal }));
  };

  const applyUiStylePreset = async (style: AppSettings["ui_style"]) => {
    if (applyingUiStyle || settingsRef.current.ui_style === style) return;
    setApplyingUiStyle(true);
    try {
      const result = await hadesApi.patchSettings({ ui_style: style }, configRevisionRef.current);
      const form = toSettingsForm(result.values);
      commitPatchedKeys(form, Number(result.config_revision ?? form.config_revision ?? configRevisionRef.current + 1), ["ui_style"]);
      if (style === "finalbeta") {
        window.location.hash = "#/fb/dashboard";
        toast.success("FINALBETA actief.");
      } else {
        window.location.hash = "#/settings";
        toast.success("HADES Lux Atelier actief.");
      }
    } catch (reason) {
      // Offline / backend down: apply locally without claiming persistence.
      const local = { ...settingsRef.current, ui_style: style };
      commitPatchedKeys(local, configRevisionRef.current, ["ui_style"]);
      if (style === "finalbeta") window.location.hash = "#/fb/dashboard";
      else window.location.hash = "#/settings";
      const detail = reason instanceof Error ? reason.message : "Interface-preset opslaan is mislukt.";
      toast.message(`${style === "finalbeta" ? "FINALBETA" : "Lux Atelier"} lokaal toegepast. Niet opgeslagen: ${detail}`);
      if (reason && typeof reason === "object" && "status" in reason && (reason as { status: number }).status === 409) {
        await load();
      }
    } finally {
      setApplyingUiStyle(false);
    }
  };

  const applyMotionLevel = async (level: AppSettings["motion_level"]) => {
    if (settingsRef.current.motion_level === level) return;
    try {
      const result = await hadesApi.patchSettings({ motion_level: level }, configRevisionRef.current);
      const form = toSettingsForm(result.values);
      commitPatchedKeys(form, Number(result.config_revision ?? form.config_revision ?? configRevisionRef.current + 1), ["motion_level"]);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Motion level opslaan is mislukt.");
      if (reason && typeof reason === "object" && "status" in reason && (reason as { status: number }).status === 409) {
        await load();
      }
    }
  };

  const persistPolicy = async (key: PolicyKey, value: AppSettings[PolicyKey]) => {
    if (settingsRef.current[key] === value || persistingPolicy) return;
    const previous = settingsRef.current[key];
    setSettings({ ...settingsRef.current, [key]: value });
    setPersistingPolicy(key);
    try {
      let result: { values: AppSettings; config_revision?: number };
      try {
        result = await hadesApi.patchSettings({ [key]: value }, configRevisionRef.current);
      } catch (reason) {
        const isRevisionConflict = reason && typeof reason === "object" && "status" in reason
          && (reason as { status: number }).status === 409;
        if (!isRevisionConflict) throw reason;

        const latest = await hadesApi.settings();
        const latestRevision = Number(
          latest.config_revision ?? latest.values.config_revision ?? configRevisionRef.current,
        );
        setConfigRevision(latestRevision);
        result = await hadesApi.patchSettings({ [key]: value }, latestRevision);
      }
      const form = toSettingsForm(result.values);
      if (form[key] !== value) {
        throw new Error(`Beleid '${key}' is niet bevestigd door de backend (kreeg '${String(form[key])}').`);
      }
      commitPatchedKeys(form, Number(result.config_revision ?? form.config_revision ?? configRevisionRef.current + 1), [key]);
      const labels: Record<PolicyKey, string> = {
        file_read_policy: "Bestanden lezen",
        file_write_policy: "Bestanden schrijven",
        network_policy: "Netwerk",
        subprocess_policy: "Subprocess",
      };
      const valueLabel = value === "allow" ? "toegestaan" : value === "ask" ? "eerst vragen" : "geblokkeerd";
      toast.success(`${labels[key]} opgeslagen: ${valueLabel}.`);
    } catch (reason) {
      setSettings({ ...settingsRef.current, [key]: previous });
      toast.error(reason instanceof Error ? reason.message : "Beleid opslaan is mislukt.");
      if (reason && typeof reason === "object" && "status" in reason && (reason as { status: number }).status === 409) {
        await load();
      }
    } finally {
      setPersistingPolicy(null);
    }
  };

  const applyPolicyPreset = (preset: "paranoid" | "normal" | "lab") => {
    if (preset === "paranoid") {
      setSettings({
        ...settingsRef.current,
        file_read_policy: "ask",
        file_write_policy: "block",
        network_policy: "block",
        plugin_autonomous_tools: false,
        auto_web_research: false,
      });
      toast.message("Preset Paranoid geladen — nog opslaan.");
      return;
    }
    if (preset === "lab") {
      setSettings({
        ...settingsRef.current,
        file_read_policy: "allow",
        file_write_policy: "ask",
        network_policy: "allow",
        plugin_autonomous_tools: true,
        auto_web_research: true,
      });
      toast.message("Preset Lab geladen — nog opslaan. Geschikt voor geautoriseerde harvests.");
      return;
    }
    setSettings({
      ...settingsRef.current,
      file_read_policy: "allow",
      file_write_policy: "ask",
      network_policy: "block",
      plugin_autonomous_tools: true,
      auto_web_research: true,
    });
    toast.message("Preset Normal geladen — nog opslaan.");
  };

  const save = async () => {
    setSaving(true);
    try {
      const current = settingsRef.current;
      const patch = diffSettingsPatch(baselineRef.current, current);
      const hasPatch = Object.keys(patch).length > 0;
      const hasProfile = Boolean(activeProfile?.model_id);
      if (!hasPatch && !hasProfile) {
        toast.message("Geen wijzigingen om op te slaan.");
        return;
      }
      let resultValues = current;
      if (hasPatch) {
        const result = await hadesApi.patchSettings(patch, configRevisionRef.current);
        resultValues = toSettingsForm(result.values);
        for (const key of Object.keys(patch) as Array<keyof AppSettings>) {
          if (JSON.stringify(resultValues[key]) !== JSON.stringify(patch[key])) {
            throw new Error(`Instelling '${String(key)}' is niet bevestigd door de backend.`);
          }
        }
        setSettings(resultValues);
        baselineRef.current = resultValues;
        setConfigRevision(Number(result.config_revision ?? resultValues.config_revision ?? configRevisionRef.current + 1));
      }
      if (activeProfile?.model_id) {
        const savedProfile = await hadesApi.saveModelProfile(activeProfile.model_id, {
          temperature: activeProfile.temperature, top_p: activeProfile.top_p, top_k: activeProfile.top_k,
          max_tokens: activeProfile.max_tokens, repeat_penalty: activeProfile.repeat_penalty, seed: activeProfile.seed,
          system_prompt: activeProfile.system_prompt, make_active: true,
        });
        setActiveProfile(savedProfile);
      }
      applyLiveDocumentStyle(resultValues);
      window.dispatchEvent(new CustomEvent(HADES_SETTINGS_UPDATED_EVENT, { detail: resultValues }));
      if (!hasPatch && hasProfile) {
        toast.success("Modelprofiel opgeslagen.");
      } else {
        const unlimitedKept = NULLABLE_CEILING_KEYS.filter((key) => resultValues[key] === null);
        toast.success(
          unlimitedKept.length
            ? `Opgeslagen (rev ${resultValues.config_revision ?? configRevisionRef.current}). Unlimited behouden: ${unlimitedKept.join(", ")}.`
            : "Instellingen lokaal opgeslagen en live toegepast.",
        );
      }
      setHealth(await hadesApi.health());
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Opslaan is mislukt.");
      if (reason && typeof reason === "object" && "status" in reason && (reason as { status: number }).status === 409) {
        await load();
      }
    } finally {
      setSaving(false);
    }
  };

  const test = async () => {
    setTesting(true);
    try {
      const result = await hadesApi.testConnection(settings);
      if (!result.connected || Number(result.models || 0) <= 0) {
        toast.error("LM Studio bereikbaar zonder geladen model.");
      } else {
        toast.success(`LM Studio reageert: ${result.models} model(len), ${result.latency_ms} ms.`);
      }
      setHealth(await hadesApi.health());
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Verbindingstest is mislukt.");
    } finally {
      setTesting(false);
    }
  };

  const refreshHealth = async () => {
    setHealthRefreshing(true);
    try {
      setHealth(await hadesApi.health());
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Gezondheid laden is mislukt.");
      setHealth(null);
    } finally {
      setHealthRefreshing(false);
    }
  };

  const backup = async () => {
    try {
      const result = await hadesApi.backupDatabase();
      toast.success(`SQLite-backup (alleen DB) gemaakt: ${result.path}`);
      await load();
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Backup maken is mislukt.");
    }
  };


  const workspaceRestore = async () => {
    const archive = restoreArchivePath.trim();
    if (!archive) {
      toast.error("Geef een archive-pad op om te herstellen.");
      return;
    }
    setRestoreBusy(true);
    try {
      const result = await hadesApi.workspaceRestore({ archive_path: archive });
      if (result.ok === false || result.error) {
        toast.error(String(result.error || result.message || "Restore mislukt (fail-closed)."));
      } else {
        toast.success(
          typeof result.isolated_target === "string"
            ? `Restore naar geïsoleerde map: ${result.isolated_target}`
            : "Restore voorbereid in geïsoleerde map (live DB niet vervangen).",
        );
      }
      await load();
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Workspace-restore is mislukt.");
    } finally {
      setRestoreBusy(false);
    }
  };

  const workspaceBackup = async () => {
    try {
      const result = await hadesApi.workspaceBackup({});
      const path = typeof result.archive_path === "string" ? result.archive_path : "";
      const phase = String(result.phase || "");
      if (
        (phase === "completed" || phase === "completed_with_warnings")
        && path.trim().length > 0
      ) {
        toast.success(`Volledige workspace-archive gemaakt: ${path}`);
      } else {
        toast.error(
          path
            ? `Workspace-backup niet succesvol (${phase || "onbekend"}): ${path}`
            : `Workspace-backup niet succesvol (${phase || "geen archief"}).`,
        );
      }
      await load();
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Workspace-backup is mislukt.");
    }
  };

  const reset = async () => {
    try {
      const result = await hadesApi.resetSettings();
      const form = toSettingsForm(result.values);
      setSettings(form);
      baselineRef.current = form;
      setConfigRevision(Number(form.config_revision ?? 0));
      window.dispatchEvent(new CustomEvent(HADES_SETTINGS_UPDATED_EVENT, { detail: form }));
      toast.success("Standaardinstellingen hersteld.");
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Herstellen is mislukt.");
    }
  };

  const exportConfig = () => {
    const blob = new Blob([JSON.stringify({ version: 1, settings }, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "hades-configuratie.json";
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const importConfig = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    try {
      const parsed = JSON.parse(await file.text()) as unknown;
      if (!parsed || typeof parsed !== "object") throw new Error("Ongeldig configuratiebestand.");
      const record = parsed as Record<string, unknown>;
      const values = (record.settings && typeof record.settings === "object" ? record.settings : record) as Partial<AppSettings>;
      if (!values.lm_studio_base_url) throw new Error("Ongeldig configuratiebestand.");
      const result = await hadesApi.saveSettings({ ...fallbackSettings, ...values });
      const form = toSettingsForm(result.values);
      setSettings(form);
      baselineRef.current = form;
      setConfigRevision(Number(result.config_revision ?? form.config_revision ?? 0));
      window.dispatchEvent(new CustomEvent(HADES_SETTINGS_UPDATED_EVENT, { detail: form }));
      toast.success("Configuratie geïmporteerd en opgeslagen.");
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Importeren is mislukt.");
    }
  };

  return (
    <div className="page page-settings">
      <PageHeader title="Instellingen" description="Beheer de lokale API, runtime, opslag en standaardrechten." actions={loading ? <Loader2 className="spin muted-icon" /> : <Button type="button" onClick={() => void save()} disabled={saving || persistingPolicy !== null}>{saving ? <Loader2 className="spin" /> : <Save />}Alles opslaan</Button>} />
      <div className="settings-layout">
        <aside className="settings-nav">{settingTabs.map((tab) => <button className={tab === activeTab ? "active" : ""} type="button" key={tab} onClick={() => setActiveTab(tab)}>{tab}</button>)}</aside>
        <div className="settings-main">
          {activeTab === "Algemeen" ? <div className="settings-top-grid"><Panel title="Algemeen gedrag"><div className="form-grid two"><label><span>Taal</span><Select value={settings.language} onValueChange={(value: "nl" | "en") => setSettings({ ...settings, language: value })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="nl">Nederlands</SelectItem><SelectItem value="en">Engels</SelectItem></SelectContent></Select></label><label><span>Weergave</span><Select value={settings.theme} onValueChange={(value: AppSettings["theme"]) => setSettings({ ...settings, theme: value })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="light">Licht</SelectItem><SelectItem value="dark">Donker</SelectItem><SelectItem value="system">Systeem</SelectItem></SelectContent></Select></label></div><div className="form-grid two"><label><span>Modelverversing</span><Select value={settings.model_refresh_seconds == null ? "unlimited" : String(settings.model_refresh_seconds)} onValueChange={(value) => setSettings({ ...settings, model_refresh_seconds: value === "unlimited" ? null : Number(value) })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="30">30 seconden</SelectItem><SelectItem value="60">60 seconden</SelectItem><SelectItem value="300">5 minuten</SelectItem><SelectItem value="unlimited">Unlimited</SelectItem></SelectContent></Select></label></div><div className="toggle-lines"><label><span><strong>Automatisch verbinden</strong><small>Controleer LM Studio bij het openen.</small></span><Switch checked={settings.auto_connect} onCheckedChange={(checked) => setSettings({ ...settings, auto_connect: checked })} /></label><label><span><strong>Streamingvoorkeur</strong><small>Bewaar voorkeur voor modellen/runtimes die streaming ondersteunen.</small></span><Switch checked={settings.streaming} onCheckedChange={(checked) => setSettings({ ...settings, streaming: checked })} /></label><label><span><strong>Gesprekken als kennis indexeren</strong><small>Volledige chats blijven archiveerbaar en relevante inhoud wordt terugvindbaar.</small></span><Switch checked={settings.conversation_learning} onCheckedChange={(checked) => setSettings({ ...settings, conversation_learning: checked })} /></label></div><div className="form-grid two"><label><span>Denkdiepte</span><Select value={normalizeReasoningMode(settings.reasoning_profile)} onValueChange={(value: ProductReasoningMode) => setSettings({ ...settings, reasoning_profile: value })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="adaptive">Adaptive</SelectItem><SelectItem value="normal">Normal</SelectItem><SelectItem value="medium">Medium</SelectItem><SelectItem value="high">High</SelectItem></SelectContent></Select></label><label><span>Auto-memory</span><Select value={settings.auto_memory_mode} onValueChange={(value: AppSettings["auto_memory_mode"]) => setSettings({ ...settings, auto_memory_mode: value })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="off">Uit</SelectItem><SelectItem value="project">Projectkennis</SelectItem><SelectItem value="all">Breed</SelectItem></SelectContent></Select></label></div><div className="form-grid two"><label><span>Retrieval limiet</span><Input type="number" min={1} max={30} value={nullableNumberDisplay(settings.max_retrieval_items)} onChange={(event) => setSettings({ ...settings, max_retrieval_items: parseNullableNumber(event.target.value) })} /></label><label><span>Max. retrieval tekens</span><Input type="number" min={500} max={40000} value={nullableNumberDisplay(settings.max_retrieval_chars)} onChange={(event) => setSettings({ ...settings, max_retrieval_chars: parseNullableNumber(event.target.value) })} /><small>Totaalbudget voor non-dumping RAG-pack.</small></label><label><span>Max. tekens per hit</span><Input type="number" min={200} max={8000} value={nullableNumberDisplay(settings.max_retrieval_chars_per_hit)} onChange={(event) => setSettings({ ...settings, max_retrieval_chars_per_hit: parseNullableNumber(event.target.value) })} /></label><label><span>Standaard researchdiepte</span><Select value={settings.research_default_depth} onValueChange={(value: AppSettings["research_default_depth"]) => setSettings({ ...settings, research_default_depth: value })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="quick">Quick</SelectItem><SelectItem value="standard">Standard</SelectItem><SelectItem value="deep">Deep</SelectItem><SelectItem value="expert">Expert</SelectItem></SelectContent></Select></label></div><label className="form-stack"><span>Globale system prompt</span><Textarea value={settings.system_prompt} onChange={(event) => setSettings({ ...settings, system_prompt: event.target.value })} className="memory-content" /><small>Nieuwe en bestaande chats zonder eigen override gebruiken deze prompt direct na Opslaan.</small></label><div className="toggle-lines"><label><span><strong>Plugins autonoom gebruiken</strong><small>Enabled plugins mogen door de bot worden gekozen als ze de taak verbeteren; Block-rechten blijven blokkeren.</small></span><Switch checked={settings.plugin_autonomous_tools} onCheckedChange={(checked) => setSettings({ ...settings, plugin_autonomous_tools: checked })} /></label><label><span><strong>Actuele webkennis automatisch ophalen</strong><small>Bij actuele/webvragen gebruikt HADES internet als netwerk niet geblokkeerd is; offline valt hij terug op lokale kennis.</small></span><Switch checked={settings.auto_web_research} onCheckedChange={(checked) => setSettings({ ...settings, auto_web_research: checked })} /></label><label><span><strong>Plugin-dependencies automatisch installeren</strong><small>Python/Node/plugin-lokale dependencies worden bij import standaard voorbereid.</small></span><Switch checked={settings.plugin_auto_install_dependencies} onCheckedChange={(checked) => setSettings({ ...settings, plugin_auto_install_dependencies: checked })} /></label></div><div className="form-grid two"><label><span>Max. autonome toolrondes</span><Input type="number" min={0} max={8} value={nullableNumberDisplay(settings.max_tool_rounds)} onChange={(event) => setSettings({ ...settings, max_tool_rounds: parseNullableNumber(event.target.value) })} /></label></div><div className="form-grid two"><label><span>Expert mastery target</span><Input type="number" min={60} max={100} value={settings.expert_mastery_target} onChange={(event) => setSettings({ ...settings, expert_mastery_target: Number(event.target.value) })} /><small>Drempel voor Research Expert-modus (60–100).</small></label><label><span>Expert max. cycli</span><Input type="number" min={1} max={20} value={nullableNumberDisplay(settings.expert_max_cycles)} onChange={(event) => setSettings({ ...settings, expert_max_cycles: parseNullableNumber(event.target.value) })} /><small>Standaard aantal researchrondes in Expert-modus (per-project override op de Research-pagina).</small></label></div></Panel><Panel title="Configuratiebestand"><p className="panel-copy">Exporteer of importeer alle instellingen als leesbaar JSON-bestand.</p><div className="config-actions"><Button variant="outline" onClick={exportConfig}><Download />Exporteer</Button><Button variant="outline" onClick={() => fileInput.current?.click()}><Upload />Importeer</Button></div></Panel></div> : null}

          {activeTab === "Interface" ? <div className="settings-top-grid"><Panel title="Interface"><p className="panel-copy">Kies de actieve HADES-interface. Lux Atelier blijft de standaard productGUI. FINALBETA is een geïsoleerde Phase 1-visualisatie en wordt nog niet de standaard.</p><div className="interface-preset-grid" role="group" aria-label="Interface"><button type="button" className={`interface-preset-card interface-preset-card--lux${settings.ui_style === "finalbeta" ? " active" : ""}`} aria-pressed={settings.ui_style !== "finalbeta"} disabled={applyingUiStyle || settings.ui_style !== "finalbeta"} onClick={() => void applyUiStylePreset("lux")}><strong>HADES Lux</strong><small>Huidige productinterface — alle functies verbonden.</small></button><button type="button" className={`interface-preset-card${settings.ui_style === "finalbeta" ? " active" : ""}`} aria-pressed={settings.ui_style === "finalbeta"} disabled={applyingUiStyle || settings.ui_style === "finalbeta"} onClick={() => void applyUiStylePreset("finalbeta")}><strong>FINALBETA</strong><small>Nieuwe visuele shell — Phase 1 mock/prototype navigatie.</small></button></div></Panel><Panel title="Beweging"><label className="form-stack"><span>Motion level</span><Select value={settings.motion_level} onValueChange={(value: AppSettings["motion_level"]) => void applyMotionLevel(value)}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="reduced">Reduced</SelectItem><SelectItem value="standard">Standard</SelectItem><SelectItem value="cinematic">Cinematic</SelectItem></SelectContent></Select><small>Direct toegepast. De systeemvoorkeur voor gereduceerde beweging heeft altijd voorrang.</small></label></Panel></div> : null}

          {activeTab === "LM Studio" ? <div className="settings-top-grid"><Panel title="LM Studio-verbinding"><div className="form-stack"><label><span>Base endpoint</span><Input value={settings.lm_studio_base_url} onChange={(event) => setSettings({ ...settings, lm_studio_base_url: event.target.value })} /></label><label><span>API-key <small>optioneel</small></span><div className="input-with-icon"><KeyRound /><Input type="password" value={settings.lm_studio_api_key} onChange={(event) => setSettings({ ...settings, lm_studio_api_key: event.target.value })} /></div></label></div><div className="form-grid two"><label><span>Verversinterval modellen</span><Input type="number" min={10} max={3600} value={nullableNumberDisplay(settings.model_refresh_seconds)} onChange={(event) => setSettings({ ...settings, model_refresh_seconds: parseNullableNumber(event.target.value) })} /></label><label><span>Request-timeout</span><Input type="number" min={5} max={900} value={nullableNumberDisplay(settings.request_timeout_seconds)} onChange={(event) => setSettings({ ...settings, request_timeout_seconds: parseNullableNumber(event.target.value) })} /></label></div><div className="button-row end"><Button variant="outline" onClick={test} disabled={testing}>{testing ? <Loader2 className="spin" /> : <Activity />}Verbinding testen</Button><Button type="button" onClick={() => void save()} disabled={saving || persistingPolicy !== null}><Save />Opslaan</Button></div></Panel><Panel title="Actieve botparameters"><div className="form-grid two">{activeProfile ? <><label><span>Temperature</span><Input type="number" min={0} max={2} step={0.05} value={activeProfile.temperature} onChange={(event) => setActiveProfile({ ...activeProfile, temperature: Number(event.target.value) })} /></label><label><span>Top P</span><Input type="number" min={0.01} max={1} step={0.01} value={activeProfile.top_p} onChange={(event) => setActiveProfile({ ...activeProfile, top_p: Number(event.target.value) })} /></label><label><span>Top K</span><Input type="number" min={0} max={500} value={activeProfile.top_k} onChange={(event) => setActiveProfile({ ...activeProfile, top_k: Number(event.target.value) })} /></label><label><span>Max tokens</span><Input type="number" min={1} max={131072} value={activeProfile.max_tokens} onChange={(event) => setActiveProfile({ ...activeProfile, max_tokens: Number(event.target.value) })} /></label><label><span>Repeat penalty</span><Input type="number" min={0.5} max={2} step={0.01} value={activeProfile.repeat_penalty} onChange={(event) => setActiveProfile({ ...activeProfile, repeat_penalty: Number(event.target.value) })} /></label><label><span>Seed</span><Input type="number" min={-1} value={activeProfile.seed} onChange={(event) => setActiveProfile({ ...activeProfile, seed: Number(event.target.value) })} /></label></> : <p className="empty-copy">Geen actief modelprofiel geladen.</p>}</div>{activeProfile ? <label className="form-stack"><span>Model system prompt</span><Textarea value={activeProfile.system_prompt} onChange={(event) => setActiveProfile({ ...activeProfile, system_prompt: event.target.value })} className="memory-content" /><small>Profielprompt voor het actieve model. De globale system prompt onder Algemeen heeft voorrang voor chats zonder eigen override.</small></label> : null}<small>Deze waarden worden samen met Opslaan direct op het actieve modelprofiel toegepast.</small></Panel><Panel title="Verbindingsdiagnostiek" actions={<StatusBadge tone={health?.lm_studio === "connected" ? "success" : "warning"}>{health?.lm_studio === "connected" ? "Verbonden" : "Offline"}</StatusBadge>}><div className="diagnostic-hero"><span className="service-icon">{health?.lm_studio === "connected" ? <Server /> : <ServerOff />}</span><div><strong>LM Studio</strong><span>OpenAI-compatibele lokale API</span></div></div><dl className="detail-list spaced"><div><dt>Actief model</dt><dd>{health?.active_model || "Niet ingesteld"}</dd></div><div><dt>Gevonden modellen</dt><dd>{health?.models ?? 0}</dd></div><div><dt>Latency</dt><dd>{health?.latency_ms ? `${health.latency_ms} ms` : "—"}</dd></div><div><dt>Laatste fout</dt><dd>{health?.detail || "Geen"}</dd></div></dl><Button variant="outline" onClick={() => load()}><RefreshCcw />Diagnostiek vernieuwen</Button></Panel></div> : null}

          {activeTab === "Python & Runtime" ? <div className="service-grid settings-service-grid"><Panel title="Python / FastAPI"><div className="service-card"><span className="service-icon"><Network /></span><StatusBadge tone={health?.backend === "ok" ? "success" : "danger"}>{health?.backend === "ok" ? "Actief" : "Onbereikbaar"}</StatusBadge><dl><span>URL <b>127.0.0.1:8000</b></span><span>Versie <b>{version}</b></span><span>API <b>/api</b></span></dl><Button variant="outline" onClick={() => load()}>Bridge testen</Button></div></Panel><Panel title="Lokale taakruntime"><div className="service-card"><span className="service-icon"><ShieldCheck /></span><StatusBadge tone="success">Begrensd</StatusBadge><dl><span>Max. gelijktijdig <b>{settings.max_concurrent_tasks}</b></span><span>Plugin subprocess <b>Alleen geïsoleerde Ready-tools</b></span><span>Internet <b>{settings.network_policy === "block" ? "Geblokkeerd" : "Volgens beleid"}</b></span></dl><label className="form-stack"><span>Maximaal gelijktijdige taken</span><Input type="number" min={1} max={8} value={nullableNumberDisplay(settings.max_concurrent_tasks)} onChange={(event) => setSettings({ ...settings, max_concurrent_tasks: parseNullableNumber(event.target.value) })} /><small>Zelfde limiet als onder Prestaties; geldt direct voor de Work Runtime-scheduler.</small></label><label className="form-stack"><span>Native runtime</span><Select value={settings.native_runtime_mode} onValueChange={(value: AppSettings["native_runtime_mode"]) => setSettings({ ...settings, native_runtime_mode: value })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="auto">Automatisch</SelectItem><SelectItem value="enabled">Ingeschakeld</SelectItem><SelectItem value="disabled">Uitgeschakeld</SelectItem></SelectContent></Select><small>De native runtime blijft beschikbaar; deze voorkeur bepaalt alleen de gevraagde modus.</small></label></div></Panel></div> : null}

          {activeTab === "Opslag" ? <div className="service-grid settings-service-grid"><Panel title="SQLite (alleen database)"><div className="service-card"><span className="service-icon"><Database /></span><StatusBadge tone="success">Gezond</StatusBadge><dl><span>Pad <b className="break-path">{storage.path}</b></span><span>Grootte <b>{formatBytes(storage.size_bytes)}</b></span><span>Modus <b>WAL + foreign keys</b></span><span>Soort <b>DB-only — geen volledige workspace-backup</b></span></dl><Button variant="outline" onClick={backup}><HardDrive />SQLite-backup maken</Button></div></Panel><Panel title="Volledige workspace-archive"><div className="service-card"><span className="service-icon"><HardDrive /></span><StatusBadge tone="neutral">Apart van SQLite-backup</StatusBadge><dl><span>Inhoud <b>DB + evidence + artifacts + plugins + knowledge</b></span><span>Grote caches/modellen <b>standaard uitgesloten (selecteerbaar)</b></span><span>Restore <b>eerst naar geïsoleerde map + overzicht</b></span></dl><div className="flex flex-col gap-2">
<Button variant="outline" onClick={workspaceBackup}><HardDrive />Backup now</Button>
<label className="grid gap-1 text-xs"><span>Restore archive pad</span>
<Input value={restoreArchivePath} onChange={(event) => setRestoreArchivePath(event.target.value)} placeholder="C:\\HADES\\backups\\workspace.zip" />
</label>
<Button variant="outline" disabled={restoreBusy || !restoreArchivePath.trim()} onClick={() => void workspaceRestore()}>
{restoreBusy ? "Bezig…" : "Restore…"}
</Button>
<p className="m-0 text-[10px] text-muted-foreground">Restore is fail-closed naar een geïsoleerde map; live DB wordt nooit stil vervangen. Nieuwere/incompatibele schema&apos;s worden geweigerd.</p>
</div></div></Panel><Panel title="Wat wordt bewaard"><div className="check-list"><span><Check />Gesprekken en berichten</span><span><Check />Taken, resultaten en logs</span><span><Check />Geheugen, Brain-nodes en instellingen</span><span><Check />Knowledge Library, Research, plugins en agents</span></div></Panel></div> : null}

          {activeTab === "Beveiliging" ? <div className="policy-grid settings-policy-grid"><Panel title="Local-only & privacy"><div className="check-list"><span><Check />Lokale opslag en standaard lokale modelendpoint</span><span><Check />Geen HADES-telemetrie of analytics</span><span><Check />Externe netwerkacties alleen volgens expliciet beleid</span><span><Check />Geen hardcoded morele contentfilters — gedrag via system prompt / model</span></div></Panel><Panel title="Beleids-presets"><div className="button-row" style={{ flexWrap: "wrap", gap: 8 }}><Button variant="outline" onClick={() => applyPolicyPreset("paranoid")}>Paranoid</Button><Button variant="outline" onClick={() => applyPolicyPreset("normal")}>Normal</Button><Button variant="outline" onClick={() => applyPolicyPreset("lab")}>Lab</Button></div><small>Paranoid = netwerk/schrijven dicht. Normal = standaard lokaal. Lab = netwerk allow voor harvest/research. Presets laden lokaal — daarna “Overige rechten opslaan” of Alles opslaan. Individuele rechten hieronder slaan direct op.</small></Panel><Panel title="Standaardrechten"><div className="select-list"><label>Bestanden lezen<Select value={settings.file_read_policy} disabled={persistingPolicy !== null || saving} onValueChange={(value: AppSettings["file_read_policy"]) => void persistPolicy("file_read_policy", value)}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="allow">Toegestaan</SelectItem><SelectItem value="ask">Eerst vragen</SelectItem><SelectItem value="block">Geblokkeerd</SelectItem></SelectContent></Select></label><label>Bestanden schrijven<Select value={settings.file_write_policy} disabled={persistingPolicy !== null || saving} onValueChange={(value: AppSettings["file_write_policy"]) => void persistPolicy("file_write_policy", value)}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="allow">Toegestaan</SelectItem><SelectItem value="ask">Eerst vragen</SelectItem><SelectItem value="block">Geblokkeerd</SelectItem></SelectContent></Select></label><label>Netwerk<Select value={settings.network_policy} disabled={persistingPolicy !== null || saving} onValueChange={(value: AppSettings["network_policy"]) => void persistPolicy("network_policy", value)}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="allow">Toegestaan</SelectItem><SelectItem value="ask">Eerst vragen</SelectItem><SelectItem value="block">Geblokkeerd</SelectItem></SelectContent></Select></label><label>Subprocess<Select value={settings.subprocess_policy} disabled={persistingPolicy !== null || saving} onValueChange={(value: AppSettings["subprocess_policy"]) => void persistPolicy("subprocess_policy", value)}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="allow">Toegestaan</SelectItem><SelectItem value="ask">Eerst vragen</SelectItem><SelectItem value="block">Geblokkeerd</SelectItem></SelectContent></Select></label></div><small>Wijzigingen aan standaardrechten worden direct opgeslagen (geen aparte opslaan-stap).</small><Button type="button" onClick={() => void save()} disabled={saving || persistingPolicy !== null}>{saving ? <Loader2 className="spin" /> : <Save />}{persistingPolicy ? "Beleid opslaan…" : "Overige rechten opslaan"}</Button></Panel><Panel title="Terminal allowlist"><label className="form-stack"><span>Toegestane commando&apos;s <small>optioneel, kommagescheiden</small></span><Input value={(settings.terminal_allowlist || []).join(", ")} onChange={(event) => setSettings({ ...settings, terminal_allowlist: event.target.value.split(",").map((item) => item.trim()).filter(Boolean) })} placeholder="python, git, pytest" /><small>Leeg = ingebouwde standaardlijst. Alleen expliciet toegestane binaries worden uitgevoerd.</small></label></Panel><Panel title="Onboarding"><label className="form-stack"><span>Voltooid op <small>ISO-timestamp of leeg</small></span><Input value={settings.onboarding_completed_at || ""} onChange={(event) => setSettings({ ...settings, onboarding_completed_at: event.target.value })} placeholder="leeg = nog niet afgerond" /><small>Leegmaken heropent de 3-minuten onboarding-flow.</small></label></Panel><Panel title="Systeemgezondheid" actions={<StatusBadge tone={overallHealthTone(health)}>{overallHealthLabel(health)}</StatusBadge>}><ul className="health-check-list settings-health-list">{health?.checks?.length ? health.checks.map((check) => (<li key={check.id}><StatusBadge tone={checkStatusTone(check.status)}>{check.status}</StatusBadge><div><strong>{check.label}</strong>{check.detail ? <small>{check.detail}</small> : null}</div></li>)) : <li className="health-check-empty"><small>{health ? "Geen gedetailleerde checks van de backend." : "Backend niet bereikbaar — geen gezondheidsdata."}</small></li>}</ul><Button variant="outline" onClick={() => void refreshHealth()} disabled={healthRefreshing}>{healthRefreshing ? <Loader2 className="spin" /> : <RefreshCcw />}Status vernieuwen</Button></Panel><ReleaseConfidencePanel compact /></div> : null}

          {activeTab === "Prestaties" ? <div className="settings-top-grid"><Panel title="Taakcapaciteit"><label className="form-stack"><span>Maximaal gelijktijdige taken {settings.max_concurrent_tasks === null ? <small>(Unlimited)</small> : null}</span><Input type="number" min={1} placeholder="Unlimited" value={nullableNumberDisplay(settings.max_concurrent_tasks)} onChange={(event) => setSettings({ ...settings, max_concurrent_tasks: parseNullableNumber(event.target.value) })} /><small>Leeg = Unlimited. Wijzigingen gelden direct voor nieuwe reserveringen.</small></label><div className="form-grid two"><label><span>Max. parallelle stappen {settings.max_parallel_steps === null ? <small>(Unlimited)</small> : null}</span><Input type="number" min={1} placeholder="Unlimited" value={nullableNumberDisplay(settings.max_parallel_steps)} onChange={(event) => setSettings({ ...settings, max_parallel_steps: parseNullableNumber(event.target.value) })} /></label><label><span>Max. modelconcurrency {settings.max_model_concurrency === null ? <small>(Unlimited)</small> : null}</span><Input type="number" min={1} placeholder="Unlimited" value={nullableNumberDisplay(settings.max_model_concurrency)} onChange={(event) => setSettings({ ...settings, max_model_concurrency: parseNullableNumber(event.target.value) })} /><small>1 respecteert single-slot lokale modellen. Leeg = Unlimited.</small></label></div><div className="form-grid two"><label><span>Max. modelcalls per taak {settings.max_model_calls_per_task === null ? <small>(Unlimited)</small> : null}</span><Input type="number" min={1} placeholder="Unlimited" value={nullableNumberDisplay(settings.max_model_calls_per_task)} onChange={(event) => setSettings({ ...settings, max_model_calls_per_task: parseNullableNumber(event.target.value) })} /></label><label><span>Max. specialiststappen {settings.max_specialist_steps === null ? <small>(Unlimited)</small> : null}</span><Input type="number" min={1} placeholder="Unlimited" value={nullableNumberDisplay(settings.max_specialist_steps)} onChange={(event) => setSettings({ ...settings, max_specialist_steps: parseNullableNumber(event.target.value) })} /></label></div><div className="form-grid two"><label><span>Max. subtaken {settings.max_subtasks === null ? <small>(Unlimited)</small> : null}</span><Input type="number" min={1} placeholder="Unlimited" value={nullableNumberDisplay(settings.max_subtasks)} onChange={(event) => setSettings({ ...settings, max_subtasks: parseNullableNumber(event.target.value) })} /></label><label><span>Max. afhankelijkheidsdiepte {settings.max_dependency_depth === null ? <small>(Unlimited)</small> : null}</span><Input type="number" min={1} placeholder="Unlimited" value={nullableNumberDisplay(settings.max_dependency_depth)} onChange={(event) => setSettings({ ...settings, max_dependency_depth: parseNullableNumber(event.target.value) })} /></label></div><small>Config-revisie: {settings.config_revision ?? configRevision}. Alleen gewijzigde velden worden opgeslagen (geen stille overschrijving van andere tabs/Control Center).</small></Panel><Panel title="Modelrouting"><div className="form-stack"><label><span>Fallback-modellen (kommagescheiden)</span><Input value={(settings.model_fallback_order || []).join(", ")} onChange={(event) => setSettings({ ...settings, model_fallback_order: event.target.value.split(",").map((item) => item.trim()).filter(Boolean) })} /><small>Alleen lokale IDs; cloud-fallback blijft uit tenzij hieronder toegestaan.</small></label><label><span>Rol→model overrides (JSON)</span><Textarea value={JSON.stringify(settings.role_model_overrides || {}, null, 0)} onChange={(event) => { try { setSettings({ ...settings, role_model_overrides: JSON.parse(event.target.value || "{}") }); } catch { /* keep typing */ } }} /><small>Bijv. {"{"}"build":"local-coder"{"}"}. Expliciete chat/taakkeuze blijft leidend.</small></label><label className="toggle-lines"><span><strong>Cloud-modelfallback toestaan</strong><small>Standaard uit: lokale data gaat niet ongemerkt naar cloud.</small></span><Switch checked={settings.allow_cloud_model_fallback} onCheckedChange={(checked) => setSettings({ ...settings, allow_cloud_model_fallback: checked })} /></label></div></Panel><Panel title="Retrieval & geheugen"><div className="form-grid two"><label><span>Lexicale gewicht</span><Input type="number" min={0} max={1} step={0.05} value={settings.retrieval_lexical_weight} onChange={(event) => setSettings({ ...settings, retrieval_lexical_weight: Number(event.target.value) })} /></label><label><span>Semantisch gewicht</span><Input type="number" min={0} max={1} step={0.05} value={settings.retrieval_semantic_weight} onChange={(event) => setSettings({ ...settings, retrieval_semantic_weight: Number(event.target.value) })} /></label></div><div className="toggle-lines"><label><span><strong>Meertalige retrieval-expansie</strong><small>Opt-in NL↔EN lexicale query-expansie; standaard uit (precision-tradeoff).</small></span><Switch checked={settings.retrieval_multilingual_expand} onCheckedChange={(checked) => setSettings({ ...settings, retrieval_multilingual_expand: checked })} /></label><label><span><strong>Semantische retrieval</strong><small>Optioneel; lexicale fallback blijft werken zonder embeddings.</small></span><Switch checked={settings.enable_semantic_retrieval} onCheckedChange={(checked) => setSettings({ ...settings, enable_semantic_retrieval: checked })} /></label><label><span><strong>Context Compiler in chat</strong><small>Opt-in: Gen2 Context Compiler op chat-pad; standaard uit tot non-regressie bewezen.</small></span><Switch checked={settings.enable_context_compiler_chat} onCheckedChange={(checked) => setSettings({ ...settings, enable_context_compiler_chat: checked })} /></label><label><span><strong>Memory schrijven</strong><small>Uit = geen nieuwe geheugenwrites (C14 policy gate).</small></span><Switch checked={settings.memory_write_enabled} onCheckedChange={(checked) => setSettings({ ...settings, memory_write_enabled: checked })} /></label><label><span><strong>Memory auto-promoten</strong><small>Alleen expliciete/gevalideerde feiten; modelzekerheid ≠ objectieve score.</small></span><Switch checked={settings.memory_auto_promote} onCheckedChange={(checked) => setSettings({ ...settings, memory_auto_promote: checked })} /></label></div><div className="form-grid two"><label><span>Embedding model-ID</span><Input value={settings.embedding_model_id} onChange={(event) => setSettings({ ...settings, embedding_model_id: event.target.value })} /></label><label><span>Diversiteitsvenster</span><Input type="number" min={1} max={12} value={nullableNumberDisplay(settings.retrieval_diversity_window)} onChange={(event) => setSettings({ ...settings, retrieval_diversity_window: parseNullableNumber(event.target.value) })} /></label></div><div className="form-grid two"><label><span>Embedding timeout (s)</span><Input type="number" min={1} max={600} value={nullableNumberDisplay(settings.embedding_timeout_seconds)} onChange={(event) => setSettings({ ...settings, embedding_timeout_seconds: parseNullableNumber(event.target.value) })} /></label><label><span>Embedding batch size</span><Input type="number" min={1} max={256} value={nullableNumberDisplay(settings.embedding_batch_size)} onChange={(event) => setSettings({ ...settings, embedding_batch_size: parseNullableNumber(event.target.value) })} /></label></div><div className="form-grid two"><label><span>Memory scope</span><Select value={settings.memory_default_scope} onValueChange={(value: AppSettings["memory_default_scope"]) => setSettings({ ...settings, memory_default_scope: value })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="session">Sessie</SelectItem><SelectItem value="project">Project</SelectItem><SelectItem value="global">Globaal</SelectItem></SelectContent></Select></label><label><span>Research max. vragen</span><Input type="number" min={1} max={24} value={nullableNumberDisplay(settings.research_max_questions)} onChange={(event) => setSettings({ ...settings, research_max_questions: parseNullableNumber(event.target.value) })} /></label></div><div className="toggle-lines"><label><span><strong>Research: lokaal eerst</strong><small>Netwerk alleen wanneer beschikbaar en toegestaan.</small></span><Switch checked={settings.research_prefer_local} onCheckedChange={(checked) => setSettings({ ...settings, research_prefer_local: checked })} /></label><label><span><strong>Voortgangs-events</strong><small>Gedeeld eventprotocol voor Chat/Taken.</small></span><Switch checked={settings.progress_events_enabled} onCheckedChange={(checked) => setSettings({ ...settings, progress_events_enabled: checked })} /></label><label><span><strong>Voorlopige streamtekst</strong><small>Gescheiden van geverifieerd eindresultaat.</small></span><Switch checked={settings.stream_provisional_text} onCheckedChange={(checked) => setSettings({ ...settings, stream_provisional_text: checked })} /></label></div></Panel><Panel title="Timeouts"><div className="form-stack"><label><span>LM Studio-timeout in seconden</span><Input type="number" min={5} max={900} value={nullableNumberDisplay(settings.request_timeout_seconds)} onChange={(event) => setSettings({ ...settings, request_timeout_seconds: parseNullableNumber(event.target.value) })} /></label><label><span>Modelverversing in seconden</span><Input type="number" min={10} max={3600} value={nullableNumberDisplay(settings.model_refresh_seconds)} onChange={(event) => setSettings({ ...settings, model_refresh_seconds: parseNullableNumber(event.target.value) })} /></label></div></Panel></div> : null}

          {activeTab === "Spraak" ? (
            <div className="settings-top-grid">
              <Panel title="Ingebouwde spraak (Chat Dictatie / Spraakgesprek)">
                <p className="panel-copy">Lokale faster-whisper ASR + Piper/browser TTS via <code>backend/voice</code>. Onafhankelijk van VoiceStudio.</p>
              </Panel>
              <VoiceSettingsPanel
                settings={settings}
                setSettings={(next) => setSettings(toSettingsForm(next))}
              />
              <Panel title="VoiceStudio-provider (gesproken antwoorden / optionele STT)">
                <p className="panel-copy">Swappable lokale TTS/STT via <code>backend/speech</code>. Gebruikt wanneer TTS-provider = VoiceStudio.</p>
              </Panel>
              <SpeechSettingsPanel
                settings={settings}
                setSettings={(next) => setSettings(toSettingsForm(next))}
              />
            </div>
          ) : null}

          {activeTab === "Advanced" ? <div className="settings-top-grid"><MeetDitModelPanel /><NativeRuntimePanel /><HadesControlCenter /></div> : null}

          {activeTab === "Logs" ? <Panel title="Systeemstatus" actions={<StatusBadge tone={health?.backend === "ok" ? "success" : "danger"}>{health?.backend === "ok" ? "Backend actief" : "Backend offline"}</StatusBadge>}><div className="log-view"><code>HADES backend: {health?.backend ?? "onbekend"}</code><code>LM Studio: {health?.lm_studio ?? "onbekend"}</code><code>Modelaantal: {health?.models ?? 0}</code><code>Actief model: {health?.active_model || "niet ingesteld"}</code><code>Database: {storage.path}</code>{health?.detail ? <code>Diagnostiek: {health.detail}</code> : null}</div><Button variant="outline" onClick={() => load()}><RefreshCcw />Status vernieuwen</Button></Panel> : null}

          <div className="settings-footer-actions"><input ref={fileInput} className="visually-hidden" type="file" accept="application/json,.json" onChange={importConfig} /><Button variant="outline" onClick={exportConfig}><Download />Configuratie exporteren</Button><Button variant="outline" onClick={() => fileInput.current?.click()}><Upload />Importeren</Button><AlertDialog><AlertDialogTrigger asChild><Button variant="destructive"><RotateCcw />Standaardwaarden</Button></AlertDialogTrigger><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>Alle instellingen herstellen?</AlertDialogTitle><AlertDialogDescription>De verbinding, rechten en runtimevoorkeuren worden teruggezet. Gesprekken, taken en geheugen blijven bewaard.</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>Annuleren</AlertDialogCancel><AlertDialogAction onClick={reset}>Herstellen</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog></div>
        </div>
      </div>
    </div>
  );
}

