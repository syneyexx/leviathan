import type { ReactNode } from "react";
import {
  COMMON_TIMEZONES,
  formatTimezoneLabel,
} from "../../lib/uiPreferences";
import { Button } from "../ui";
import { ToggleControl } from "../models/ModelsFormControls";
import type { SettingsWorkspace } from "../../hooks/useSettingsWorkspace";

type Props = {
  ws: SettingsWorkspace;
};

function Field({
  label,
  children,
  hint,
}: {
  label: string;
  children: ReactNode;
  hint?: string;
}) {
  return (
    <label className="lv-v2-settings-field">
      <span className="lv-v2-settings-field__label">{label}</span>
      {children}
      {hint ? <small className="lv-v2-settings-field__hint">{hint}</small> : null}
    </label>
  );
}

export function SettingsGeneralPanel({ ws }: Props) {
  const draft = (key: string) => ws.drafts[key];
  const set = (key: string, value: unknown) => ws.setDraft(key, value);

  const refreshOptions = [
    { value: 5, label: "5 seconden" },
    { value: 15, label: "15 seconden" },
    { value: 30, label: "30 seconden" },
    { value: 60, label: "60 seconden" },
    { value: 120, label: "2 minuten" },
    { value: 300, label: "5 minuten" },
  ];

  const desktopHint = (() => {
    const cap = ws.desktopPerm;
    if (!cap.supported) return "Browser ondersteunt geen Notification API.";
    if (cap.permission === "denied") return "Browser-toestemming geweigerd — preference wordt wel opgeslagen.";
    if (cap.permission === "granted") return "Browser-toestemming verleend.";
    return "Toestemming wordt gevraagd bij opslaan wanneer ingeschakeld.";
  })();

  const startupHint = (() => {
    if (!ws.startup) return "OS-registratiestatus wordt geladen…";
    if (!ws.startup.supported) return ws.startup.detail;
    return `${ws.startup.status}: ${ws.startup.detail}`;
  })();

  return (
    <section className="lv-v2-settings-general" aria-label="Algemeen">
      <div className="lv-v2-settings-panel-head">
        <div>
          <h3>Algemeen</h3>
          <p>Basis configuratie en systeemvoorkeuren</p>
        </div>
        <Button variant="secondary" size="sm" onClick={() => void ws.resetCategory("algemeen")}>
          Standaardwaarden
        </Button>
      </div>

      <div className="lv-v2-settings-general__block">
        <h4>Applicatie Instellingen</h4>
        <div className="lv-v2-settings-general__grid">
          <Field label="Applicatie Naam">
            <input
              className="lv-v2-input"
              value={String(draft("ui.app_display_name") ?? "")}
              maxLength={120}
              onChange={(e) => set("ui.app_display_name", e.target.value)}
            />
          </Field>
          <Field label="Tijdzone" hint="IANA id; offset volgt DST-wijzigingen.">
            <select
              className="lv-v2-select"
              value={String(draft("ui.timezone") ?? "Europe/Amsterdam")}
              onChange={(e) => set("ui.timezone", e.target.value)}
            >
              {COMMON_TIMEZONES.map((tz) => (
                <option key={tz} value={tz}>
                  {formatTimezoneLabel(tz)}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Taal" hint="Alleen locales met UI-ondersteuning.">
            <select
              className="lv-v2-select"
              value={String(draft("ui.locale") ?? "nl")}
              onChange={(e) => set("ui.locale", e.target.value)}
            >
              <option value="nl">Nederlands</option>
              <option value="en">English</option>
            </select>
          </Field>
          <Field label="Thema">
            <select
              className="lv-v2-select"
              value={String(draft("ui.theme") ?? "dark_leviathan")}
              onChange={(e) => set("ui.theme", e.target.value)}
            >
              <option value="dark_leviathan">Dark (Leviathan)</option>
            </select>
          </Field>
          <Field label="Automatisch verversen" hint="Pauzeert in verborgen tabs; geen overlap.">
            <select
              className="lv-v2-select"
              value={String(draft("ui.auto_refresh_seconds") ?? 30)}
              onChange={(e) => set("ui.auto_refresh_seconds", Number(e.target.value))}
            >
              {refreshOptions.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </Field>
        </div>
      </div>

      <div className="lv-v2-settings-toggles">
        <div className="lv-v2-settings-toggles__group">
          <h4>Systeem voorkeuren</h4>
          <div className="lv-v2-settings-toggle-row">
            <div>
              <strong>Geluid meldingen</strong>
              <small>Toast-cue in deze browser-tab</small>
            </div>
            <ToggleControl
              checked={Boolean(draft("ui.sound_notifications"))}
              onChange={(v) => set("ui.sound_notifications", v)}
            />
          </div>
          <div className="lv-v2-settings-toggle-row">
            <div>
              <strong>Desktop notificaties</strong>
              <small>{desktopHint}</small>
            </div>
            <ToggleControl
              checked={Boolean(draft("ui.desktop_notifications"))}
              onChange={(v) => set("ui.desktop_notifications", v)}
            />
          </div>
          <div className="lv-v2-settings-toggle-row">
            <div>
              <strong>Start met systeem</strong>
              <small>{startupHint}</small>
            </div>
            <ToggleControl
              checked={Boolean(draft("ui.start_with_system"))}
              onChange={(v) => set("ui.start_with_system", v)}
            />
          </div>
        </div>

        <div className="lv-v2-settings-toggles__group">
          <h4>Data & Privacy</h4>
          <div className="lv-v2-settings-toggle-row">
            <div>
              <strong>Lokale data opslag</strong>
              <small>Voorkeur lokaal; cloud providers blijven apart configureerbaar</small>
            </div>
            <ToggleControl
              checked={Boolean(draft("ui.prefer_local_data"))}
              onChange={(v) => set("ui.prefer_local_data", v)}
            />
          </div>
          <div className="lv-v2-settings-toggle-row">
            <div>
              <strong>Telemetry</strong>
              <small>Optionele diagnostiek off-machine. Lokale SystemTelemetry blijft aan.</small>
            </div>
            <ToggleControl
              checked={Boolean(draft("ui.optional_diagnostics_share"))}
              onChange={(v) => set("ui.optional_diagnostics_share", v)}
            />
          </div>
          <div className="lv-v2-settings-toggle-row">
            <div>
              <strong>Crash rapporten</strong>
              <small>Lokale crash fingerprints in ObservabilityHub (geen externe sink)</small>
            </div>
            <ToggleControl
              checked={Boolean(draft("ui.crash_reports_enabled"))}
              onChange={(v) => set("ui.crash_reports_enabled", v)}
            />
          </div>
        </div>
      </div>
    </section>
  );
}
