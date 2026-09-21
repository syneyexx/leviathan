/** FINALBETA — Model Training Overzicht tab (current Training Control body). */
import type { ReactNode } from "react";
import { FbIcon } from "../../icons";

export function TrainingTabOverzicht({ tabs }: { tabs?: ReactNode }) {
  return (
    <div className="training-overzicht">
      <div className="page-head">
        <div>
          <h1 className="page-title">Training Control</h1>
          <p className="page-sub">
            Train modellen en het HADES framework vanuit één gecontroleerde lokale werkomgeving.
          </p>
        </div>
        <div className="page-actions">
          <button className="btn btn-outline" type="button" data-toast="ATME benchmark gestart (demo)">
            <FbIcon name="bolt" size={14} />
            ATME benchmark
          </button>
          <button className="btn btn-gold" type="button" data-toast="Nieuwe training wizard (demo)">
            <FbIcon name="plus" size={14} />
            Nieuwe training
          </button>
        </div>
      </div>

      {tabs}

      <div className="status-strip">
        <div className="card status-card">
          <div className="status-ico ok">
            <FbIcon name="check" size={16} />
          </div>
          <div className="status-meta">
            <span className="status-value">Trainer gereed</span>
            <span className="status-hint">Trainingsomgeving online</span>
          </div>
        </div>

        <div className="card status-card">
          <div className="status-ico ring">
            <FbIcon name="grid" size={15} />
          </div>
          <div className="status-meta">
            <span className="status-label">GPU / VRAM</span>
            <span className="status-value">NVIDIA RTX 4090</span>
            <span className="status-hint">18.4 / 24 GB</span>
            <div className="bar-row">
              <div className="bar">
                <span style={{ width: "77%" }} />
              </div>
              <span className="bar-pct">77%</span>
            </div>
          </div>
        </div>

        <div className="card status-card">
          <div className="status-ico doc">
            <FbIcon name="database" size={15} />
          </div>
          <div className="status-meta">
            <span className="status-value">Dataset Brain</span>
            <span className="status-hint">3 datasets actief</span>
            <span className="status-hint">142.6K voorbeelden</span>
          </div>
        </div>

        <div className="card status-card">
          <div className="status-ico ring-gold">
            <FbIcon name="play" size={14} />
          </div>
          <div className="status-meta">
            <span className="status-label">Actieve run</span>
            <span className="status-value">HADES-Llama-8B</span>
            <span className="status-hint">Stap 2.480 / 10.000</span>
            <div className="bar-row">
              <div className="bar">
                <span style={{ width: "24%" }} />
              </div>
              <span className="bar-pct">24%</span>
            </div>
          </div>
        </div>
      </div>

      <div className="work-grid">
        <div className="stack">
          <section className="card card-pad">
            <div className="config-head">
              <div>
                <h2 className="section-title">Nieuwe training configureren</h2>
                <p className="section-sub">
                  Stel hier je training samen. Kies tussen model training of framework training.
                </p>
              </div>
            </div>

            <div className="mode-grid">
              <button className="mode-card active" type="button" data-mode="model">
                <span className="mode-ico">
                  <FbIcon name="brain" size={16} />
                </span>
                <span>
                  <span className="mode-title">Model trainen</span>
                  <span className="mode-desc">Fine-tune een bestaand model met je eigen datasets.</span>
                </span>
              </button>
              <button className="mode-card" type="button" data-mode="framework">
                <span className="mode-ico">
                  <FbIcon name="grid" size={16} />
                </span>
                <span>
                  <span className="mode-title">Framework trainen</span>
                  <span className="mode-desc">Train de HADES Neural framework (op maat van jouw omgeving).</span>
                </span>
              </button>
            </div>

            <div className="config-body">
              <div className="form-grid">
                <label className="field">
                  <span className="field-label">Dataset</span>
                  <select className="control" defaultValue="HADES-Chat (Dataset Brain)">
                    <option>HADES-Chat (Dataset Brain)</option>
                    <option>Custom Instruct Mix</option>
                    <option>Research Corpus v3</option>
                  </select>
                </label>
                <label className="field">
                  <span className="field-label">Batch size</span>
                  <select className="control" defaultValue="4">
                    <option>4</option>
                    <option>2</option>
                    <option>8</option>
                  </select>
                </label>
                <label className="field">
                  <span className="field-label">Base model</span>
                  <select className="control" defaultValue="meta-llama/Llama-3.1-8B-Instruct">
                    <option>meta-llama/Llama-3.1-8B-Instruct</option>
                    <option>Qwen/Qwen2.5-14B-Instruct</option>
                    <option>mistralai/Mistral-7B-Instruct-v0.3</option>
                  </select>
                </label>
                <label className="field">
                  <span className="field-label">Grad accumulation</span>
                  <select className="control" defaultValue="8">
                    <option>8</option>
                    <option>4</option>
                    <option>16</option>
                  </select>
                </label>
                <label className="field">
                  <span className="field-label">Trainingsstrategie</span>
                  <select className="control" defaultValue="ATME (Adaptive)">
                    <option>ATME (Adaptive)</option>
                    <option>Fixed schedule</option>
                    <option>Memory-first</option>
                  </select>
                </label>
                <label className="field">
                  <span className="field-label">Learning rate</span>
                  <select className="control" defaultValue="2e-4">
                    <option>2e-4</option>
                    <option>1e-4</option>
                    <option>5e-5</option>
                  </select>
                </label>
                <label className="field">
                  <span className="field-label">Mode</span>
                  <select className="control" defaultValue="QLoRA (4-bit)">
                    <option>QLoRA (4-bit)</option>
                    <option>LoRA (16-bit)</option>
                    <option>Full fine-tune</option>
                  </select>
                </label>
                <label className="field">
                  <span className="field-label">Max steps</span>
                  <select className="control" defaultValue="10000">
                    <option>10000</option>
                    <option>5000</option>
                    <option>20000</option>
                  </select>
                </label>
                <label className="field">
                  <span className="field-label">Sequence length</span>
                  <select className="control" defaultValue="4096">
                    <option>4096</option>
                    <option>2048</option>
                    <option>8192</option>
                  </select>
                </label>
                <div className="field">
                  <span className="field-label">LoRA r / alpha</span>
                  <div className="lora-pair">
                    <input className="control" defaultValue="64" />
                    <input className="control" defaultValue="128" />
                  </div>
                </div>
                <label className="field">
                  <span className="field-label">LoRA dropout</span>
                  <select className="control" defaultValue="0.05">
                    <option>0.05</option>
                    <option>0.1</option>
                    <option>0.0</option>
                  </select>
                </label>
                <label className="field">
                  <span className="field-label">Activation checkpointing</span>
                  <select className="control" defaultValue="Aan (aanbevolen)">
                    <option>Aan (aanbevolen)</option>
                    <option>Uit</option>
                  </select>
                </label>
              </div>

              <aside className="exec-plan">
                <h3 className="exec-title">Execution Plan</h3>
                <div className="exec-row">
                  <span>Strategie</span>
                  <span>ATME (Adaptive)</span>
                </div>
                <div className="exec-row">
                  <span>Geschat VRAM piek</span>
                  <span>14.2 GB</span>
                </div>
                <div className="exec-row">
                  <span>Geschat RAM piek</span>
                  <span>32.1 GB</span>
                </div>
                <div className="exec-row">
                  <span>Verwachte bottleneck</span>
                  <span>VRAM</span>
                </div>
                <div className="exec-row">
                  <span>Vertrouwen</span>
                  <span className="exec-conf">92%</span>
                </div>
                <div className="exec-note">
                  <span className="info">i</span>
                  <span>Deze schatting is gebaseerd op je hardwareprofiel en gekozen instellingen.</span>
                </div>
              </aside>
            </div>

            <div className="config-actions">
              <button className="btn btn-outline-blue" type="button" data-toast="Modelinspectie (demo)">
                <FbIcon name="search" size={14} />
                Model inspecteren
              </button>
              <button className="btn btn-gold" type="button" data-toast="Training gestart (demo)">
                <FbIcon name="play" size={14} />
                Training starten
              </button>
            </div>
          </section>

          <section className="card active-panel">
            <div className="active-head">
              <div className="active-head-left">
                <FbIcon name="file" size={15} />
                <div>
                  <h2 className="section-title">Actieve training</h2>
                  <p className="section-sub">Realtime voortgang en statistieken van de huidige run.</p>
                </div>
              </div>
            </div>

            <div className="run-line">
              <div>
                <div className="run-name">
                  HADES-Llama-8B
                  <span className="tag gold">QLoRA</span>
                </div>
                <div className="run-base">meta-llama/Llama-3.1-8B-Instruct · HADES-Chat</div>
              </div>
              <div className="run-progress-meta">Stap 2.480 / 10.000 · 24%</div>
            </div>
            <div className="bar">
              <span style={{ width: "24%" }} />
            </div>
            <div style={{ marginTop: 6, fontSize: 11, color: "var(--muted)" }}>Resterende tijd: 1u 34m</div>

            <div className="metrics-row">
              <div className="metric">
                <div className="metric-label">Train loss</div>
                <div className="metric-value">0.842</div>
                <div className="metric-hint up">▼ −12.4%</div>
              </div>
              <div className="metric">
                <div className="metric-label">Piek VRAM</div>
                <div className="metric-value">13.6 GB</div>
                <div className="metric-hint">71%</div>
              </div>
              <div className="metric">
                <div className="metric-label">Piek RAM</div>
                <div className="metric-value">28.4 GB</div>
                <div className="metric-hint">56%</div>
              </div>
              <div className="metric">
                <div className="metric-label">Bottleneck</div>
                <div className="metric-value orange">VRAM</div>
                <div className="metric-hint orange">71%</div>
              </div>
            </div>

            <div className="chart-card">
              <div className="chart-head">
                <span>Training loss (laatste 500 stappen)</span>
                <span>Smoothing: 0.6</span>
              </div>
              <svg className="chart-svg" viewBox="0 0 640 120" preserveAspectRatio="none" aria-hidden="true">
                <defs>
                  <linearGradient id="mtLossFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#f0b429" stopOpacity="0.22" />
                    <stop offset="100%" stopColor="#f0b429" stopOpacity="0" />
                  </linearGradient>
                </defs>
                <g stroke="#1a2b3a" strokeWidth="1">
                  <line x1="0" y1="20" x2="640" y2="20" />
                  <line x1="0" y1="50" x2="640" y2="50" />
                  <line x1="0" y1="80" x2="640" y2="80" />
                  <line x1="0" y1="110" x2="640" y2="110" />
                </g>
                <path
                  d="M0,28 C40,34 60,22 90,40 C120,58 140,48 170,55 C200,62 220,42 250,48 C280,54 300,70 330,58 C360,46 380,62 410,52 C440,42 460,68 490,60 C520,52 540,72 570,66 C600,60 620,78 640,74 L640,120 L0,120 Z"
                  fill="url(#mtLossFill)"
                />
                <path
                  d="M0,28 C40,34 60,22 90,40 C120,58 140,48 170,55 C200,62 220,42 250,48 C280,54 300,70 330,58 C360,46 380,62 410,52 C440,42 460,68 490,60 C520,52 540,72 570,66 C600,60 620,78 640,74"
                  fill="none"
                  stroke="#f0b429"
                  strokeWidth="2.2"
                  strokeLinecap="round"
                />
              </svg>
            </div>

            <div className="active-actions">
              <button className="btn btn-outline" type="button" data-toast="Log geopend (demo)">
                <FbIcon name="file" size={14} />
                Log openen
              </button>
              <button className="btn btn-danger" type="button" data-toast="Stop training bevestigen (demo)">
                <FbIcon name="stop" size={14} />
                Stop training
              </button>
            </div>
          </section>
        </div>

        <div className="mid-stack">
          <section className="card widget">
            <div className="widget-head">
              <FbIcon name="database" size={14} />
              <span className="widget-title">Dataset pipeline</span>
            </div>
            <p className="widget-sub">Geselecteerde datasets voor deze run.</p>
            <div className="pipe-item">
              <div className="pipe-ico">
                <FbIcon name="globe" size={14} />
              </div>
              <div className="pipe-body">
                <div className="pipe-name">Hugging Face</div>
                <div className="pipe-path">HuggingFaceTB/smoltalk</div>
                <div className="pipe-meta">
                  <span className="pipe-count">12.4K voorbeelden</span>
                  <span className="tag">Sync</span>
                </div>
              </div>
            </div>
            <div className="pipe-item">
              <div className="pipe-ico">
                <FbIcon name="folder" size={14} />
              </div>
              <div className="pipe-body">
                <div className="pipe-name">Lokale dataset</div>
                <div className="pipe-path">D:\HADES\data\custom-instruct</div>
                <div className="pipe-meta">
                  <span className="pipe-count">8.1K voorbeelden</span>
                  <span className="tag">Lokaal</span>
                </div>
              </div>
            </div>
            <div className="pipe-item">
              <div className="pipe-ico">
                <FbIcon name="database" size={14} />
              </div>
              <div className="pipe-body">
                <div className="pipe-name">Dataset Brain snapshot</div>
                <div className="pipe-path">HADES Knowledge v1.2</div>
                <div className="pipe-meta">
                  <span className="pipe-count">122.1K voorbeelden</span>
                  <span className="tag gold">Brain</span>
                </div>
              </div>
            </div>
          </section>

          <section className="card widget">
            <div className="widget-head">
              <FbIcon name="settings" size={14} />
              <span className="widget-title">Framework training</span>
              <span className="tag green" style={{ marginLeft: "auto" }}>
                Gereed
              </span>
            </div>
            <p className="widget-sub">HADES Neural instellingen</p>
            <div className="kv">
              <span>Neural mode</span>
              <span>Hybrid (Memory+Tools)</span>
            </div>
            <div className="kv">
              <span>Requirement</span>
              <span>&gt;= 8B parameters</span>
            </div>
            <div className="kv">
              <span>Dual memory</span>
              <span>ATME (VRAM+RAM)</span>
            </div>
            <div className="kv">
              <span>Domains</span>
              <span>Core, Tools, Agents, Safety</span>
            </div>
          </section>

          <section className="card widget">
            <div className="widget-head">
              <FbIcon name="folder" size={14} />
              <span className="widget-title">Artifacts</span>
            </div>
            <p className="widget-sub">Output en gegenereerde bestanden</p>
            <div className="artifact">
              <FbIcon name="folder" size={14} />
              <div className="artifact-body">
                <div className="artifact-name">Adapter output</div>
                <div className="artifact-path">./outputs/hades-lora-8b</div>
              </div>
              <span className="tag gold">LoRA</span>
            </div>
            <div className="artifact">
              <FbIcon name="file" size={14} />
              <div className="artifact-body">
                <div className="artifact-name">Tokenizer</div>
                <div className="artifact-path">Gebaseerd op base model</div>
              </div>
              <span className="tag">Kopie</span>
            </div>
            <div className="artifact">
              <FbIcon name="file" size={14} />
              <div className="artifact-body">
                <div className="artifact-name">Tokenizer metadata</div>
                <div className="artifact-path">tokenizer_config.json</div>
              </div>
              <span className="tag">JSON</span>
            </div>
            <div className="warn-box">
              <FbIcon name="bolt" size={13} />
              <span>GGUF merge valt buiten de huidige scope (aparte tool).</span>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}

export function TrainingOverzichtInspector() {
  return (
    <>
      <p className="quote">
        “Sovereign AI. Local power.
        <br />
        Infinite possibilities.”
      </p>
      <div style={{ marginBottom: 10 }}>
        <span className="badge-outline">ONTWERPVOORBEELD</span>
      </div>
      <section className="insp-section">
        <div className="insp-head">
          <h3 className="insp-title">Hardware &amp; ATME</h3>
          <button className="btn btn-sm btn-ghost" type="button" data-toast="Hardware details (demo)">
            Details
          </button>
        </div>
        <div className="insp-card">
          <div className="hw-row">
            <div className="hw-top">
              <span className="k">GPU</span>
              <span className="v">NVIDIA RTX 4090</span>
            </div>
          </div>
          <div className="hw-row">
            <div className="hw-top">
              <span className="k">VRAM</span>
              <span className="v">18.4 / 24 GB</span>
            </div>
            <div className="bar-row">
              <div className="bar">
                <span style={{ width: "77%" }} />
              </div>
              <span className="bar-pct">77%</span>
            </div>
          </div>
          <div className="hw-row">
            <div className="hw-top">
              <span className="k">RAM</span>
              <span className="v">32.1 / 64 GB</span>
            </div>
            <div className="bar-row">
              <div className="bar">
                <span style={{ width: "50%" }} />
              </div>
              <span className="bar-pct">50%</span>
            </div>
          </div>
          <div className="hw-row">
            <div className="hw-top">
              <span className="k">Planner</span>
              <span className="v">
                ATME v2.1 <span className="tag green">Actief</span>
              </span>
            </div>
          </div>
          <div className="hw-row">
            <div className="hw-top">
              <span className="k">Benchmark</span>
              <span className="v">
                Laatste run: 14 nov 2024 <span className="tag green">9.4 / 10</span>
              </span>
            </div>
          </div>
        </div>
      </section>

      <section className="insp-section">
        <h3 className="insp-title">Training stack</h3>
        <p className="insp-sub">Controleer de geïnstalleerde packages.</p>
        <div className="insp-card">
          {[
            ["PyTorch", "2.2.1", true],
            ["Transformers", "4.46.0", true],
            ["PEFT", "0.11.1", true],
            ["Accelerate", "1.0.1", true],
          ].map(([name, ver]) => (
            <div key={String(name)} className="stack-row">
              <span className="stack-name">{name}</span>
              <span className="stack-ver">{ver}</span>
              <span className="ok-dot">
                <FbIcon name="check" size={8} />
              </span>
              <span className="tag green">OK</span>
            </div>
          ))}
          <div className="stack-row">
            <span className="stack-name">BitsAndBytes</span>
            <span className="stack-ver">0.43.1</span>
            <span className="tag warn">Optioneel</span>
          </div>
        </div>
      </section>

      <section className="insp-section">
        <h3 className="insp-title">Policies</h3>
        <p className="insp-sub">Configuratie en permissies voor training.</p>
        <div className="insp-card">
          <div className="policy-row">
            <FbIcon name="folder" size={14} />
            <span className="policy-name">File read</span>
            <span className="tag green">Toegestaan</span>
          </div>
          <div className="policy-row">
            <FbIcon name="globe" size={14} />
            <span className="policy-name">Network</span>
            <span className="tag warn">Beperkt (HF only)</span>
          </div>
          <div className="policy-row">
            <FbIcon name="terminal" size={14} />
            <span className="policy-name">Subprocess</span>
            <span className="tag green">Toegestaan</span>
          </div>
          <button className="btn btn-sm btn-outline btn-block" type="button" data-toast="Beleid beheren (demo)">
            <FbIcon name="shield" size={14} />
            Beleid beheren
          </button>
        </div>
      </section>

      <section className="insp-section">
        <h3 className="insp-title">Run details</h3>
        <p className="insp-sub">Huidige run informatie.</p>
        <div className="insp-card">
          <div className="detail-row">
            <span className="k">Status</span>
            <span className="v green">● Actief</span>
          </div>
          <div className="detail-row">
            <span className="k">Strategie</span>
            <span className="v">ATME (Adaptive)</span>
          </div>
          <div className="detail-row">
            <span className="k">Host → GPU</span>
            <span className="v">DESKTOP-HADES → cuda:0</span>
          </div>
          <div className="detail-row">
            <span className="k">Starttijd</span>
            <span className="v">14 nov 2024, 14:22</span>
          </div>
          <div className="detail-row">
            <span className="k">Uptime</span>
            <span className="v">0u 28m 16s</span>
          </div>
          <div className="detail-row">
            <span className="k">Job log</span>
            <span className="v" style={{ fontFamily: "var(--mono)", fontSize: 10 }}>
              ./logs/run-20241114-1422.log
            </span>
          </div>
        </div>
      </section>
    </>
  );
}
