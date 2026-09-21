"use client";

import { useState, type ReactNode } from "react";
import { FbIcon } from "../../icons";
import {
  DATASET_ACTIVITY,
  DATASET_DETAIL_TABS,
  DATASET_PIPELINE,
  DATASET_SAMPLE_ROWS,
  DATASET_SCHEMA_FIELDS,
  DATASET_SOURCES,
  DATASET_STATS,
  DATASET_STORAGE,
  mockDatasets,
  type DatasetDetailTab,
  type DatasetStatus,
} from "../../mocks/model-training";

function statusClass(status: DatasetStatus) {
  if (status === "Gereed") return "green";
  if (status === "Verwerken") return "cyan";
  return "gold";
}

export function TrainingTabDatasets({ tabs }: { tabs?: ReactNode }) {
  const [selectedId, setSelectedId] = useState("ds-chat");
  const [detailTab, setDetailTab] = useState<DatasetDetailTab>("Overzicht");
  const selected = mockDatasets.find((d) => d.id === selectedId) ?? mockDatasets[0]!;

  return (
    <div className="training-datasets">
      <div className="page-head">
        <div>
          <h1 className="page-title">Datasets</h1>
          <p className="page-sub">Beheer trainingsdatasets voor je modellen en het HADES framework.</p>
        </div>
        <div className="page-actions">
          <button className="btn btn-outline" type="button" data-toast="Dataset importeren (demo)">
            <FbIcon name="upload" size={14} />
            Dataset importeren
          </button>
          <button className="btn btn-gold" type="button" data-toast="Nieuwe dataset (demo)">
            <FbIcon name="plus" size={14} />
            Nieuwe dataset
          </button>
        </div>
      </div>

      {tabs}

      <div className="training-stat-row training-stat-row-6">
        {DATASET_STATS.map((stat) => (
          <div key={stat.label} className="card training-stat">
            <span className="training-stat-label">{stat.label}</span>
            <strong className={`training-stat-value ${stat.tone}`}>{stat.value}</strong>
            <span className="training-stat-hint">{stat.hint}</span>
          </div>
        ))}
      </div>

      <div className="training-ds-grid">
        <section className="card card-pad training-table-card">
          <div className="training-section-head">
            <div>
              <h2 className="section-title">Dataset Library</h2>
              <p className="section-sub">Selecteer een dataset om details te bekijken.</p>
            </div>
          </div>
          <div className="training-table-wrap">
            <table className="training-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Domain</th>
                  <th>Source</th>
                  <th>Split</th>
                  <th>Size</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {mockDatasets.map((ds) => (
                  <tr
                    key={ds.id}
                    className={ds.id === selectedId ? "selected" : undefined}
                    onClick={() => setSelectedId(ds.id)}
                  >
                    <td>
                      <strong>{ds.name}</strong>
                    </td>
                    <td>{ds.domain}</td>
                    <td>{ds.source}</td>
                    <td className="mono">{ds.split}</td>
                    <td>{ds.size}</td>
                    <td>
                      <span className={`tag ${statusClass(ds.status)}`}>{ds.status}</span>
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn btn-sm btn-outline"
                        data-toast={`Open ${ds.name}`}
                        onClick={(e) => e.stopPropagation()}
                      >
                        Open
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <aside className="card card-pad training-ds-details">
          <h2 className="section-title">Dataset Details</h2>
          <p className="section-sub">{selected.name}</p>
          <nav className="training-subtabs" aria-label="Dataset detail weergaven">
            {DATASET_DETAIL_TABS.map((tab) => (
              <button
                key={tab}
                type="button"
                className={`training-subtab${detailTab === tab ? " active" : ""}`}
                onClick={() => setDetailTab(tab)}
              >
                {tab}
              </button>
            ))}
          </nav>

          {detailTab === "Overzicht" ? (
            <div className="training-ds-panel">
              <p className="training-ds-desc">{selected.description}</p>
              <div className="kv">
                <span>Voorbeelden</span>
                <span>{selected.examples}</span>
              </div>
              <div className="kv">
                <span>Formaat</span>
                <span>{selected.format}</span>
              </div>
              <div className="kv">
                <span>Laatst bijgewerkt</span>
                <span>{selected.updated}</span>
              </div>
              <div className="kv">
                <span>Split</span>
                <span className="mono">{selected.split}</span>
              </div>
              <div className="training-quality">
                <div className="training-quality-top">
                  <span>Kwaliteitsscore</span>
                  <strong className="gold">
                    {selected.quality}
                    <small>/100</small>
                  </strong>
                </div>
                <div className="bar">
                  <span style={{ width: `${selected.quality}%` }} />
                </div>
              </div>
            </div>
          ) : null}

          {detailTab === "Schema" ? (
            <div className="training-ds-panel">
              <div className="training-table-wrap">
                <table className="training-table compact">
                  <thead>
                    <tr>
                      <th>Field</th>
                      <th>Type</th>
                      <th>Required</th>
                    </tr>
                  </thead>
                  <tbody>
                    {DATASET_SCHEMA_FIELDS.map((field) => (
                      <tr key={field.name}>
                        <td className="mono">{field.name}</td>
                        <td>{field.type}</td>
                        <td>{field.required ? "Ja" : "Nee"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : null}

          {detailTab === "Voorbeeld" ? (
            <div className="training-ds-panel training-sample">
              {DATASET_SAMPLE_ROWS.map((row, i) => (
                <div key={`${row.role}-${i}`} className="training-sample-row">
                  <span className={`tag${row.role === "assistant" ? " gold" : ""}`}>{row.role}</span>
                  <p>{row.content}</p>
                </div>
              ))}
            </div>
          ) : null}

          {detailTab === "Statistieken" ? (
            <div className="training-ds-panel">
              <div className="kv">
                <span>Tokens (est.)</span>
                <span>48.2M</span>
              </div>
              <div className="kv">
                <span>Gem. lengte</span>
                <span>312 tokens</span>
              </div>
              <div className="kv">
                <span>Duplicaten</span>
                <span>1.8%</span>
              </div>
              <div className="kv">
                <span>Taal NL / EN</span>
                <span>62% / 38%</span>
              </div>
              <div className="training-quality">
                <div className="training-quality-top">
                  <span>Coverage score</span>
                  <strong>{selected.quality}%</strong>
                </div>
                <div className="bar">
                  <span style={{ width: `${selected.quality}%` }} />
                </div>
              </div>
            </div>
          ) : null}
        </aside>
      </div>

      <div className="training-bottom-3">
        <section className="card card-pad">
          <h2 className="section-title">Preprocessing Pipeline</h2>
          <p className="section-sub">Stappen voor de geselecteerde dataset.</p>
          <div className="training-pipeline">
            {DATASET_PIPELINE.map((step) => (
              <div key={step.step} className={`training-pipe-step ${step.state}`}>
                <span className="training-pipe-dot" />
                <div>
                  <strong>{step.step}</strong>
                  <div className="muted">{step.detail}</div>
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="card card-pad">
          <h2 className="section-title">Dataset Sources</h2>
          <p className="section-sub">Actieve bronnen in de bibliotheek.</p>
          {DATASET_SOURCES.map((src) => (
            <div key={src.path} className="pipe-item">
              <div className="pipe-ico">
                <FbIcon name="database" size={14} />
              </div>
              <div className="pipe-body">
                <div className="pipe-name">{src.name}</div>
                <div className="pipe-path">{src.path}</div>
                <div className="pipe-meta">
                  <span className="pipe-count">{src.count} voorbeelden</span>
                  <span className={`tag${src.tag === "Brain" ? " gold" : ""}`}>{src.tag}</span>
                </div>
              </div>
            </div>
          ))}
        </section>

        <section className="card card-pad">
          <h2 className="section-title">Recente activiteit</h2>
          <p className="section-sub">Laatste dataset gebeurtenissen.</p>
          <div className="training-activity">
            {DATASET_ACTIVITY.map((item) => (
              <div key={item.title} className="training-activity-row">
                <span className={`training-activity-dot ${item.tone}`} />
                <div className="grow">
                  <strong>{item.title}</strong>
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

export function TrainingDatasetsInspector() {
  return (
    <>
      <p className="quote">
        “Data shapes intelligence.
        <br />
        Curate with intent.”
      </p>
      <section className="insp-section">
        <h3 className="insp-title">HADES Core</h3>
        <div className="insp-card">
          <div className="detail-row">
            <span className="k">Dataset Brain</span>
            <span className="v green">● Online</span>
          </div>
          <div className="detail-row">
            <span className="k">Indexed sets</span>
            <span className="v">24</span>
          </div>
          <div className="detail-row">
            <span className="k">Evidence links</span>
            <span className="v">1.284</span>
          </div>
          <div className="detail-row">
            <span className="k">Sync policy</span>
            <span className="v">HF allowlist</span>
          </div>
        </div>
      </section>
      <section className="insp-section">
        <h3 className="insp-title">Storage breakdown</h3>
        <div className="insp-card">
          {DATASET_STORAGE.map((row) => (
            <div key={row.label} className="hw-row">
              <div className="hw-top">
                <span className="k">{row.label}</span>
                <span className="v">{row.value}</span>
              </div>
              <div className="bar-row">
                <div className="bar">
                  <span style={{ width: `${row.pct}%` }} />
                </div>
                <span className="bar-pct">{row.pct}%</span>
              </div>
            </div>
          ))}
        </div>
      </section>
      <section className="insp-section">
        <h3 className="insp-title">Snelle acties</h3>
        <div className="insp-card training-insp-actions">
          <button className="btn btn-sm btn-outline btn-block" type="button" data-toast="Sync HF (demo)">
            <FbIcon name="refresh" size={13} />
            Sync Hugging Face
          </button>
          <button className="btn btn-sm btn-outline btn-block" type="button" data-toast="Validate all (demo)">
            <FbIcon name="checkcircle" size={13} />
            Valideer bibliotheek
          </button>
          <button className="btn btn-sm btn-gold btn-block" type="button" data-toast="Import wizard (demo)">
            <FbIcon name="plus" size={13} />
            Dataset toevoegen
          </button>
        </div>
      </section>
    </>
  );
}
