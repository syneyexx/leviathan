"use client";

import type { ReactNode } from "react";
import { FbIcon } from "../../icons";
import {
  FRAMEWORK_ACTIVITY,
  FRAMEWORK_NODES,
  FRAMEWORK_OBJECTIVES,
  FRAMEWORK_SIGNALS,
  FRAMEWORK_STATUS,
} from "../../mocks/model-training";

export function TrainingTabFramework({ tabs }: { tabs?: ReactNode }) {
  return (
    <div className="training-framework">
      <div className="page-head">
        <div>
          <h1 className="page-title">Framework</h1>
          <p className="page-sub">
            Train het HADES neural framework: routing, memory, tools en safety op maat van jouw lokale omgeving.
          </p>
        </div>
        <div className="page-actions">
          <button className="btn btn-outline" type="button" data-toast="Eval batch (demo)">
            <FbIcon name="flask" size={14} />
            Eval batch
          </button>
          <button className="btn btn-gold" type="button" data-toast="Start framework training (demo)">
            <FbIcon name="play" size={14} />
            Start framework training
          </button>
        </div>
      </div>

      {tabs}

      <div className="training-stat-row training-stat-row-6">
        {FRAMEWORK_STATUS.map((stat) => (
          <div key={stat.label} className="card training-stat">
            <span className="training-stat-label">{stat.label}</span>
            <strong className={`training-stat-value ${stat.tone}`}>{stat.value}</strong>
            <span className="training-stat-hint">{stat.hint}</span>
          </div>
        ))}
      </div>

      <div className="training-fw-grid">
        <section className="card card-pad">
          <h2 className="section-title">Framework Training Matrix</h2>
          <p className="section-sub">Doelprofiel en trainingsparameters voor Neural Core.</p>
          <div className="form-grid training-form-tight">
            <label className="field">
              <span className="field-label">Focus</span>
              <select className="control" defaultValue="Chat-primary">
                <option>Chat-primary</option>
                <option>Research-heavy</option>
                <option>Coding</option>
                <option>Balanced</option>
              </select>
            </label>
            <label className="field">
              <span className="field-label">Safety</span>
              <select className="control" defaultValue="Strict local">
                <option>Strict local</option>
                <option>Balanced</option>
                <option>Permissive lab</option>
              </select>
            </label>
            <label className="field">
              <span className="field-label">Neural mode</span>
              <select className="control" defaultValue="Hybrid (Memory+Tools)">
                <option>Hybrid (Memory+Tools)</option>
                <option>Memory-first</option>
                <option>Tools-first</option>
              </select>
            </label>
            <label className="field">
              <span className="field-label">Dual memory</span>
              <select className="control" defaultValue="ATME (VRAM+RAM)">
                <option>ATME (VRAM+RAM)</option>
                <option>VRAM only</option>
                <option>RAM spill</option>
              </select>
            </label>
            <label className="field">
              <span className="field-label">Domains</span>
              <select className="control" defaultValue="Core, Tools, Agents, Safety">
                <option>Core, Tools, Agents, Safety</option>
                <option>Core + Research</option>
                <option>Full mesh</option>
              </select>
            </label>
            <label className="field">
              <span className="field-label">Eval cadence</span>
              <select className="control" defaultValue="Elke 500 stappen">
                <option>Elke 500 stappen</option>
                <option>Elke 250 stappen</option>
                <option>Einde epoch</option>
              </select>
            </label>
          </div>
          <div className="config-actions">
            <button className="btn btn-outline-blue" type="button" data-toast="Dry-run matrix (demo)">
              <FbIcon name="search" size={14} />
              Dry-run matrix
            </button>
            <button className="btn btn-gold" type="button" data-toast="Matrix opgeslagen (demo)">
              <FbIcon name="save" size={14} />
              Matrix opslaan
            </button>
          </div>
        </section>

        <aside className="card card-pad training-neural-card">
          <h2 className="section-title">Neural Architecture</h2>
          <p className="section-sub">HADES Core met satelliet-domeinen.</p>
          <div className="training-neural" aria-hidden="true">
            <svg className="training-neural-svg" viewBox="0 0 320 260">
              <defs>
                <linearGradient id="mtHexFill" x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0%" stopColor="#0d2a3d" />
                  <stop offset="100%" stopColor="#12364a" />
                </linearGradient>
              </defs>
              {FRAMEWORK_NODES.map((node) => {
                const x = (node.x / 100) * 320;
                const y = (node.y / 100) * 260;
                return (
                  <line
                    key={`l-${node.id}`}
                    x1="160"
                    y1="130"
                    x2={x}
                    y2={y}
                    stroke="rgba(62,199,232,0.35)"
                    strokeWidth="1.2"
                  />
                );
              })}
              <polygon
                points="160,78 205,104 205,156 160,182 115,156 115,104"
                fill="url(#mtHexFill)"
                stroke="#f0b429"
                strokeWidth="1.8"
              />
              <text x="160" y="126" textAnchor="middle" fill="#f0b429" fontSize="11" fontWeight="650">
                HADES
              </text>
              <text x="160" y="142" textAnchor="middle" fill="#8ea3af" fontSize="9">
                CORE
              </text>
              {FRAMEWORK_NODES.map((node) => {
                const x = (node.x / 100) * 320;
                const y = (node.y / 100) * 260;
                return (
                  <g key={node.id}>
                    <circle cx={x} cy={y} r="18" fill="#0b1c28" stroke="#3ec7e8" strokeWidth="1.4" />
                    <text x={x} y={y + 3} textAnchor="middle" fill="#d7e6ef" fontSize="8" fontWeight="600">
                      {node.label}
                    </text>
                  </g>
                );
              })}
            </svg>
          </div>
        </aside>
      </div>

      <div className="training-bottom-3">
        <section className="card card-pad">
          <h2 className="section-title">Objectives</h2>
          <p className="section-sub">Voortgang op framework-doelen.</p>
          <div className="training-objectives">
            {FRAMEWORK_OBJECTIVES.map((obj) => (
              <div key={obj.label} className="training-obj-row">
                <div className="training-obj-top">
                  <span>{obj.label}</span>
                  <strong>{obj.pct}%</strong>
                </div>
                <div className="bar">
                  <span style={{ width: `${obj.pct}%` }} />
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="card card-pad">
          <h2 className="section-title">Evaluation Signals</h2>
          <p className="section-sub">Laatste meetwaarden uit eval batches.</p>
          <div className="training-signals">
            {FRAMEWORK_SIGNALS.map((sig) => (
              <div key={sig.signal} className="training-signal-row">
                <div>
                  <strong>{sig.signal}</strong>
                  <div className={`muted training-trend ${sig.tone}`}>{sig.trend}</div>
                </div>
                <span className={`training-signal-val ${sig.tone}`}>{sig.value}</span>
              </div>
            ))}
          </div>
        </section>

        <section className="card card-pad">
          <h2 className="section-title">Framework Activity</h2>
          <p className="section-sub">Recente Neural Core gebeurtenissen.</p>
          <div className="training-activity">
            {FRAMEWORK_ACTIVITY.map((item) => (
              <div key={item.title} className="training-activity-row">
                <span className="training-activity-dot cyan" />
                <div className="grow">
                  <strong>{item.title}</strong>
                  <div className="muted">{item.detail}</div>
                </div>
                <span className="muted">{item.ago}</span>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}

export function TrainingFrameworkInspector() {
  return (
    <>
      <p className="quote">
        “One brain.
        <br />
        Many capabilities.”
      </p>
      <section className="insp-section">
        <h3 className="insp-title">Neural Core</h3>
        <div className="insp-card">
          <div className="detail-row">
            <span className="k">Version</span>
            <span className="v">HADES Neural v3</span>
          </div>
          <div className="detail-row">
            <span className="k">Mesh</span>
            <span className="v">9 / 9 nodes</span>
          </div>
          <div className="detail-row">
            <span className="k">Requirement</span>
            <span className="v">&gt;= 8B params</span>
          </div>
          <div className="detail-row">
            <span className="k">Status</span>
            <span className="v green">● Healthy</span>
          </div>
        </div>
      </section>
      <section className="insp-section">
        <h3 className="insp-title">Brain Status</h3>
        <div className="insp-card">
          <div className="detail-row">
            <span className="k">Graph sync</span>
            <span className="tag green">OK</span>
          </div>
          <div className="detail-row">
            <span className="k">Self-model</span>
            <span className="v">Current</span>
          </div>
          <div className="detail-row">
            <span className="k">Immune</span>
            <span className="v green">Nominal</span>
          </div>
        </div>
      </section>
      <section className="insp-section">
        <h3 className="insp-title">Evidence Sync</h3>
        <div className="insp-card">
          <div className="detail-row">
            <span className="k">Vault → Brain</span>
            <span className="v">8m ago</span>
          </div>
          <div className="detail-row">
            <span className="k">Pending</span>
            <span className="v">14 items</span>
          </div>
          <div className="detail-row">
            <span className="k">Policy</span>
            <span className="v">Citation-aware</span>
          </div>
        </div>
      </section>
      <section className="insp-section">
        <h3 className="insp-title">Quick Actions</h3>
        <div className="insp-card training-insp-actions">
          <button className="btn btn-sm btn-outline btn-block" type="button" data-toast="Sync evidence (demo)">
            <FbIcon name="refresh" size={13} />
            Sync Evidence
          </button>
          <button className="btn btn-sm btn-outline btn-block" type="button" data-toast="Open brain graph (demo)">
            <FbIcon name="brain" size={13} />
            Brain graph
          </button>
          <button className="btn btn-sm btn-gold btn-block" type="button" data-toast="Start framework training (demo)">
            <FbIcon name="play" size={13} />
            Start framework training
          </button>
        </div>
      </section>
    </>
  );
}
