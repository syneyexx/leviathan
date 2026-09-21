"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { useHadesSettings } from "@/components/hades/features/settings/hooks/useHadesSettings";
import { useUiStyle } from "@/components/hades/ui-style";
import { type AppSettings } from "@/lib/hades-api";
import { HADES_SETTINGS_UPDATED_EVENT } from "@/components/hades/features/settings/settings-events";
import { FbIcon } from "../icons";
import {
  SETTINGS_AUTOSAVE,
  SETTINGS_GENERAL_TOGGLES,
  SETTINGS_INTERFACE_FIELDS,
  SETTINGS_NOTIFICATIONS,
  SETTINGS_PRIVACY,
  SETTINGS_QUICK_ACTIONS,
  SETTINGS_RUNTIME_SLIDERS,
  SETTINGS_SHORTCUTS,
  SETTINGS_THEMES,
} from "../mocks/settings";
import { FinalBetaShell } from "../shell/finalbeta-shell";
import type { FinalBetaNavigate, FinalBetaPageId } from "../types";

type SettingsTab = "algemeen" | "interface" | "ai" | "privacy" | "opslag" | "updates";
type PolicyValue = "allow" | "ask" | "block";

type Props = {
  onNavigate: FinalBetaNavigate;
  pageId?: FinalBetaPageId;
  initialTab?: SettingsTab;
};

const DAYS = ["Zondag", "Maandag", "Dinsdag", "Woensdag", "Donderdag", "Vrijdag", "Zaterdag"];
const MONTHS = [
  "januari",
  "februari",
  "maart",
  "april",
  "mei",
  "juni",
  "juli",
  "augustus",
  "september",
  "oktober",
  "november",
  "december",
];

const POLICY_OPTIONS: PolicyValue[] = ["allow", "ask", "block"];

function pad(n: number) {
  return String(n).padStart(2, "0");
}

function SetToggle({
  label,
  on = true,
  icon,
  check,
  controlled,
  disabled,
  onChange,
  presentationOnly,
}: {
  label: string;
  on?: boolean;
  icon?: string;
  check?: boolean;
  controlled?: boolean;
  disabled?: boolean;
  onChange?: (next: boolean) => void;
  presentationOnly?: boolean;
}) {
  const [active, setActive] = useState(on);
  const value = controlled ? on : active;
  return (
    <div className="set-toggle-row">
      <span className="set-toggle-label">
        {check ? <i className={`set-check${value ? " on" : ""}`} aria-hidden="true" /> : null}
        {icon ? <FbIcon name={icon} size={12} /> : null}
        {label}
        {presentationOnly ? <small className="muted"> (lokaal)</small> : null}
      </span>
      <button
        type="button"
        className={`set-toggle${value ? " on" : ""}`}
        aria-pressed={value}
        aria-label={label}
        disabled={disabled}
        onClick={() => {
          if (controlled) {
            onChange?.(!value);
            return;
          }
          setActive((v) => !v);
        }}
      >
        <i />
      </button>
    </div>
  );
}

function CardHead({ icon, title, subtitle }: { icon: string; title: string; subtitle: string }) {
  return (
    <div className="set-card-head">
      <span className="set-card-ico">
        <FbIcon name={icon} size={12} />
      </span>
      <div>
        <h2>{title}</h2>
        <p>{subtitle}</p>
      </div>
    </div>
  );
}

/**
 * FINALBETA Instellingen — visual shell preserved; backend-owned controls use /api/settings.
 */
export function FinalBetaSettingsPage({
  onNavigate,
  pageId = "settings-general",
  initialTab = "algemeen",
}: Props) {
  const { uiStyle, setUiStyle } = useUiStyle();
  const settings = useHadesSettings();
  const values = settings.values;
  const [busy, setBusy] = useState(false);
  const [now, setNow] = useState(() => new Date());
  const [sliders, setSliders] = useState<Record<string, number>>(() =>
    Object.fromEntries(SETTINGS_RUNTIME_SLIDERS.map((s) => [s.id, s.value])),
  );

  const pageToSection: Record<string, string> = {
    "settings-general": "set-section-general",
    "settings-interface": "set-section-interface",
    "settings-llm-behavior": "set-section-ai",
    "settings-llm-studio": "set-section-ai",
    "settings-security": "set-section-privacy",
    "settings-storage": "set-section-storage",
    "settings-python": "set-section-ai",
    "settings-benchmarks": "set-section-ai",
    "settings-logs": "set-section-storage",
    "settings-backups": "set-section-storage",
  };
  const activeSection = pageToSection[pageId] || pageToSection[`settings-${initialTab}`] || "set-section-general";

  useEffect(() => {
    const el = document.getElementById(activeSection);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [activeSection]);

  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 30_000);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    if (!values) return;
    if (values.theme === "dark" || values.theme === "light" || values.theme === "system") {
      // theme buttons use SETTINGS_THEMES ids; map light→solar, system→nebula for display only
    }
  }, [values]);

  const patchSafe = async (partial: Partial<AppSettings>, okMsg: string) => {
    setBusy(true);
    try {
      await settings.patch(partial);
      toast.success(okMsg);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Instelling opslaan mislukt.");
    } finally {
      setBusy(false);
    }
  };

  const applyStyle = async (style: "lux" | "finalbeta") => {
    if (busy || uiStyle === style) return;
    setBusy(true);
    try {
      await settings.patch({ ui_style: style });
      setUiStyle(style);
      window.dispatchEvent(
        new CustomEvent(HADES_SETTINGS_UPDATED_EVENT, {
          detail: { ui_style: style, config_revision: settings.revision },
        }),
      );
      if (style === "lux") {
        window.location.hash = "#/settings";
        toast.success("HADES Lux Atelier actief.");
      } else {
        window.location.hash = "#/fb/settings-general";
        toast.success("FINALBETA actief.");
      }
    } catch (reason) {
      setUiStyle(style);
      window.dispatchEvent(new CustomEvent(HADES_SETTINGS_UPDATED_EVENT, { detail: { ui_style: style } }));
      window.location.hash = style === "lux" ? "#/settings" : "#/fb/settings-general";
      const detail = reason instanceof Error ? reason.message : "Interface-preset opslaan is mislukt.";
      toast.message(`${style === "lux" ? "HADES Lux" : "FINALBETA"} lokaal toegepast. Niet opgeslagen: ${detail}`);
    } finally {
      setBusy(false);
    }
  };

  const lang = values?.language === "en" ? "English" : "Nederlands";
  const themeId = values?.theme === "light" ? "solar" : values?.theme === "system" ? "nebula" : "dark";
  const motionReduced = values?.motion_level === "reduced";
  const saving = busy || settings.busy;

  const policySelect = (key: keyof AppSettings, label: string, current: PolicyValue) => (
    <label key={key} className="set-field">
      <span>{label}</span>
      <select
        className="set-control"
        value={current}
        disabled={saving || !values}
        onChange={(e) => void patchSafe({ [key]: e.target.value as PolicyValue }, `${label} → ${e.target.value}`)}
        data-setting={key}
      >
        {POLICY_OPTIONS.map((opt) => (
          <option key={opt} value={opt}>
            {opt.toUpperCase()}
          </option>
        ))}
      </select>
    </label>
  );

  const body = (
    <div className="settings-page" data-live="settings">
      <div className="settings-welcome">
        <div className="settings-welcome-copy">
          <h1>Instellingen</h1>
          <p>Systeemvoorkeuren, interface, policies en beheer van HADES.</p>
        </div>
        <div className="settings-welcome-mid">“Configure today. Amplify tomorrow.”</div>
        <div className="settings-clock">
          <div className="settings-clock-copy">
            <div className="date">
              {DAYS[now.getDay()]} {now.getDate()} {MONTHS[now.getMonth()]} {now.getFullYear()}
            </div>
            <div className="time">
              {pad(now.getHours())}:{pad(now.getMinutes())}
            </div>
          </div>
          <FbIcon name="bolt" size={22} className="settings-sun" />
        </div>
      </div>

      {settings.error || settings.lastError ? (
        <div className="set-card" role="alert" style={{ marginBottom: 12, padding: 12 }}>
          <strong>Settings laden/opslaan mislukt.</strong>{" "}
          {settings.lastError || settings.error?.message}
          <button type="button" className="set-btn" style={{ marginLeft: 8 }} onClick={() => void settings.refresh()}>
            Opnieuw
          </button>
        </div>
      ) : null}

      <div className="settings-grid">
        <section id="set-section-general" className="set-card set-card-general" data-settings-tab="algemeen">
          <CardHead icon="settings" title="Algemene instellingen" subtitle="Basisconfiguratie van HADES." />
          <label className="set-field">
            <span>Systeemnaam</span>
            <input className="set-control" value="HADES" readOnly aria-readonly="true" title="Vast productnaam" />
          </label>
          <label className="set-field">
            <span>Taal</span>
            <select
              className="set-control"
              value={lang}
              disabled={saving || !values}
              onChange={(e) =>
                void patchSafe(
                  { language: e.target.value === "English" ? "en" : "nl" },
                  `Taal → ${e.target.value}`,
                )
              }
              data-setting="language"
            >
              <option>Nederlands</option>
              <option>English</option>
            </select>
          </label>
          <label className="set-field">
            <span>LM Studio URL</span>
            <input
              className="set-control"
              value={values?.lm_studio_base_url ?? ""}
              disabled={saving || !values}
              onChange={(e) => void patchSafe({ lm_studio_base_url: e.target.value }, "LM Studio URL opgeslagen")}
              data-setting="lm_studio_base_url"
            />
          </label>
          <label className="set-field">
            <span>Request timeout (s)</span>
            <input
              className="set-control"
              type="number"
              min={1}
              value={values?.request_timeout_seconds ?? ""}
              disabled={saving || !values}
              onChange={(e) => {
                const n = e.target.value === "" ? null : Number(e.target.value);
                void patchSafe({ request_timeout_seconds: n }, "Request timeout opgeslagen");
              }}
              data-setting="request_timeout_seconds"
            />
          </label>
          {SETTINGS_GENERAL_TOGGLES.map((item) => (
            <SetToggle key={item.id} label={item.label} on={item.on} check presentationOnly />
          ))}
        </section>

        <section id="set-section-interface" className="set-card set-card-interface" data-settings-tab="interface">
          <CardHead icon="image" title="Interface thema & density" subtitle="Uiterlijk en beleving van de interface." />
          <div className="set-ui-row" role="group" aria-label="Interface">
            <button
              type="button"
              className={`set-ui-opt${uiStyle !== "finalbeta" ? " active" : ""}`}
              aria-pressed={uiStyle !== "finalbeta"}
              disabled={saving || uiStyle !== "finalbeta"}
              onClick={() => void applyStyle("lux")}
            >
              <span className="mode-title">HADES Lux</span>
              <span className="mode-desc">Functionele productinterface.</span>
            </button>
            <button
              type="button"
              className={`set-ui-opt${uiStyle === "finalbeta" ? " active" : ""}`}
              aria-pressed={uiStyle === "finalbeta"}
              disabled={saving || uiStyle === "finalbeta"}
              onClick={() => void applyStyle("finalbeta")}
            >
              <span className="mode-title">FINALBETA</span>
              <span className="mode-desc">Nieuwe visuele interface.</span>
            </button>
          </div>
          <div className="set-theme-row" role="group" aria-label="Thema">
            {SETTINGS_THEMES.map((theme) => {
              const mapped: AppSettings["theme"] =
                theme.id === "solar" ? "light" : theme.id === "nebula" ? "system" : "dark";
              return (
                <button
                  key={theme.id}
                  type="button"
                  className={`set-theme${themeId === theme.id ? " active" : ""}`}
                  aria-pressed={themeId === theme.id}
                  disabled={saving || !values}
                  onClick={() => void patchSafe({ theme: mapped }, `Thema → ${mapped}`)}
                >
                  <FbIcon name={theme.icon} size={14} />
                  <strong>
                    {theme.label}
                    {theme.id === "dark" ? " (Standaard)" : ""}
                  </strong>
                  <small>{theme.hint}</small>
                </button>
              );
            })}
          </div>
          {SETTINGS_INTERFACE_FIELDS.map((field) =>
            field.id === "anim" ? (
              <label key={field.id} className="set-field">
                <span>{field.label}</span>
                <select
                  className="set-control"
                  value={
                    values?.motion_level === "reduced"
                      ? "Verminderd"
                      : values?.motion_level === "cinematic"
                        ? "Normaal"
                        : "Normaal"
                  }
                  disabled={saving || !values}
                  onChange={(e) => {
                    const motion_level =
                      e.target.value === "Verminderd" ? "reduced" : e.target.value === "Uit" ? "reduced" : "standard";
                    void patchSafe({ motion_level }, `Animaties → ${motion_level}`);
                  }}
                  data-setting="motion_level"
                >
                  <option>Normaal</option>
                  <option>Verminderd</option>
                  <option>Uit</option>
                </select>
              </label>
            ) : (
              <label key={field.id} className="set-field">
                <span>
                  {field.label} <small className="muted">(lokaal)</small>
                </span>
                <select className="set-control" defaultValue={field.value}>
                  {field.options.map((opt) => (
                    <option key={opt}>{opt}</option>
                  ))}
                </select>
              </label>
            ),
          )}
          <SetToggle
            label="Reduceer beweging (accessibility)"
            controlled
            on={motionReduced}
            disabled={saving || !values}
            onChange={(next) => void patchSafe({ motion_level: next ? "reduced" : "standard" }, "Motion level opgeslagen")}
          />
        </section>

        <section className="set-card set-card-notifications">
          <CardHead icon="bolt" title="Notificaties" subtitle="Presentatie-only — geen backend notificatiekanaal." />
          {SETTINGS_NOTIFICATIONS.map((item) => (
            <SetToggle key={item.id} label={item.label} on={item.on} icon={item.icon} presentationOnly />
          ))}
        </section>

        <section id="set-section-privacy" className="set-card set-card-privacy" data-settings-tab="privacy">
          <CardHead icon="shield" title="Privacy & beveiliging" subtitle="Bevestiging en lokale-only defaults." />
          {SETTINGS_PRIVACY.map((item) => (
            <SetToggle key={item.id} label={item.label} on={item.on} check presentationOnly />
          ))}
        </section>

        <section id="set-section-ai" className="set-card set-card-runtime" data-settings-tab="ai">
          <CardHead icon="sliders" title="Lokale runtime voorkeuren" subtitle="Concurrency en tool budget (live)." />
          <label className="set-field">
            <span>Max concurrente taken</span>
            <input
              className="set-control"
              type="number"
              min={1}
              value={values?.max_concurrent_tasks ?? ""}
              disabled={saving || !values}
              onChange={(e) => {
                const n = e.target.value === "" ? null : Number(e.target.value);
                void patchSafe({ max_concurrent_tasks: n }, "Max concurrente taken opgeslagen");
              }}
              data-setting="max_concurrent_tasks"
            />
          </label>
          <label className="set-field">
            <span>Max tool rounds</span>
            <input
              className="set-control"
              type="number"
              min={0}
              value={values?.max_tool_rounds ?? ""}
              disabled={saving || !values}
              onChange={(e) => {
                const n = e.target.value === "" ? null : Number(e.target.value);
                void patchSafe({ max_tool_rounds: n }, "Max tool rounds opgeslagen");
              }}
              data-setting="max_tool_rounds"
            />
          </label>
          <label className="set-field">
            <span>Reasoning profile</span>
            <select
              className="set-control"
              value={values?.reasoning_profile ?? "adaptive"}
              disabled={saving || !values}
              onChange={(e) =>
                void patchSafe(
                  { reasoning_profile: e.target.value as AppSettings["reasoning_profile"] },
                  `Reasoning → ${e.target.value}`,
                )
              }
              data-setting="reasoning_profile"
            >
              <option value="adaptive">adaptive</option>
              <option value="fast">fast</option>
              <option value="normal">normal</option>
              <option value="standard">standard</option>
              <option value="medium">medium</option>
              <option value="high">high</option>
              <option value="maximum">maximum</option>
            </select>
          </label>
          {SETTINGS_RUNTIME_SLIDERS.map((slider) => (
            <div key={slider.id} className="set-slider-row">
              <span>
                {slider.label} <small className="muted">(lokaal)</small>
              </span>
              <input
                className="set-slider"
                type="range"
                min={slider.min}
                max={slider.max}
                value={sliders[slider.id] ?? slider.value}
                style={{
                  ["--fill" as string]: `${(((sliders[slider.id] ?? slider.value) - slider.min) / (slider.max - slider.min)) * 100}%`,
                }}
                onChange={(event) => setSliders((prev) => ({ ...prev, [slider.id]: Number(event.target.value) }))}
                aria-label={slider.label}
              />
              <b>
                {slider.id === "vram"
                  ? `${sliders[slider.id] ?? slider.value}%`
                  : slider.id === "mem"
                    ? `${sliders[slider.id] ?? slider.value} GB`
                    : String(sliders[slider.id] ?? slider.value)}
              </b>
            </div>
          ))}
        </section>

        <section className="set-card set-card-policies">
          <CardHead icon="file" title="AI policies" subtitle="Autoritatieve HADES security policies (live)." />
          {policySelect("file_read_policy", "Filesystem read", (values?.file_read_policy as PolicyValue) || "ask")}
          {policySelect("file_write_policy", "Filesystem write", (values?.file_write_policy as PolicyValue) || "ask")}
          {policySelect("network_policy", "Network", (values?.network_policy as PolicyValue) || "block")}
          {policySelect("subprocess_policy", "Subprocess", (values?.subprocess_policy as PolicyValue) || "ask")}
          <SetToggle
            label="Plugin autonomous tools"
            controlled
            check
            on={Boolean(values?.plugin_autonomous_tools)}
            disabled={saving || !values}
            onChange={(next) => void patchSafe({ plugin_autonomous_tools: next }, `Autonomous tools → ${next ? "ON" : "OFF"}`)}
          />
          <SetToggle
            label="Auto web research"
            controlled
            on={Boolean(values?.auto_web_research)}
            disabled={saving || !values}
            onChange={(next) => void patchSafe({ auto_web_research: next }, `Auto web research → ${next ? "ON" : "OFF"}`)}
          />
          <SetToggle
            label="Streaming"
            controlled
            on={Boolean(values?.streaming)}
            disabled={saving || !values}
            onChange={(next) => void patchSafe({ streaming: next }, `Streaming → ${next ? "ON" : "OFF"}`)}
          />
          <div className="set-chip-cloud" style={{ marginTop: 10 }}>
            <span className="set-chip green">
              <FbIcon name="check" size={10} />
              netwerk: {(values?.network_policy || "block").toUpperCase()}
            </span>
            <span className="set-chip green">
              <FbIcon name="check" size={10} />
              write: {(values?.file_write_policy || "ask").toUpperCase()}
            </span>
            <span className={`set-chip ${values?.plugin_autonomous_tools ? "gold" : "green"}`}>
              <FbIcon name="bolt" size={10} />
              autonomy: {values?.plugin_autonomous_tools ? "ON" : "OFF"}
            </span>
          </div>
        </section>

        <section id="set-section-storage" className="set-card set-card-autosave" data-settings-tab="opslag">
          <CardHead icon="refresh" title="Autosave & updates" subtitle="Back-ups — nog geen backend API; eerlijk gelabeld." />
          <div className="set-autosave-split">
            <div>
              {SETTINGS_AUTOSAVE.map((item) => (
                <SetToggle key={item.id} label={item.label} on={item.on} check presentationOnly />
              ))}
            </div>
            <div>
              <p className="muted" style={{ fontSize: 12 }}>
                Storage pad: {settings.storage?.path || "—"}
                {settings.storage?.size_bytes != null ? ` (${settings.storage.size_bytes} bytes)` : ""}
              </p>
              <p className="muted" style={{ fontSize: 12 }}>
                Config revision: {settings.revision ?? values?.config_revision ?? "—"}
              </p>
            </div>
          </div>
        </section>

        <section className="set-card set-card-shortcuts">
          <CardHead icon="code" title="Keyboard shortcuts" subtitle="Referentie (niet configureerbaar)." />
          {SETTINGS_SHORTCUTS.map((row) => (
            <div key={row.keys} className="set-shortcut">
              <span className="set-kbd">{row.keys}</span>
              <span>{row.action}</span>
            </div>
          ))}
        </section>

        <section className="set-card set-card-integrations">
          <CardHead icon="link" title="Integraties" subtitle="Geen fake connected states — open relevante pagina’s." />
          <div className="set-integ">
            <strong>Plugins</strong>
            <button type="button" className="set-connect" onClick={() => onNavigate("tools")}>
              Openen
            </button>
          </div>
          <div className="set-integ">
            <strong>MCP</strong>
            <button type="button" className="set-connect" onClick={() => onNavigate("mcp")}>
              Openen
            </button>
          </div>
          <div className="set-integ">
            <strong>LM Studio</strong>
            <button type="button" className="set-connect" onClick={() => onNavigate("settings-llm-studio")}>
              Openen
            </button>
          </div>
        </section>
      </div>
    </div>
  );

  const inspector = (
    <>
      <p className="settings-insp-quote">“Same control. More possibilities.”</p>

      <section className="settings-insp-section">
        <div className="settings-insp-head">
          <h3 className="settings-insp-title">HADES Core</h3>
          <span className="settings-insp-ver">{settings.version || "—"}</span>
        </div>
        <div className="settings-insp-card">
          <div className="settings-detail-row">
            <span className="k">Status</span>
            <span className={`v ${settings.loading ? "" : "green"}`}>
              {settings.loading ? "Laden…" : settings.error ? "Fout" : "Live"}
            </span>
          </div>
          <div className="settings-detail-row">
            <span className="k">Mode</span>
            <span className="v">Local</span>
          </div>
          <div className="settings-detail-row">
            <span className="k">UI</span>
            <span className="v">{values?.ui_style || uiStyle}</span>
          </div>
          <div className="settings-detail-row">
            <span className="k">Revision</span>
            <span className="v">{String(settings.revision ?? values?.config_revision ?? "—")}</span>
          </div>
          <div className="settings-detail-row">
            <span className="k">Network</span>
            <span className="v">{(values?.network_policy || "—").toUpperCase()}</span>
          </div>
        </div>
      </section>

      <section className="settings-insp-section">
        <div className="settings-insp-head">
          <h3 className="settings-insp-title settings-sec-title">
            <FbIcon name="shield" size={12} />
            Beveiliging
          </h3>
        </div>
        <div className="settings-insp-card">
          <div className="settings-detail-row">
            <span className="k">Read</span>
            <span className="v">{(values?.file_read_policy || "—").toUpperCase()}</span>
          </div>
          <div className="settings-detail-row">
            <span className="k">Write</span>
            <span className="v">{(values?.file_write_policy || "—").toUpperCase()}</span>
          </div>
          <div className="settings-detail-row">
            <span className="k">Network</span>
            <span className="v">{(values?.network_policy || "—").toUpperCase()}</span>
          </div>
          <div className="settings-detail-row">
            <span className="k">Subprocess</span>
            <span className="v">{(values?.subprocess_policy || "—").toUpperCase()}</span>
          </div>
          <div className="settings-detail-row">
            <span className="k">Autonomy</span>
            <span className="v">{values?.plugin_autonomous_tools ? "ON" : "OFF"}</span>
          </div>
        </div>
      </section>

      <section className="settings-insp-section">
        <div className="settings-insp-head">
          <h3 className="settings-insp-title">Snelle acties</h3>
        </div>
        <div className="settings-quick">
          <button
            type="button"
            className="settings-quick-btn"
            disabled={saving}
            onClick={() => void settings.refresh().then(() => toast.success("Settings vernieuwd"))}
          >
            <FbIcon name="refresh" size={14} />
            <span>Vernieuwen</span>
          </button>
          {SETTINGS_QUICK_ACTIONS.filter((a) => a.id === "export" || a.id === "folder").map((action) => (
            <button
              key={action.id}
              type="button"
              className="settings-quick-btn"
              title="Nog niet geïmplementeerd"
              disabled
            >
              <FbIcon name={action.icon} size={14} />
              <span>{action.label}</span>
            </button>
          ))}
        </div>
      </section>
    </>
  );

  const footer = (
    <footer className="dash-footer settings-footer">
      <span>HADES FINALBETA | Local AI Platform · settings live</span>
      <span className="motto">Build a smarter tomorrow.</span>
    </footer>
  );

  return (
    <FinalBetaShell
      page={pageId}
      body={body}
      inspector={inspector}
      onNavigate={onNavigate}
      appClassName="settings-app"
      mainClassName="settings-main"
      footer={footer}
    />
  );
}
