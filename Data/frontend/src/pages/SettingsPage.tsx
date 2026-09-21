import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { media } from "../assets/media";
import { SubMenu } from "../components/SubMenu";
import { AppShell } from "../layouts/AppShell";
import { useAppToast } from "../state/useAppToast";

const CATEGORIES = [
  { id: "algemeen", label: "Algemeen", desc: "App defaults & behavior" },
  { id: "llm-gedrag", label: "LLM Gedrag", desc: "Response style & limits" },
  { id: "llm-studio", label: "LLM Studio", desc: "Studio & playground prefs" },
  { id: "rechten", label: "Rechten & Security", desc: "Access & audit" },
  { id: "benchmarks", label: "Model Benchmarks", desc: "Eval defaults" },
  { id: "mediacenter", label: "Mediacenter", desc: "Media defaults" },
  { id: "opslag", label: "Opslag", desc: "Storage & backups" },
  { id: "python", label: "Python & Runtime", desc: "Runtime & acceleration" },
  { id: "settings-console", label: "Console", desc: "Operator console" },
  { id: "logs", label: "Logs", desc: "Retention & verbosity" },
] as const;

type CategoryId = (typeof CATEGORIES)[number]["id"];

function isCategoryId(value: string | null): value is CategoryId {
  return CATEGORIES.some((item) => item.id === value);
}

const INTEGRATIONS = [
  { name: "OpenAI", status: "Connected" },
  { name: "Anthropic", status: "Connected" },
  { name: "Google", status: "Disconnected" },
  { name: "Ollama", status: "Connected" },
  { name: "HuggingFace", status: "Connected" },
  { name: "LM Studio", status: "Connected" },
];

type ToggleState = Record<string, boolean>;

export function SettingsPage() {
  const toast = useAppToast();
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab");
  const category: CategoryId = isCategoryId(tab) ? tab : "algemeen";
  const [appName, setAppName] = useState("LEVIATHAN");
  const [toggles, setToggles] = useState<ToggleState>({
    autoSave: true,
    updates: true,
    minimized: false,
    confirmDanger: true,
    taskComplete: true,
    errors: true,
    modelStatus: true,
    longRunning: false,
    systemUpdates: true,
    quantization: true,
    flashAttention: true,
    lowVram: false,
  });
  const [sliders, setSliders] = useState({
    concurrent: 4,
    timeout: 120,
    memory: 80,
    cpu: 80,
  });

  const setToggle = (key: string) => {
    setToggles((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const selectCategory = (id: CategoryId) => {
    const next = new URLSearchParams(params);
    if (id === "algemeen") next.delete("tab");
    else next.set("tab", id);
    setParams(next, { replace: true });
  };

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
            <p className="lv-page-quote">“A more powerful tomorrow, by design.”</p>
          </div>
          <div className="lv-hero-rail" aria-hidden="true">
            <span>Control</span>
            <span>Refine</span>
            <span>Optimize</span>
            <span>Secure</span>
            <span>Evolve</span>
          </div>
        </section>

        <SubMenu />

        <div className="lv-settings-layout">
          <aside className="lv-panel lv-settings-nav">
            {CATEGORIES.map((item) => (
              <button
                key={item.id}
                className={`lv-settings-nav-item${category === item.id ? " is-active" : ""}`}
                type="button"
                onClick={() => selectCategory(item.id)}
              >
                <strong>{item.label}</strong>
                <small>{item.desc}</small>
              </button>
            ))}
          </aside>

          <div className="lv-settings-grid">
            <article className="lv-panel lv-settings-card">
              <div className="lv-section-label">General</div>
              <div className="lv-form-field">
                <label htmlFor="app-name">Application Name</label>
                <input
                  id="app-name"
                  className="lv-input"
                  style={{ width: "100%" }}
                  value={appName}
                  onChange={(event) => setAppName(event.target.value)}
                />
              </div>
              <div className="lv-form-field">
                <label htmlFor="language">Language</label>
                <select id="language" className="lv-select" defaultValue="en">
                  <option value="en">English</option>
                  <option value="nl">Nederlands</option>
                  <option value="de">Deutsch</option>
                </select>
              </div>
              <div className="lv-form-field">
                <label htmlFor="default-llm">Default LLM</label>
                <select id="default-llm" className="lv-select" defaultValue="qwen">
                  <option value="qwen">Qwen2.5-Coder-7B</option>
                  <option value="llama">Llama 3.1 8B</option>
                  <option value="hades">HADES-Coder-7B-SFT</option>
                </select>
              </div>
              <div className="lv-toggle-stack">
                {[
                  ["autoSave", "Auto Save"],
                  ["updates", "Check for Updates"],
                  ["minimized", "Start Minimized"],
                  ["confirmDanger", "Confirm Dangerous Actions"],
                ].map(([key, label]) => (
                  <button
                    key={key}
                    className="lv-toggle"
                    type="button"
                    onClick={() => setToggle(key)}
                  >
                    <span className={`lv-switch${toggles[key] ? " is-on" : ""}`} />
                    {label}
                  </button>
                ))}
              </div>
            </article>

            <article className="lv-panel lv-settings-card">
              <div className="lv-section-label">Performance</div>
              {(
                [
                  ["concurrent", "Max Concurrent Tasks", 1, 16, ""],
                  ["timeout", "Request Timeout", 30, 300, "s"],
                  ["memory", "Max Memory Usage", 20, 100, "%"],
                  ["cpu", "CPU Usage Limit", 20, 100, "%"],
                ] as const
              ).map(([key, label, min, max, suffix]) => (
                <div key={key} className="lv-slider-row">
                  <header>
                    <span>{label}</span>
                    <strong>
                      {sliders[key]}
                      {suffix}
                    </strong>
                  </header>
                  <input
                    type="range"
                    min={min}
                    max={max}
                    value={sliders[key]}
                    onChange={(event) =>
                      setSliders((prev) => ({ ...prev, [key]: Number(event.target.value) }))
                    }
                  />
                </div>
              ))}
              <div className="lv-toggle-stack">
                {[
                  ["quantization", "Enable Model Quantization"],
                  ["flashAttention", "Use Flash Attention"],
                  ["lowVram", "Optimize for Low VRAM"],
                ].map(([key, label]) => (
                  <button
                    key={key}
                    className="lv-toggle"
                    type="button"
                    onClick={() => setToggle(key)}
                  >
                    <span className={`lv-switch${toggles[key] ? " is-on" : ""}`} />
                    {label}
                  </button>
                ))}
              </div>
            </article>

            <article className="lv-panel lv-settings-card">
              <div className="lv-section-label">Data & Storage</div>
              <div className="lv-form-field">
                <label htmlFor="data-dir">Data Directory</label>
                <input
                  id="data-dir"
                  className="lv-input"
                  style={{ width: "100%" }}
                  defaultValue="/Data/backend/data"
                />
              </div>
              <div className="lv-form-field">
                <label htmlFor="cache-dir">Cache Directory</label>
                <input
                  id="cache-dir"
                  className="lv-input"
                  style={{ width: "100%" }}
                  defaultValue="/Data/backend/cache"
                />
              </div>
              <div className="lv-form-field">
                <label htmlFor="cache-size">Max Cache Size</label>
                <input id="cache-size" className="lv-input" defaultValue="50 GB" />
              </div>
              <div className="lv-form-field">
                <label htmlFor="backup-freq">Backup Frequency</label>
                <select id="backup-freq" className="lv-select" defaultValue="daily">
                  <option value="hourly">Hourly</option>
                  <option value="daily">Daily</option>
                  <option value="weekly">Weekly</option>
                </select>
              </div>
              <div className="lv-detail-actions">
                <button className="lv-btn" type="button" onClick={() => toast("Open Directory")}>
                  Open Directory
                </button>
                <button className="lv-btn lv-btn-danger" type="button" onClick={() => toast("Run Cleanup")}>
                  Run Cleanup
                </button>
                <button className="lv-btn" type="button" onClick={() => toast("Create Backup")}>
                  Create Backup
                </button>
                <button className="lv-btn" type="button" onClick={() => toast("Restore Backup")}>
                  Restore Backup
                </button>
              </div>
            </article>

            <article className="lv-panel lv-settings-card span-2">
              <div className="lv-section-label">API & Integrations</div>
              {INTEGRATIONS.map((item) => (
                <div key={item.name} className="lv-integration-row">
                  <strong style={{ color: "var(--lv-text-bright)" }}>{item.name}</strong>
                  <span className="lv-model-status">
                    <span
                      className={`lv-status-dot ${item.status === "Connected" ? "ready" : "failed"}`}
                    />
                    {item.status}
                  </span>
                  <button className="lv-btn" type="button" onClick={() => toast(`Configure ${item.name}`)}>
                    Configure
                  </button>
                </div>
              ))}
            </article>

            <article className="lv-panel lv-settings-card">
              <div className="lv-section-label">Notifications</div>
              <div className="lv-toggle-stack">
                {[
                  ["taskComplete", "Task Completion"],
                  ["errors", "Errors & Failures"],
                  ["modelStatus", "Model Status Changes"],
                  ["longRunning", "Long Running Tasks"],
                  ["systemUpdates", "System Updates"],
                ].map(([key, label]) => (
                  <button
                    key={key}
                    className="lv-toggle"
                    type="button"
                    onClick={() => setToggle(key)}
                  >
                    <span className={`lv-switch${toggles[key] ? " is-on" : ""}`} />
                    {label}
                  </button>
                ))}
              </div>
            </article>

            <article className="lv-panel lv-settings-card lv-danger-zone">
              <div className="lv-section-label">Danger Zone</div>
              <div className="lv-danger-actions">
                <div className="lv-danger-row">
                  <span>Clear All Conversations</span>
                  <button className="lv-btn lv-btn-danger" type="button" onClick={() => toast("Clear")}>
                    Clear
                  </button>
                </div>
                <div className="lv-danger-row">
                  <span>Reset All Settings</span>
                  <button className="lv-btn lv-btn-danger" type="button" onClick={() => toast("Reset")}>
                    Reset
                  </button>
                </div>
                <div className="lv-danger-row">
                  <span>Delete Local Data</span>
                  <button className="lv-btn lv-btn-danger" type="button" onClick={() => toast("Delete")}>
                    Delete
                  </button>
                </div>
              </div>
            </article>
          </div>
        </div>

        <p className="lv-footer-quote">“Small adjustments. Massive impact.” — LEVIATHAN</p>
      </main>
    </AppShell>
  );
}
