import { useState } from "react";
import { AppShell } from "../layouts/AppShell";
import { useAppToast } from "../state/useAppToast";

const ACTIONS = [
  { title: "Start Training", subtitle: "Launch a new job", tone: "create" },
  { title: "Fine-tune Model", subtitle: "Adapt an existing mind", tone: "research" },
  { title: "Train from Scratch", subtitle: "Build a new base", tone: "build" },
  { title: "Manage Jobs", subtitle: "Queue & monitor", tone: "analyze" },
  { title: "Compare Results", subtitle: "Eval & rank", tone: "research" },
] as const;

const FORM_TABS = ["General", "Model", "Dataset", "Training", "Advanced"] as const;

const ACTIVE_JOBS = [
  { name: "hades-coder-7b-sft", status: "running" as const, progress: 62 },
  { name: "leviathan-align-dpo", status: "running" as const, progress: 28 },
  { name: "market-embed-v2", status: "queued" as const, progress: 0 },
  { name: "agent-tool-sft", status: "completed" as const, progress: 100 },
  { name: "vision-pilot-lora", status: "failed" as const, progress: 41 },
];

const RECENT_RUNS = [
  { name: "hades-coder-7b-sft", type: "SFT", status: "Running", when: "Today 12:13" },
  { name: "leviathan-align-dpo", type: "DPO", status: "Running", when: "Today 11:40" },
  { name: "agent-tool-sft", type: "SFT", status: "Completed", when: "Yesterday" },
  { name: "pretrain-corpus-a", type: "Pretrain", status: "Completed", when: "Sep 16" },
  { name: "vision-pilot-lora", type: "SFT", status: "Failed", when: "Sep 15" },
];

const LOGS = [
  "[12:13:04] epoch 2/4 step 18420 loss=0.842",
  "[12:13:18] eval loss=0.791 lr=1.8e-5",
  "[12:13:41] checkpoint saved → /models/hades-coder-7b-sft",
  "[12:14:02] gradient norm=0.94",
  "[12:14:27] continuing training…",
];

export function TrainingPage() {
  const toast = useAppToast();
  const [formTab, setFormTab] = useState<(typeof FORM_TABS)[number]>("General");
  const [outputName, setOutputName] = useState("hades-coder-7b-sft");
  const [batchSize, setBatchSize] = useState("4");
  const [learningRate, setLearningRate] = useState("2e-5");
  const [epochs, setEpochs] = useState("4");

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Training Mode"
      searchPlaceholder="Search training runs, datasets, models..."
      pageClass="lv-app--training"
    >
      <main className="lv-main">
        <section className="lv-page-hero">
          <div className="lv-hero-media">
            <img src="/assets/architecture-bg.jpg" alt="" width={1400} height={380} />
          </div>
          <div className="lv-hero-shade" />
          <div className="lv-hero-content">
            <div className="lv-hero-kicker">
              <span />
              Build. Improve. Transcend.
              <span />
            </div>
            <h1 className="lv-hero-title">Model Training</h1>
            <p className="lv-page-quote">“Train with purpose. Intelligence compounds.”</p>
          </div>
          <div className="lv-hero-rail" aria-hidden="true">
            <span>Data</span>
            <span>Training</span>
            <span>Alignment</span>
            <span>Evaluation</span>
            <span>Deployment</span>
          </div>
        </section>

        <div className="lv-action-row">
          {ACTIONS.map((action) => (
            <button
              key={action.title}
              className="lv-action-card"
              type="button"
              onClick={() => toast(action.title)}
            >
              <span className={`lv-feature-icon ${action.tone}`}>
                <svg className="lv-icon" viewBox="0 0 24 24">
                  <path d="M8 6l12 6-12 6V6z" />
                </svg>
              </span>
              <strong>{action.title}</strong>
              <small>{action.subtitle}</small>
            </button>
          ))}
        </div>

        <div className="lv-training-grid">
          <article className="lv-panel lv-card">
            <div className="lv-card-head">
              <div className="lv-section-label">Training Configuration</div>
            </div>
            <div className="lv-tabs" role="tablist">
              {FORM_TABS.map((item) => (
                <button
                  key={item}
                  className={`lv-tab${formTab === item ? " is-active" : ""}`}
                  type="button"
                  onClick={() => setFormTab(item)}
                >
                  {item}
                </button>
              ))}
            </div>

            {formTab === "General" ? (
              <div className="lv-form-grid">
                <div className="lv-form-field">
                  <label htmlFor="train-type">Training Type</label>
                  <select id="train-type" className="lv-select" defaultValue="sft">
                    <option value="sft">Supervised Fine-Tune</option>
                    <option value="dpo">DPO Alignment</option>
                    <option value="pretrain">Pretrain</option>
                  </select>
                </div>
                <div className="lv-form-field">
                  <label htmlFor="train-objective">Training Objective</label>
                  <select id="train-objective" className="lv-select" defaultValue="code">
                    <option value="code">Code Assistance</option>
                    <option value="chat">Chat</option>
                    <option value="agent">Agent Tools</option>
                  </select>
                </div>
                <div className="lv-form-field">
                  <label htmlFor="base-model">Base Model</label>
                  <select id="base-model" className="lv-select" defaultValue="qwen">
                    <option value="qwen">Qwen2.5-Coder-7B</option>
                    <option value="llama">Llama 3.1 8B</option>
                    <option value="mixtral">Mixtral 8x7B</option>
                  </select>
                </div>
                <div className="lv-form-field">
                  <label htmlFor="context-length">Context Length</label>
                  <select id="context-length" className="lv-select" defaultValue="32k">
                    <option value="8k">8K</option>
                    <option value="32k">32K</option>
                    <option value="128k">128K</option>
                  </select>
                </div>
                <div className="lv-form-field">
                  <label htmlFor="dataset">Dataset</label>
                  <select id="dataset" className="lv-select" defaultValue="code-sft">
                    <option value="code-sft">leviathan-code-sft</option>
                    <option value="chat">leviathan-chat-v3</option>
                    <option value="tools">agent-tools-mix</option>
                  </select>
                </div>
                <div className="lv-form-field">
                  <label htmlFor="precision">Precision</label>
                  <select id="precision" className="lv-select" defaultValue="bf16">
                    <option value="bf16">BF16</option>
                    <option value="fp16">FP16</option>
                    <option value="qlora">QLoRA</option>
                  </select>
                </div>
                <div className="lv-form-field">
                  <label htmlFor="output-name">Output Name</label>
                  <input
                    id="output-name"
                    className="lv-input"
                    value={outputName}
                    onChange={(event) => setOutputName(event.target.value)}
                  />
                </div>
                <div className="lv-form-field">
                  <label htmlFor="batch-size">Batch Size</label>
                  <input
                    id="batch-size"
                    className="lv-input"
                    value={batchSize}
                    onChange={(event) => setBatchSize(event.target.value)}
                  />
                </div>
                <div className="lv-form-field full">
                  <label htmlFor="output-path">Output Path</label>
                  <input
                    id="output-path"
                    className="lv-input"
                    style={{ width: "100%" }}
                    defaultValue="/models/hades-coder-7b-sft"
                  />
                </div>
                <div className="lv-form-field">
                  <label htmlFor="lr">Learning Rate</label>
                  <input
                    id="lr"
                    className="lv-input"
                    value={learningRate}
                    onChange={(event) => setLearningRate(event.target.value)}
                  />
                </div>
                <div className="lv-form-field">
                  <label htmlFor="epochs">Epochs</label>
                  <input
                    id="epochs"
                    className="lv-input"
                    value={epochs}
                    onChange={(event) => setEpochs(event.target.value)}
                  />
                </div>
              </div>
            ) : (
              <p className="lv-node-desc">
                {formTab} settings are mock placeholders for the upcoming training pipeline.
              </p>
            )}

            <div className="lv-form-actions">
              <button className="lv-btn" type="button" onClick={() => toast("Save Preset")}>
                Save Preset
              </button>
              <button className="lv-btn lv-btn-gold" type="button" onClick={() => toast("Start Training")}>
                Start Training
              </button>
            </div>
          </article>

          <article className="lv-panel lv-card">
            <div className="lv-job-head">
              <div>
                <div className="lv-section-label">Training Progress</div>
                <strong style={{ color: "var(--lv-text-bright)" }}>hades-coder-7b-sft</strong>
              </div>
              <span className="lv-model-status">
                <span className="lv-status-dot running" />
                Running · 2h 14m · ETA 1h 26m
              </span>
            </div>

            <div className="lv-meta-item">
              <span>Progress</span>
              <strong>62%</strong>
            </div>
            <div className="lv-progress">
              <span style={{ width: "62%" }} />
            </div>

            <div className="lv-job-metrics">
              <div className="lv-metric">
                <span>Epoch</span>
                <strong>2 / 4</strong>
              </div>
              <div className="lv-metric">
                <span>Step</span>
                <strong>18,420</strong>
              </div>
              <div className="lv-metric">
                <span>Loss</span>
                <strong>0.842</strong>
              </div>
              <div className="lv-metric">
                <span>LR</span>
                <strong>1.8e-5</strong>
              </div>
            </div>

            <svg className="lv-chart" viewBox="0 0 420 140" preserveAspectRatio="none" aria-label="Loss chart">
              <polyline
                fill="none"
                stroke="#4285E8"
                strokeWidth="2"
                points="0,110 40,98 80,102 120,86 160,78 200,70 240,66 280,58 320,52 360,48 400,42"
              />
              <polyline
                fill="none"
                stroke="#20DC8C"
                strokeWidth="2"
                points="0,118 40,112 80,108 120,100 160,94 200,88 240,84 280,78 320,74 360,70 400,66"
              />
              <polyline
                fill="none"
                stroke="#DB8A34"
                strokeWidth="1.5"
                strokeDasharray="4 3"
                points="0,20 40,24 80,28 120,34 160,40 200,48 240,56 280,66 320,78 360,92 400,108"
              />
            </svg>

            <pre className="lv-console">{LOGS.join("\n")}</pre>
          </article>
        </div>

        <div className="lv-bottom-modules">
          <article className="lv-panel lv-card">
            <div className="lv-section-label">Training Templates</div>
            <div className="lv-module-actions">
              {["Code Model", "Chat Model", "Agent Model", "Multimodal"].map((item) => (
                <button key={item} className="lv-btn" type="button" onClick={() => toast(item)}>
                  {item}
                </button>
              ))}
            </div>
          </article>
          <article className="lv-panel lv-card">
            <div className="lv-section-label">Evaluation</div>
            <div className="lv-module-actions">
              {["Run Evaluation", "Compare Models", "Generate Report"].map((item) => (
                <button key={item} className="lv-btn" type="button" onClick={() => toast(item)}>
                  {item}
                </button>
              ))}
            </div>
          </article>
          <article className="lv-panel lv-card">
            <div className="lv-section-label">Deployment</div>
            <div className="lv-module-actions">
              {["Export Model", "Deploy Locally", "Deploy to Cloud"].map((item) => (
                <button key={item} className="lv-btn" type="button" onClick={() => toast(item)}>
                  {item}
                </button>
              ))}
            </div>
          </article>
        </div>

        <p className="lv-footer-quote">“Better models create new worlds.” — LEVIATHAN</p>
      </main>

      <aside className="lv-right">
        <article className="lv-panel lv-card">
          <div className="lv-section-label">Compute Resources</div>
          <div className="lv-gauges">
            <div className="lv-gauge">
              <div className="lv-ring gold" style={{ ["--p" as string]: 78 }}>
                <b>78%</b>
              </div>
              <span>GPU</span>
            </div>
            <div className="lv-gauge">
              <div className="lv-ring cyan" style={{ ["--p" as string]: 34 }}>
                <b>34%</b>
              </div>
              <span>CPU</span>
            </div>
            <div className="lv-gauge">
              <div className="lv-ring cyan" style={{ ["--p" as string]: 62 }}>
                <b>62%</b>
              </div>
              <span>RAM</span>
            </div>
            <div className="lv-gauge">
              <div className="lv-ring cyan" style={{ ["--p" as string]: 41 }}>
                <b>41%</b>
              </div>
              <span>Disk</span>
            </div>
          </div>
        </article>

        <article className="lv-panel lv-card">
          <div className="lv-section-label">Active Training Jobs</div>
          <div className="lv-job-list">
            {ACTIVE_JOBS.map((job) => (
              <div key={job.name} className="lv-job-row">
                <span className={`lv-status-dot ${job.status === "completed" ? "ready" : job.status}`} />
                <div>
                  <strong>{job.name}</strong>
                  <small>{job.status}</small>
                </div>
                <strong>{job.progress}%</strong>
              </div>
            ))}
          </div>
        </article>

        <article className="lv-panel lv-card">
          <div className="lv-section-label">Recent Training Runs</div>
          <div className="lv-recent-list">
            {RECENT_RUNS.map((run) => (
              <button
                key={run.name}
                className="lv-recent-row"
                type="button"
                onClick={() => toast(run.name)}
              >
                <span>
                  {run.name}
                  <small style={{ display: "block", color: "var(--lv-text-muted)" }}>
                    {run.type} · {run.status}
                  </small>
                </span>
                <time>{run.when}</time>
              </button>
            ))}
          </div>
        </article>
      </aside>
    </AppShell>
  );
}
