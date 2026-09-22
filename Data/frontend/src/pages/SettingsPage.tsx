import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { media } from "../assets/media";
import { AppShell } from "../layouts/AppShell";
import { useAppToast } from "../state/useAppToast";

const CATEGORIES = [
  { id: "algemeen", label: "Algemeen", desc: "App defaults & behavior", to: "/settings" },
  { id: "llm-gedrag", label: "LLM Gedrag", desc: "Response style & limits", to: "/settings/llm-gedrag" },
  { id: "llm-studio", label: "LLM Studio", desc: "Studio & playground prefs", to: "/settings/llm-studio" },
  { id: "rechten", label: "Rechten & Security", desc: "Access & audit", to: "/settings/rechten" },
  { id: "benchmarks", label: "Model Benchmarks", desc: "Eval defaults", to: "/settings/benchmarks" },
  { id: "mediacenter", label: "Mediacenter", desc: "Media defaults", to: "/settings/mediacenter" },
  { id: "opslag", label: "Opslag", desc: "Storage & backups", to: "/settings/opslag" },
  { id: "python", label: "Python & Runtime", desc: "Runtime & acceleration", to: "/settings/python" },
  { id: "settings-console", label: "Console", desc: "Operator console", to: "/settings/console" },
  { id: "logs", label: "Logs", desc: "Retention & verbosity", to: "/settings/logs" },
] as const;

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
  const navigate = useNavigate();
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

        <div className="lv-settings-layout">
          <aside className="lv-panel lv-settings-nav">
            {CATEGORIES.map((item) => (
              <button
                key={item.id}
                className={`lv-settings-nav-item${item.id === "algemeen" ? " is-active" : ""}`}
                type="button"
                onClick={() => navigate(item.to)}
              >
                <strong>{item.label}</strong>
                <small>{item.desc}</small>
              </button>
            ))}
          </aside>

          <div className="lv-settings-grid">
            <article className="lv-panel lv-settings-card">
              <div className="lv-section-label">Algemeen</div>
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
                <select id="language" className="lv-select" defaultValue="nl">
                  <option value="nl">Nederlands</option>
                  <option value="en">English</option>
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
                  <button key={key} className="lv-toggle" type="button" onClick={() => setToggle(key)}>
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
                  ["concurrent", "Concurrent Jobs", 1, 16],
                  ["timeout", "Timeout (s)", 30, 600],
                  ["memory", "Memory Cap %", 20, 100],
                  ["cpu", "CPU Cap %", 20, 100],
                ] as const
              ).map(([key, label, min, max]) => (
                <div key={key} className="lv-form-field">
                  <label htmlFor={key}>
                    {label}: {sliders[key]}
                  </label>
                  <input
                    id={key}
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
                  ["quantization", "Quantization"],
                  ["flashAttention", "Flash Attention"],
                  ["lowVram", "Low VRAM Mode"],
                ].map(([key, label]) => (
                  <button key={key} className="lv-toggle" type="button" onClick={() => setToggle(key)}>
                    <span className={`lv-switch${toggles[key] ? " is-on" : ""}`} />
                    {label}
                  </button>
                ))}
              </div>
            </article>

            <article className="lv-panel lv-settings-card">
              <div className="lv-section-label">API & Integrations</div>
              <div className="lv-toggle-stack">
                {INTEGRATIONS.map((item) => (
                  <button
                    key={item.name}
                    className="lv-toggle"
                    type="button"
                    onClick={() => toast(`${item.name}: ${item.status}`)}
                  >
                    <span className={`lv-switch${item.status === "Connected" ? " is-on" : ""}`} />
                    {item.name}
                    <small className="lv-muted" style={{ marginLeft: "auto" }}>
                      {item.status}
                    </small>
                  </button>
                ))}
              </div>
            </article>

            <article className="lv-panel lv-settings-card">
              <div className="lv-section-label">Notifications</div>
              <div className="lv-toggle-stack">
                {[
                  ["taskComplete", "Task Complete"],
                  ["errors", "Errors"],
                  ["modelStatus", "Model Status"],
                  ["longRunning", "Long Running Jobs"],
                  ["systemUpdates", "System Updates"],
                ].map(([key, label]) => (
                  <button key={key} className="lv-toggle" type="button" onClick={() => setToggle(key)}>
                    <span className={`lv-switch${toggles[key] ? " is-on" : ""}`} />
                    {label}
                  </button>
                ))}
              </div>
            </article>
          </div>
        </div>
      </main>
    </AppShell>
  );
}
