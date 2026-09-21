import { useState } from "react";
import { media } from "../assets/media";
import { AppShell } from "../layouts/AppShell";
import { useAppToast } from "../state/useAppToast";

const KPIS = [
  { label: "Total Training Jobs", value: "24", meta: "+33% this month", spark: [10, 14, 18, 16, 22, 28, 30, 36] },
  { label: "Active Runs", value: "3", meta: "2 queued", spark: [8, 10, 12, 11, 14, 16, 18, 20] },
  { label: "GPU Availability", value: "87%", meta: "7 / 8 GPUs online", spark: [70, 72, 75, 78, 80, 84, 86, 87] },
  { label: "Best Validation Score", value: "0.9243", meta: "+2.1%", spark: [80, 82, 84, 86, 88, 90, 91, 92] },
] as const;

const GPUS = [
  { id: 0, vram: "21.4 / 24 GB", util: 94, temp: "71°C", power: "312W", status: "Online" },
  { id: 1, vram: "20.8 / 24 GB", util: 91, temp: "69°C", power: "298W", status: "Online" },
  { id: 2, vram: "19.6 / 24 GB", util: 88, temp: "68°C", power: "286W", status: "Online" },
  { id: 3, vram: "18.2 / 24 GB", util: 82, temp: "66°C", power: "274W", status: "Online" },
  { id: 4, vram: "17.4 / 24 GB", util: 79, temp: "65°C", power: "261W", status: "Online" },
  { id: 5, vram: "16.1 / 24 GB", util: 74, temp: "63°C", power: "248W", status: "Online" },
  { id: 6, vram: "15.2 / 24 GB", util: 68, temp: "61°C", power: "232W", status: "Online" },
  { id: 7, vram: "0.4 / 24 GB", util: 4, temp: "42°C", power: "48W", status: "Online" },
] as const;

const CHECKPOINTS = [
  { name: "ra-v3-ep068", epoch: 68, loss: "0.0417", size: "6.8 GB", when: "2m ago" },
  { name: "ra-v3-ep060", epoch: 60, loss: "0.0482", size: "6.8 GB", when: "28m ago" },
  { name: "ra-v3-ep050", epoch: 50, loss: "0.0561", size: "6.8 GB", when: "1h ago" },
  { name: "ra-v3-ep040", epoch: 40, loss: "0.0714", size: "6.8 GB", when: "2h ago" },
] as const;

const METRICS = [
  { name: "Validation Loss", value: "0.0417", delta: "-12.3%", up: false },
  { name: "Perplexity", value: "8.42", delta: "-6.8%", up: false },
  { name: "Accuracy", value: "91.4%", delta: "+2.1%", up: true },
  { name: "F1 Score", value: "0.903", delta: "+1.6%", up: true },
] as const;

const LOGS = [
  "[14:27:18] INFO Step 12480/18400 loss=0.0324 lr=2.0e-5",
  "[14:27:12] INFO Validation loss=0.0417 perplexity=8.42",
  "[14:26:58] INFO Checkpoint saved → /models/runs/ra-v3-20250422_1420",
  "[14:26:41] WARN Grad norm spiked to 1.84 — clipped",
  "[14:26:20] INFO Epoch 68/100 completed in 2m 48s",
] as const;

const EXPERIMENTS = [
  { name: "Research-Assistant-v3", base: "Llama-3-8B", dataset: "Research-v2", status: "Training", progress: 68 },
  { name: "hades-coder-7b-sft", base: "Qwen2.5-7B", dataset: "Code-SFT", status: "Completed", progress: 100 },
  { name: "align-dpo-v1", base: "Llama-3-8B", dataset: "Prefs-v1", status: "Queued", progress: 0 },
] as const;

function Spark({ points }: { points: readonly number[] }) {
  const max = Math.max(...points);
  const min = Math.min(...points);
  const d = points
    .map((v, i) => {
      const x = (i / (points.length - 1)) * 70;
      const y = 20 - ((v - min) / (max - min || 1)) * 16;
      return `${i === 0 ? "M" : "L"}${x},${y}`;
    })
    .join(" ");
  return (
    <svg className="lv-tn-spark" viewBox="0 0 70 22" aria-hidden="true">
      <path d={d} fill="none" stroke="#22C9D6" strokeWidth="1.5" />
    </svg>
  );
}

function LossChart() {
  return (
    <svg className="lv-tn-chart" viewBox="0 0 520 220" role="img" aria-label="Training progress chart">
      {[0, 1, 2, 3, 4].map((i) => (
        <line key={i} x1="40" x2="500" y1={20 + i * 40} y2={20 + i * 40} stroke="rgba(214,169,87,0.1)" />
      ))}
      <path
        d="M40,40 C90,55 140,70 180,95 C230,125 280,145 330,155 C380,165 430,170 500,175"
        fill="none"
        stroke="#22C9D6"
        strokeWidth="2"
      />
      <path
        d="M40,48 C90,62 140,80 180,105 C230,132 280,150 330,158 C380,166 430,172 500,178"
        fill="none"
        stroke="#20DC8C"
        strokeWidth="2"
      />
      <path d="M40,190 C180,160 320,120 500,80" fill="none" stroke="#D6A957" strokeWidth="1.5" opacity="0.8" />
      <line x1="360" x2="360" y1="20" y2="200" stroke="rgba(32,220,140,0.35)" strokeDasharray="3 3" />
      <rect x="368" y="34" width="120" height="72" rx="8" fill="rgba(5,7,6,0.92)" stroke="rgba(214,169,87,0.25)" />
      <text x="378" y="52" className="lv-tn-axis">Epoch 68 / 100</text>
      <text x="378" y="68" className="lv-tn-axis">Train 0.0324</text>
      <text x="378" y="84" className="lv-tn-axis">Val 0.0417</text>
      <text x="378" y="100" className="lv-tn-axis">LR 2.0e-5</text>
      <text x="40" y="214" className="lv-tn-axis">0</text>
      <text x="490" y="214" className="lv-tn-axis">100</text>
    </svg>
  );
}

export function TrainingPage() {
  const toast = useAppToast();
  const [method, setMethod] = useState<"Full" | "LoRA">("LoRA");
  const [checkpointing, setCheckpointing] = useState(true);

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Training Mode"
      searchPlaceholder="Search models, datasets, experiments, or ask Leviathan..."
      layout="wide"
      pageClass="lv-app--training"
    >
      <main className="lv-main lv-tn-main">
        <section className="lv-tn-hero" aria-label="Model Training">
          <img src={media.trainingHero} alt="" width={1400} height={220} />
        </section>

        <section className="lv-tn-kpi-row">
          {KPIS.map((item) => (
            <article key={item.label} className="lv-tn-kpi">
              <div className="lv-tn-kpi-label">{item.label}</div>
              <div className="lv-tn-kpi-value">{item.value}</div>
              <div className="lv-tn-kpi-foot">
                <span>{item.meta}</span>
                <Spark points={item.spark} />
              </div>
            </article>
          ))}
        </section>

        <section className="lv-tn-mid">
          <article className="lv-panel lv-tn-card">
            <div className="lv-tn-card-head">
              <div className="lv-section-label">Training Progress</div>
              <span className="lv-tn-live">Live</span>
            </div>
            <div className="lv-tn-legend">
              <span>
                <i style={{ background: "#22C9D6" }} /> Training Loss
              </span>
              <span>
                <i style={{ background: "#20DC8C" }} /> Validation Loss
              </span>
              <span>
                <i style={{ background: "#D6A957" }} /> Learning Rate
              </span>
            </div>
            <LossChart />
          </article>

          <article className="lv-panel lv-tn-card">
            <div className="lv-tn-card-head">
              <div className="lv-section-label">Training Configuration</div>
              <button type="button" className="lv-tn-mini" onClick={() => toast("Load preset")}>
                Load Preset
              </button>
            </div>
            <div className="lv-tn-form">
              {[
                ["Base Model", "Llama-3-8B-Instruct"],
                ["Dataset", "Leviathan-Research-v2"],
                ["Training Method", "Supervised Fine-tuning (SFT)"],
                ["Optimizer", "AdamW"],
                ["Scheduler", "Cosine with Warmup"],
                ["Precision", "Mixed Precision (FP16)"],
              ].map(([label, value]) => (
                <label key={label} className="lv-tn-field">
                  <span>{label}</span>
                  <select defaultValue={value}>
                    <option>{value}</option>
                  </select>
                </label>
              ))}
              <label className="lv-tn-field">
                <span>Sequence Length</span>
                <input defaultValue="4096" />
              </label>
              <label className="lv-tn-field">
                <span>Batch Size</span>
                <input defaultValue="32" />
              </label>
              <div className="lv-tn-method">
                <span>Fine-tuning Type</span>
                <div>
                  <button type="button" className={method === "Full" ? "is-active" : ""} onClick={() => setMethod("Full")}>
                    Full Finetune
                  </button>
                  <button type="button" className={method === "LoRA" ? "is-active" : ""} onClick={() => setMethod("LoRA")}>
                    LoRA
                  </button>
                </div>
              </div>
              {method === "LoRA" && (
                <label className="lv-tn-field">
                  <span>LoRA Rank</span>
                  <input defaultValue="64" />
                </label>
              )}
              <label className="lv-tn-toggle">
                <span>Grad Checkpointing</span>
                <button type="button" className={checkpointing ? "is-on" : ""} onClick={() => setCheckpointing((v) => !v)}>
                  {checkpointing ? "Enabled" : "Off"}
                </button>
              </label>
            </div>
          </article>

          <article className="lv-panel lv-tn-card">
            <div className="lv-tn-card-head">
              <div className="lv-section-label">Run Status</div>
              <span className="lv-tn-pill">Training</span>
            </div>
            <strong className="lv-tn-run-name">Research-Assistant-v3</strong>
            <p className="lv-tn-run-sub">Fine-tuning Llama-3-8B on domain data</p>
            <div className="lv-tn-progress">
              <div>
                <span>Progress</span>
                <strong>68%</strong>
              </div>
              <div className="lv-tn-bar">
                <span style={{ width: "68%" }} />
              </div>
            </div>
            <ul className="lv-tn-stats">
              <li>
                <span>Epoch</span>
                <strong>68 / 100</strong>
              </li>
              <li>
                <span>Step</span>
                <strong>12,480 / 18,400</strong>
              </li>
              <li>
                <span>Elapsed</span>
                <strong>03:27:18</strong>
              </li>
              <li>
                <span>ETA</span>
                <strong>01:36:52</strong>
              </li>
              <li>
                <span>Current Loss</span>
                <strong>0.0324</strong>
              </li>
              <li>
                <span>Validation Loss</span>
                <strong>0.0417</strong>
              </li>
              <li>
                <span>Output Path</span>
                <strong className="lv-tn-path">/models/runs/ra-v3-20250422_1420</strong>
              </li>
            </ul>
            <div className="lv-tn-run-actions">
              <button type="button" onClick={() => toast("Paused")}>
                Pause
              </button>
              <button type="button" className="danger" onClick={() => toast("Stop requested")}>
                Stop
              </button>
            </div>
          </article>
        </section>

        <section className="lv-tn-lower">
          <article className="lv-panel lv-tn-card">
            <div className="lv-section-label">GPU & System Resources</div>
            <div className="lv-tn-table-wrap">
              <table className="lv-tn-table">
                <thead>
                  <tr>
                    <th>GPU</th>
                    <th>VRAM</th>
                    <th>Util</th>
                    <th>Temp</th>
                    <th>Power</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {GPUS.map((g) => (
                    <tr key={g.id}>
                      <td>GPU {g.id}</td>
                      <td>{g.vram}</td>
                      <td>
                        <div className="lv-tn-util">
                          <span style={{ width: `${g.util}%` }} />
                        </div>
                        {g.util}%
                      </td>
                      <td>{g.temp}</td>
                      <td>{g.power}</td>
                      <td className="is-online">{g.status}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="lv-tn-sysbars">
              <div>
                <div>
                  <span>System RAM</span>
                  <strong>126 / 256 GB · 49%</strong>
                </div>
                <div className="lv-tn-bar">
                  <span style={{ width: "49%" }} />
                </div>
              </div>
              <div>
                <div>
                  <span>Disk Usage</span>
                  <strong>1.2 / 4.0 TB · 30%</strong>
                </div>
                <div className="lv-tn-bar">
                  <span style={{ width: "30%" }} />
                </div>
              </div>
            </div>
          </article>

          <article className="lv-panel lv-tn-card">
            <div className="lv-section-label">Checkpoints</div>
            <ul className="lv-tn-list">
              {CHECKPOINTS.map((c) => (
                <li key={c.name}>
                  <strong>{c.name}</strong>
                  <span>
                    Ep {c.epoch} · Val {c.loss}
                  </span>
                  <em>
                    {c.size} · {c.when}
                  </em>
                </li>
              ))}
            </ul>
          </article>

          <article className="lv-panel lv-tn-card">
            <div className="lv-section-label">Evaluation Metrics</div>
            <ul className="lv-tn-metrics">
              {METRICS.map((m) => (
                <li key={m.name}>
                  <span>{m.name}</span>
                  <strong>{m.value}</strong>
                  <em className={m.up ? "is-good" : "is-good"}>{m.delta}</em>
                </li>
              ))}
            </ul>
          </article>
        </section>

        <section className="lv-tn-footer-row">
          <article className="lv-panel lv-tn-card lv-tn-logs">
            <div className="lv-section-label">Training Logs</div>
            <pre>{LOGS.join("\n")}</pre>
          </article>
          <article className="lv-panel lv-tn-card">
            <div className="lv-section-label">Quick Actions</div>
            <div className="lv-tn-actions">
              {["Start Training", "Save Preset", "Open Logs", "Evaluate Model", "Deploy to Models"].map((label, i) => (
                <button key={label} type="button" className={i === 0 ? "primary" : ""} onClick={() => toast(label)}>
                  {label}
                </button>
              ))}
            </div>
            <div className="lv-section-label" style={{ marginTop: 10 }}>
              Active Experiments
            </div>
            <ul className="lv-tn-experiments">
              {EXPERIMENTS.map((e) => (
                <li key={e.name}>
                  <div>
                    <strong>{e.name}</strong>
                    <small>
                      {e.base} · {e.dataset} · {e.status}
                    </small>
                  </div>
                  <div className="lv-tn-bar compact">
                    <span style={{ width: `${e.progress}%` }} />
                  </div>
                </li>
              ))}
            </ul>
          </article>
        </section>

        <p className="lv-footer-quote">“Greater intelligence is not built in a day, but in the deliberate compounding of effort.” — LEVIATHAN</p>
      </main>
    </AppShell>
  );
}
