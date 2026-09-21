"use client";

import type { HadesCodingRuntime } from "@/components/hades/finalbeta/hooks/use-coding-live";

type Props = { coding: HadesCodingRuntime };

function Toggle({
  label,
  on,
  disabled,
  onToggle,
}: {
  label: string;
  on: boolean;
  disabled?: boolean;
  onToggle: () => void;
}) {
  return (
    <div className="coding-settings-toggle-row">
      <span>{label}</span>
      <button
        type="button"
        className={`coding-settings-toggle${on ? " on" : ""}`}
        aria-pressed={on}
        disabled={disabled}
        onClick={onToggle}
      >
        <i />
      </button>
    </div>
  );
}

export function CodingTabSettings({ coding }: Props) {
  const values = coding.controlValues || {};
  const autonomy = String(values["coding.autonomy.profile"] || coding.autonomyProfile);
  const omniDefault = Boolean(values["coding.omniroute.enabled_by_default"] ?? coding.useOmniroute);
  const omniFallback = values["coding.omniroute.allow_fallback"] !== false;
  const maxRepair = String(values["build.max_repair_attempts"] ?? coding.maxAttempts);
  const testTimeout = String(values["build.test_timeout_seconds"] ?? "—");

  return (
    <div className="coding-settings-tab">
      <div className="coding-tab-b-layout">
        <div className="coding-tab-b-col">
          <article className="coding-tab-b-card">
            <div className="coding-tab-b-card-head">
              <strong>Coding defaults (Control Plane)</strong>
            </div>
            <div className="coding-tab-b-card-body">
              {coding.controlError ? <div className="coding-banner danger">{coding.controlError}</div> : null}
              <label className="coding-field">
                <span>Default autonomy profile</span>
                <select
                  value={autonomy}
                  onChange={(e) => coding.setAutonomyProfile(e.target.value as typeof coding.autonomyProfile)}
                >
                  <option value="analyze_only">analyze_only</option>
                  <option value="managed_workspace_modify">managed_workspace_modify</option>
                  <option value="reviewable_result">reviewable_result</option>
                </select>
              </label>
              <Toggle
                label="OmniRoute enabled by default"
                on={omniDefault}
                disabled={!coding.omnirouteStatus?.usable}
                onToggle={() => coding.setUseOmniroute(!coding.useOmniroute)}
              />
              <div className="coding-tab-b-kv">
                <span>OmniRoute status</span>
                <strong>
                  {coding.omnirouteStatus
                    ? `${coding.omnirouteStatus.status_label} · usable=${String(coding.omnirouteStatus.usable)}`
                    : "—"}
                </strong>
              </div>
              <div className="coding-tab-b-kv">
                <span>Allow OmniRoute fallback</span>
                <strong>{omniFallback ? "true" : "false"}</strong>
              </div>
              <div className="coding-tab-b-kv">
                <span>build.max_repair_attempts</span>
                <strong>{maxRepair}</strong>
              </div>
              <div className="coding-tab-b-kv">
                <span>build.test_timeout_seconds</span>
                <strong>{testTimeout}</strong>
              </div>
              <button
                type="button"
                className="btn btn-gold"
                disabled={coding.controlSaving}
                onClick={() =>
                  void coding.saveControlPatch({
                    "coding.autonomy.profile": coding.autonomyProfile,
                    "coding.omniroute.enabled_by_default": coding.useOmniroute,
                  })
                }
              >
                {coding.controlSaving ? "Opslaan…" : "Opslaan naar Control Plane"}
              </button>
              <button type="button" className="btn btn-outline" onClick={() => void coding.refreshControlValues()}>
                Herladen
              </button>
            </div>
          </article>
        </div>

        <div className="coding-tab-b-col">
          <article className="coding-tab-b-card">
            <div className="coding-tab-b-card-head">
              <strong>Runtime policies (read-only snapshot)</strong>
            </div>
            <div className="coding-tab-b-card-body">
              <div className="coding-tab-b-kv">
                <span>subprocess_policy</span>
                <strong>{coding.settings?.subprocess_policy || "—"}</strong>
              </div>
              <div className="coding-tab-b-kv">
                <span>file_write_policy</span>
                <strong>{coding.settings?.file_write_policy || "—"}</strong>
              </div>
              <div className="coding-tab-b-kv">
                <span>file_read_policy</span>
                <strong>{coding.settings?.file_read_policy || "—"}</strong>
              </div>
              <p className="coding-hint">Wijzig policies via Settings / Control Plane Security — niet via nep-toggles.</p>
            </div>
          </article>

          <article className="coding-tab-b-card">
            <div className="coding-tab-b-card-head">
              <strong>Session Coding defaults</strong>
            </div>
            <div className="coding-tab-b-card-body">
              <label className="coding-field">
                <span>Default strategy (session)</span>
                <select
                  value={coding.codingStrategy}
                  onChange={(e) => coding.setCodingStrategy(e.target.value as typeof coding.codingStrategy)}
                >
                  <option value="fast">fast</option>
                  <option value="investigate">investigate</option>
                  <option value="auto">auto</option>
                </select>
              </label>
              <label className="coding-field">
                <span>Default max attempts (session)</span>
                <input value={coding.maxAttempts} onChange={(e) => coding.setMaxAttempts(e.target.value)} />
              </label>
              <Toggle label="Background jobs by default" on={coding.backgroundRun} onToggle={() => coding.setBackgroundRun(!coding.backgroundRun)} />
            </div>
          </article>

          <article className="coding-tab-b-card">
            <div className="coding-tab-b-card-head">
              <strong>Niet beschikbaar</strong>
            </div>
            <div className="coding-tab-b-card-body">
              <div className="coding-unavailable">
                Er is geen `.hades/coding.json` productbestand. Import/export/share van een los Coding-configbestand is niet van toepassing.
              </div>
            </div>
          </article>
        </div>
      </div>
    </div>
  );
}
