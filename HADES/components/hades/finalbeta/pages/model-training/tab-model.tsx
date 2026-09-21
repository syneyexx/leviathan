"use client";

import type { ReactNode } from "react";
import { FbIcon } from "../../icons";
import {
  MODEL_CAPABILITIES,
  MODEL_COMPAT,
  MODEL_PROFILES,
  MODEL_STATUS,
} from "../../mocks/model-training";

export function TrainingTabModel({ tabs }: { tabs?: ReactNode }) {
  return (
    <div className="training-model">
      <div className="page-head">
        <div>
          <h1 className="page-title">Model</h1>
          <p className="page-sub">
            Kies een basismodel en configureer fine-tuning setup voor lokale QLoRA / LoRA training.
          </p>
        </div>
        <div className="page-actions">
          <button className="btn btn-outline" type="button" data-toast="Model zoeken (demo)">
            <FbIcon name="search" size={14} />
            Model zoeken
          </button>
          <button className="btn btn-gold" type="button" data-toast="Preset toepassen (demo)">
            <FbIcon name="bolt" size={14} />
            Preset toepassen
          </button>
        </div>
      </div>

      {tabs}

      <div className="training-stat-row training-stat-row-5">
        {MODEL_STATUS.map((stat) => (
          <div key={stat.label} className="card training-stat">
            <span className="training-stat-label">{stat.label}</span>
            <strong className="training-stat-value gold">{stat.value}</strong>
            <span className="training-stat-hint">{stat.hint}</span>
          </div>
        ))}
      </div>

      <div className="training-model-grid">
        <section className="card card-pad">
          <h2 className="section-title">Model Configuration</h2>
          <p className="section-sub">Fine-tuning parameters voor de geselecteerde basis.</p>
          <div className="form-grid training-form-tight">
            <label className="field">
              <span className="field-label">Base model</span>
              <select className="control" defaultValue="Qwen/Qwen2.5-Coder-7B-Instruct">
                <option>Qwen/Qwen2.5-Coder-7B-Instruct</option>
                <option>meta-llama/Llama-3.1-8B-Instruct</option>
                <option>mistralai/Mistral-7B-Instruct-v0.3</option>
              </select>
            </label>
            <label className="field">
              <span className="field-label">Training mode</span>
              <select className="control" defaultValue="QLoRA (4-bit)">
                <option>QLoRA (4-bit)</option>
                <option>LoRA (16-bit)</option>
                <option>Full fine-tune</option>
              </select>
            </label>
            <label className="field">
              <span className="field-label">Quantization</span>
              <select className="control" defaultValue="Q4_K_M">
                <option>Q4_K_M</option>
                <option>Q5_K_M</option>
                <option>Q8_0</option>
              </select>
            </label>
            <label className="field">
              <span className="field-label">Context length</span>
              <select className="control" defaultValue="128K">
                <option>128K</option>
                <option>32K</option>
                <option>8K</option>
              </select>
            </label>
            <label className="field">
              <span className="field-label">Target modules</span>
              <select className="control" defaultValue="q_proj,v_proj,o_proj">
                <option>q_proj,v_proj,o_proj</option>
                <option>all-linear</option>
                <option>attn-only</option>
              </select>
            </label>
            <label className="field">
              <span className="field-label">LoRA r / alpha</span>
              <div className="lora-pair">
                <input className="control" defaultValue="64" />
                <input className="control" defaultValue="128" />
              </div>
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
              <span className="field-label">Max steps</span>
              <select className="control" defaultValue="8000">
                <option>8000</option>
                <option>5000</option>
                <option>12000</option>
              </select>
            </label>
          </div>
          <div className="config-actions">
            <button className="btn btn-outline-blue" type="button" data-toast="Validate config (demo)">
              <FbIcon name="checkcircle" size={14} />
              Config valideren
            </button>
            <button className="btn btn-gold" type="button" data-toast="Save model profile (demo)">
              <FbIcon name="save" size={14} />
              Profiel opslaan
            </button>
          </div>
        </section>

        <aside className="card card-pad training-model-details">
          <h2 className="section-title">Selected Model Details</h2>
          <p className="section-sub">Qwen2.5-Coder-7B-Instruct</p>
          <div className="kv">
            <span>Architectuur</span>
            <span>Transformer dense</span>
          </div>
          <div className="kv">
            <span>Parameters</span>
            <span>7.6B</span>
          </div>
          <div className="kv">
            <span>Tokenizer</span>
            <span>Qwen2 BPE</span>
          </div>
          <div className="kv">
            <span>License</span>
            <span>Apache-2.0</span>
          </div>
          <div className="kv">
            <span>Local path</span>
            <span className="mono">./models/qwen25-coder-7b</span>
          </div>
          <div className="kv">
            <span>Geschat VRAM (QLoRA)</span>
            <span>11.8 GB</span>
          </div>
          <div className="training-model-badge-row">
            <span className="tag gold">Coder</span>
            <span className="tag green">Lokaal</span>
            <span className="tag">Q4_K_M</span>
          </div>
        </aside>
      </div>

      <div className="training-bottom-3">
        <section className="card card-pad">
          <h2 className="section-title">Capability Comparison</h2>
          <p className="section-sub">Relatieve sterkte van het geselecteerde model.</p>
          <div className="training-cap-bars">
            {MODEL_CAPABILITIES.map((cap) => (
              <div key={cap.label} className="training-cap-row">
                <span>{cap.label}</span>
                <div className="bar">
                  <span style={{ width: `${cap.score}%` }} />
                </div>
                <strong>{cap.score}</strong>
              </div>
            ))}
          </div>
          <svg className="training-radar" viewBox="0 0 200 160" aria-hidden="true">
            <polygon
              points="100,18 168,55 148,128 52,128 32,55"
              fill="rgba(240,180,41,0.12)"
              stroke="#f0b429"
              strokeWidth="1.5"
            />
            <polygon
              points="100,28 155,58 140,118 60,118 45,58"
              fill="none"
              stroke="rgba(62,199,232,0.45)"
              strokeWidth="1"
              strokeDasharray="3 3"
            />
            <circle cx="100" cy="80" r="2.5" fill="#f0b429" />
          </svg>
        </section>

        <section className="card card-pad">
          <h2 className="section-title">Compatibility checklist</h2>
          <p className="section-sub">Runtime vereisten voor deze config.</p>
          <div className="training-compat">
            {MODEL_COMPAT.map((item) => (
              <div key={item.label} className={`training-compat-row ${item.ok ? "ok" : "warn"}`}>
                <FbIcon name={item.ok ? "checkcircle" : "bolt"} size={14} />
                <span>{item.label}</span>
                <span className={`tag ${item.ok ? "green" : "warn"}`}>{item.ok ? "OK" : "Optioneel"}</span>
              </div>
            ))}
          </div>
        </section>

        <section className="card card-pad">
          <h2 className="section-title">Model Profiles</h2>
          <p className="section-sub">Opgeslagen training presets.</p>
          <div className="training-profiles">
            {MODEL_PROFILES.map((profile) => (
              <button
                key={profile.id}
                type="button"
                className={`training-profile${profile.tag === "Actief" ? " active" : ""}`}
                data-toast={`Profile ${profile.name}`}
              >
                <strong>{profile.name}</strong>
                <span className="muted">{profile.desc}</span>
                <span className={`tag${profile.tag === "Actief" ? " gold" : ""}`}>{profile.tag}</span>
              </button>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}

export function TrainingModelInspector() {
  return (
    <>
      <p className="quote">
        “Own the weights.
        <br />
        Own the outcome.”
      </p>
      <section className="insp-section">
        <h3 className="insp-title">Model Runtime</h3>
        <div className="insp-card">
          <div className="detail-row">
            <span className="k">Status</span>
            <span className="v green">● Online</span>
          </div>
          <div className="detail-row">
            <span className="k">Backend</span>
            <span className="v">LM Studio + PEFT</span>
          </div>
          <div className="detail-row">
            <span className="k">Device</span>
            <span className="v">cuda:0</span>
          </div>
          <div className="detail-row">
            <span className="k">Loaded</span>
            <span className="v">Qwen2.5-Coder</span>
          </div>
        </div>
      </section>
      <section className="insp-section">
        <h3 className="insp-title">OmniRoute</h3>
        <div className="insp-card">
          <div className="detail-row">
            <span className="k">Routing</span>
            <span className="v">Coding-first</span>
          </div>
          <div className="detail-row">
            <span className="k">Fallback</span>
            <span className="v">Llama-3.1-8B</span>
          </div>
          <div className="detail-row">
            <span className="k">Catalog</span>
            <span className="v green">Synced</span>
          </div>
        </div>
      </section>
      <section className="insp-section">
        <h3 className="insp-title">Training presets</h3>
        <div className="insp-card">
          <div className="detail-row">
            <span className="k">Coder QLoRA</span>
            <span className="tag gold">Actief</span>
          </div>
          <div className="detail-row">
            <span className="k">Chat balanced</span>
            <span className="v">Preset</span>
          </div>
          <div className="detail-row">
            <span className="k">Research long-ctx</span>
            <span className="v">Preset</span>
          </div>
        </div>
      </section>
      <section className="insp-section">
        <h3 className="insp-title">Quick actions</h3>
        <div className="insp-card training-insp-actions">
          <button className="btn btn-sm btn-outline btn-block" type="button" data-toast="Inspect weights (demo)">
            <FbIcon name="search" size={13} />
            Weights inspecteren
          </button>
          <button className="btn btn-sm btn-outline btn-block" type="button" data-toast="Export GGUF (demo)">
            <FbIcon name="download" size={13} />
            Export GGUF
          </button>
          <button className="btn btn-sm btn-gold btn-block" type="button" data-toast="Start fine-tune (demo)">
            <FbIcon name="play" size={13} />
            Fine-tune starten
          </button>
        </div>
      </section>
    </>
  );
}
