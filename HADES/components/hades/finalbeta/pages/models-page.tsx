/** FINALBETA Models — pixel mock (content area). */
"use client";

import { useMemo, useState } from "react";
import { donutSegments } from "../hooks/dashboard-live-utils";
import { FbIcon } from "../icons";
import {
  MODELS_ACTIVE_RUNTIME,
  MODELS_BENCHMARK,
  MODELS_DOWNLOAD_QUEUE,
  MODELS_HERO,
  MODELS_KPIS,
  MODELS_PROFILES,
  MODELS_PROVIDERS,
  MODELS_QUICK_ACTIONS,
  MODELS_REGISTRY,
  MODELS_REGISTRY_FILTERS,
  MODELS_ROUTING_TOGGLES,
  MODELS_VRAM,
  modelStatusLabel,
} from "../mocks/models-pixel";
import { FinalBetaShell } from "../shell/finalbeta-shell";
import type { FinalBetaNavigate } from "../types";

type Props = { onNavigate: FinalBetaNavigate };


export function ModelsPage({ onNavigate }: Props) {
  const [query, setQuery] = useState("");
  const [providerFilter, setProviderFilter] = useState(MODELS_REGISTRY_FILTERS.providers[0]!);
  const [typeFilter, setTypeFilter] = useState(MODELS_REGISTRY_FILTERS.types[0]!);
  const [capFilter, setCapFilter] = useState(MODELS_REGISTRY_FILTERS.capabilities[0]!);
  const [statusFilter, setStatusFilter] = useState(MODELS_REGISTRY_FILTERS.statuses[0]!);
  const [toggles, setToggles] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(MODELS_ROUTING_TOGGLES.map((t) => [t.id, t.defaultOn])),
  );

  const filteredModels = useMemo(() => {
    const q = query.trim().toLowerCase();
    return MODELS_REGISTRY.filter((row) => {
      if (q && !row.name.toLowerCase().includes(q) && !row.provider.toLowerCase().includes(q)) return false;
      if (providerFilter !== "Alle providers" && row.provider !== providerFilter && !row.provider.startsWith(providerFilter))
        return false;
      if (statusFilter !== "Alle statussen" && modelStatusLabel(row.status) !== statusFilter) return false;
      if (capFilter !== "Alle capabilities" && !row.capabilities.some((c) => c === capFilter)) return false;
      if (typeFilter !== "Alle types") {
        const hay = `${row.name} ${row.capabilities.join(" ")}`.toLowerCase();
        if (!hay.includes(typeFilter.toLowerCase())) return false;
      }
      return true;
    });
  }, [query, providerFilter, typeFilter, capFilter, statusFilter]);

  const vramDonut = useMemo(
    () =>
      donutSegments(
        MODELS_VRAM.slices.map((slice) => ({
          label: slice.label,
          count: slice.gb,
          color: slice.color,
        })),
      ),
    [],
  );

  const body = (
    <div className="mdl-page">
      <header className="mdl-hero">
        <div className="mdl-hero-grid">
          <div>
            <h1>{MODELS_HERO.title}</h1>
            <p className="mdl-hero-sub">{MODELS_HERO.subtitle}</p>
          </div>
          <p className="mdl-hero-quote">“{MODELS_HERO.quote}”</p>
          <div className="mdl-hero-pillars" aria-hidden="true">
            {MODELS_HERO.pillars.map((line) => (
              <span key={line}>{line}</span>
            ))}
          </div>
        </div>
      </header>

      <div className="mdl-kpi-row">
        {MODELS_KPIS.map((kpi) => (
          <article key={kpi.id} className="mdl-kpi">
            <span className="mdl-kpi-ico">
              <FbIcon name={kpi.icon} size={15} />
            </span>
            <div className="mdl-kpi-body">
              <div className="mdl-kpi-label">{kpi.label}</div>
              <div className="mdl-kpi-value">{kpi.value}</div>
              <div className={`mdl-kpi-hint ${kpi.hintTone}`}>{kpi.hint}</div>
              {kpi.progress != null ? (
                <div className="mdl-kpi-bar" aria-hidden="true">
                  <i style={{ width: `${kpi.progress}%` }} />
                </div>
              ) : null}
            </div>
          </article>
        ))}
      </div>

      <div className="mdl-actions">
        {MODELS_QUICK_ACTIONS.map((action) => (
          <button key={action.id} type="button" className="mdl-action" data-toast={action.toast}>
            <span className="mdl-action-ico">
              <FbIcon name={action.icon} size={16} />
            </span>
            <span className="mdl-action-title">{action.title}</span>
            <span className="mdl-action-sub">{action.subtitle}</span>
          </button>
        ))}
      </div>

      <section className="mdl-registry" aria-label="Model registry">
        <div className="mdl-registry-head">
          <h2 className="mdl-registry-title">↓ MODEL REGISTRY</h2>
        </div>
        <div className="mdl-registry-filters">
          <label className="mdl-search">
            <FbIcon name="search" size={12} />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Zoek modellen..."
              aria-label="Zoek modellen"
            />
          </label>
          <select
            className="mdl-filter"
            value={providerFilter}
            onChange={(e) => setProviderFilter(e.target.value)}
            aria-label="Filter providers"
          >
            {MODELS_REGISTRY_FILTERS.providers.map((opt) => (
              <option key={opt} value={opt}>{opt}</option>
            ))}
          </select>
          <select className="mdl-filter" value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)} aria-label="Filter types">
            {MODELS_REGISTRY_FILTERS.types.map((opt) => (
              <option key={opt} value={opt}>{opt}</option>
            ))}
          </select>
          <select className="mdl-filter" value={capFilter} onChange={(e) => setCapFilter(e.target.value)} aria-label="Filter capabilities">
            {MODELS_REGISTRY_FILTERS.capabilities.map((opt) => (
              <option key={opt} value={opt}>{opt}</option>
            ))}
          </select>
          <select className="mdl-filter" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} aria-label="Filter statussen">
            {MODELS_REGISTRY_FILTERS.statuses.map((opt) => (
              <option key={opt} value={opt}>{opt}</option>
            ))}
          </select>
        </div>
        <div className="mdl-table-wrap">
          <table className="mdl-table">
            <thead>
              <tr>
                <th>Naam</th>
                <th>Provider</th>
                <th>Grootte</th>
                <th>Quantisatie</th>
                <th>Status</th>
                <th>Capabilities</th>
                <th>Laatst Gebruikt</th>
                <th aria-label="Acties" />
              </tr>
            </thead>
            <tbody>
              {filteredModels.map((row) => (
                <tr key={row.id}>
                  <td>
                    <div className="mdl-name-cell">
                      <FbIcon name={row.icon} size={14} className="mdl-row-ico" />
                      <strong>{row.name}</strong>
                    </div>
                  </td>
                  <td>
                    <div className="mdl-provider-cell">
                      <FbIcon name={row.providerIcon} size={12} />
                      <span>{row.provider}</span>
                    </div>
                  </td>
                  <td>{row.size}</td>
                  <td>{row.quant}</td>
                  <td>
                    <span className={`mdl-status ${row.status}`}>
                      {row.status === "geladen" || row.status === "beschikbaar" ? (
                        <FbIcon name="checkcircle" size={11} />
                      ) : (
                        <span className="mdl-status-dot" />
                      )}
                      {modelStatusLabel(row.status)}
                    </span>
                  </td>
                  <td>
                    <div className="mdl-pills">
                      {row.capabilities.map((cap) => (
                        <span key={cap} className="mdl-pill">{cap}</span>
                      ))}
                    </div>
                  </td>
                  <td>{row.lastUsed}</td>
                  <td>
                    <button type="button" className="mdl-row-menu" data-toast={`Acties — ${row.name}`} aria-label="Meer acties">
                      <FbIcon name="more" size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <div className="mdl-widgets">
        <section className="mdl-widget">
          <div className="mdl-widget-head">
            <div>
              <h3>Download &amp; Import Queue</h3>
              <p>{MODELS_DOWNLOAD_QUEUE.length} items</p>
            </div>
            <button type="button" className="mdl-link" data-toast="Wachtrij gepauzeerd">
              Alles pauzeren
            </button>
          </div>
          {MODELS_DOWNLOAD_QUEUE.map((item) => (
            <div key={item.id} className="mdl-queue-item">
              <div className="mdl-queue-top">
                <strong>{item.name}</strong>
                <span>{item.source}</span>
              </div>
              {item.state === "done" ? (
                <span className="mdl-done">Gereed</span>
              ) : (
                <>
                  <div className="mdl-progress" aria-hidden="true">
                    <i style={{ width: `${item.progress ?? 0}%` }} />
                  </div>
                  <div className="mdl-queue-meta">
                    <span>{item.progress}%</span>
                    <span>{item.eta}</span>
                  </div>
                </>
              )}
            </div>
          ))}
        </section>

        <section className="mdl-widget">
          <div className="mdl-widget-head">
            <div>
              <h3>Benchmark Snapshot</h3>
            </div>
          </div>
          <div className="mdl-bench-select">
            <select defaultValue={MODELS_BENCHMARK.modelId} aria-label="Benchmark model">
              <option value={MODELS_BENCHMARK.modelId}>{MODELS_BENCHMARK.modelLabel}</option>
            </select>
            <button type="button" className="mdl-bench-run" data-toast="Benchmark gestart">
              Uitvoeren
            </button>
          </div>
          {MODELS_BENCHMARK.metrics.map((metric) => (
            <div key={metric.id} className="mdl-bench-metric">
              <span>{metric.label}</span>
              <b>{metric.score.toFixed(1)}</b>
              <div className="mdl-bench-bar" aria-hidden="true">
                <i style={{ width: `${metric.score}%` }} />
              </div>
            </div>
          ))}
        </section>

        <section className="mdl-widget">
          <div className="mdl-widget-head">
            <div>
              <h3>VRAM / Memory Allocatie</h3>
            </div>
          </div>
          <div className="mdl-vram-wrap">
            <div className="mdl-donut">
              <svg viewBox="0 0 42 42" aria-hidden="true">
                <circle cx="21" cy="21" r="14" fill="none" stroke="#223544" strokeWidth="5" />
                {vramDonut.map((seg, index) => (
                  <circle
                    key={`${seg.color}-${index}`}
                    cx="21"
                    cy="21"
                    r="14"
                    fill="none"
                    stroke={seg.color}
                    strokeWidth="5"
                    strokeDasharray={seg.dash}
                    strokeDashoffset={seg.offset}
                    transform="rotate(-90 21 21)"
                  />
                ))}
              </svg>
              <div className="mdl-donut-center">
                <strong>{MODELS_VRAM.usedPct}%</strong>
                <span>VRAM</span>
              </div>
            </div>
            <ul className="mdl-vram-legend">
              {MODELS_VRAM.slices.map((slice) => (
                <li key={slice.label}>
                  <i style={{ background: slice.color }} />
                  <span>{slice.label}</span>
                  <b>{slice.gb} GB</b>
                </li>
              ))}
            </ul>
          </div>
          <div className="mdl-vram-foot">
            <span>Totaal {MODELS_VRAM.totalGb.toFixed(1)} GB</span>
            <button type="button" className="mdl-opt-btn" data-toast="Geheugen optimaliseren">
              <FbIcon name="settings" size={11} />
              Geheugen optimaliseren
            </button>
          </div>
        </section>

        <section className="mdl-widget">
          <div className="mdl-widget-head">
            <div>
              <h3>Opgeslagen Profielen</h3>
            </div>
            <button type="button" className="mdl-link" data-toast="Nieuw profiel">
              Nieuw +
            </button>
          </div>
          {MODELS_PROFILES.map((profile) => (
            <div key={profile.id} className="mdl-profile">
              <span className="mdl-profile-ico">
                <FbIcon name={profile.icon} size={14} />
              </span>
              <div className="mdl-profile-copy">
                <strong>{profile.name}</strong>
                <span>{profile.detail}</span>
              </div>
              <span className="mdl-profile-count">{profile.count}</span>
            </div>
          ))}
        </section>
      </div>
    </div>
  );

  const inspector = (
    <>
      <section className="insp-section">
        <h3 className="insp-title">Actieve Runtime &amp; Routing</h3>
        <div className="insp-card">
          <div className="mdl-insp-runtime-card">
            <span className="mdl-insp-runtime-ico">
              <FbIcon name="brain" size={22} />
            </span>
            <div className="mdl-insp-runtime-copy">
              <strong>{MODELS_ACTIVE_RUNTIME.name}</strong>
              <span>
                {MODELS_ACTIVE_RUNTIME.provider} • {MODELS_ACTIVE_RUNTIME.quant}
              </span>
              <span className="mdl-badge-active">Actief</span>
            </div>
          </div>
          {MODELS_ROUTING_TOGGLES.map((toggle) => (
            <div key={toggle.id} className="mdl-toggle-row">
              <div className="mdl-toggle-copy">
                <strong>{toggle.label}</strong>
                <span>{toggle.hint}</span>
              </div>
              <button
                type="button"
                className={`switch${toggles[toggle.id] ? " on" : ""}`}
                aria-pressed={toggles[toggle.id]}
                onClick={() => setToggles((prev) => ({ ...prev, [toggle.id]: !prev[toggle.id] }))}
                data-toast={toggle.label}
              />
            </div>
          ))}
          <div className="mdl-context">
            <div className="mdl-context-top">
              <span>Context geheugen</span>
              <b>{MODELS_ACTIVE_RUNTIME.contextTokens} tokens</b>
            </div>
            <input
              type="range"
              className="mdl-range"
              min={8}
              max={128}
              defaultValue={32}
              aria-label="Context geheugen"
              data-toast="Context geheugen"
            />
          </div>
        </div>
      </section>
      <section className="insp-section">
        <h3 className="insp-title">Provider Status</h3>
        <div className="insp-card">
          {MODELS_PROVIDERS.map((provider) => (
            <div key={provider.id} className="mdl-provider-row">
              <div className="mdl-provider-top">
                <div>
                  <strong>{provider.name}</strong>
                  <span> · {provider.kind}</span>
                </div>
                <span className={`mdl-provider-status ${provider.status}`}>
                  <span className="mdl-status-dot" />
                  {provider.status === "degraded" ? "Degraded" : "Online"}
                </span>
              </div>
              <div className="mdl-provider-bar" aria-hidden="true">
                <i className={provider.status} style={{ width: `${provider.healthPct}%` }} />
              </div>
              <div className="mdl-provider-meta">
                <span>{provider.loaded}/{provider.total}</span>
                <span>{provider.healthPct}%</span>
              </div>
            </div>
          ))}
        </div>
      </section>
      <section className="insp-section">
        <h3 className="insp-title">Snelkoppeling</h3>
        <div className="insp-card" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <button className="btn btn-sm btn-outline btn-block" type="button" onClick={() => onNavigate("model-training")}>
            Model Training
          </button>
          <button className="btn btn-sm btn-gold btn-block" type="button" onClick={() => onNavigate("settings-llm-studio")}>
            LLM Studio
          </button>
        </div>
      </section>
    </>
  );

  return (
    <FinalBetaShell
      page="models"
      body={body}
      inspector={inspector}
      onNavigate={onNavigate}
      appClassName="mdl-app"
      mainClassName="mdl-main"
    />
  );
}
