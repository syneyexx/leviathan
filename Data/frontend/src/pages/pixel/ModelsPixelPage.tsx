import { useMemo, useState } from "react";
import { AppShell } from "../../layouts/AppShell";
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
} from "../../mocks/models-pixel";
import { useAppToast } from "../../state/useAppToast";
import { donutSegments, PxHero, PxIcon, PxKpi, PxSwitch } from "./pixel-shared";

export function ModelsPixelPage() {
  const toast = useAppToast();
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
          value: slice.gb,
          color: slice.color,
        })),
      ),
    [],
  );

  return (
    <AppShell
      activeMode="explore"
      modeLabel="LLM Studio"
      searchPlaceholder="Zoek modellen, providers..."
      systemItems={["SYSTEMS ONLINE", "MODELS", "VRAM 78%", "SYNC"]}
      layout="wide"
      pageClass="lv-app--pixel-llm"
    >
      <main className="lv-main lv-px-main">
        <div className="lv-px-split">
          <div className="lv-px-stack">
            <PxHero
              title={MODELS_HERO.title}
              subtitle={MODELS_HERO.subtitle}
              quote={MODELS_HERO.quote}
              pillars={MODELS_HERO.pillars}
            />

            <div className="lv-px-kpi-row">
              {MODELS_KPIS.map((kpi) => (
                <PxKpi
                  key={kpi.id}
                  label={kpi.label}
                  value={kpi.value}
                  hint={kpi.hint}
                  hintTone={kpi.hintTone}
                  icon={kpi.icon}
                  progress={"progress" in kpi ? kpi.progress : undefined}
                />
              ))}
            </div>

            <div className="lv-px-actions">
              {MODELS_QUICK_ACTIONS.map((action) => (
                <button
                  key={action.id}
                  type="button"
                  className="lv-px-action"
                  onClick={() => toast(action.toast)}
                >
                  <span className="lv-px-action-ico">
                    <PxIcon name={action.icon} />
                  </span>
                  <span className="lv-px-action-title">{action.title}</span>
                  <span className="lv-px-action-sub">{action.subtitle}</span>
                </button>
              ))}
            </div>

            <section className="lv-px-panel" aria-label="Model registry">
              <div className="lv-px-panel-head">
                <h2 className="lv-px-panel-title">↓ Model Registry</h2>
              </div>
              <div className="lv-px-filters">
                <label className="lv-px-search">
                  <PxIcon name="search" />
                  <input
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="Zoek modellen..."
                    aria-label="Zoek modellen"
                  />
                </label>
                <select className="lv-px-select" value={providerFilter} onChange={(e) => setProviderFilter(e.target.value)}>
                  {MODELS_REGISTRY_FILTERS.providers.map((opt) => (
                    <option key={opt} value={opt}>{opt}</option>
                  ))}
                </select>
                <select className="lv-px-select" value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
                  {MODELS_REGISTRY_FILTERS.types.map((opt) => (
                    <option key={opt} value={opt}>{opt}</option>
                  ))}
                </select>
                <select className="lv-px-select" value={capFilter} onChange={(e) => setCapFilter(e.target.value)}>
                  {MODELS_REGISTRY_FILTERS.capabilities.map((opt) => (
                    <option key={opt} value={opt}>{opt}</option>
                  ))}
                </select>
                <select className="lv-px-select" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
                  {MODELS_REGISTRY_FILTERS.statuses.map((opt) => (
                    <option key={opt} value={opt}>{opt}</option>
                  ))}
                </select>
              </div>
              <div className="lv-px-table-wrap">
                <table className="lv-px-table">
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
                          <div className="lv-px-cell-name">
                            <PxIcon name={row.icon} />
                            <strong>{row.name}</strong>
                          </div>
                        </td>
                        <td>
                          <div className="lv-px-cell-name">
                            <PxIcon name={row.providerIcon} />
                            <span>{row.provider}</span>
                          </div>
                        </td>
                        <td>{row.size}</td>
                        <td>{row.quant}</td>
                        <td>
                          <span className={`lv-px-status is-${row.status}`}>
                            <span className="lv-px-status-dot" />
                            {modelStatusLabel(row.status)}
                          </span>
                        </td>
                        <td>
                          <div className="lv-px-pills">
                            {row.capabilities.map((cap) => (
                              <span key={cap} className="lv-px-pill">{cap}</span>
                            ))}
                          </div>
                        </td>
                        <td>{row.lastUsed}</td>
                        <td>
                          <button
                            type="button"
                            className="lv-px-btn"
                            aria-label="Meer acties"
                            onClick={() => toast(`Acties — ${row.name}`)}
                          >
                            <PxIcon name="more" />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>

            <div className="lv-px-widgets">
              <section className="lv-px-panel">
                <div className="lv-px-panel-head">
                  <div>
                    <h3 className="lv-px-panel-title">Download &amp; Import Queue</h3>
                    <p style={{ margin: 0, fontSize: 9, color: "var(--lv-text-muted)" }}>
                      {MODELS_DOWNLOAD_QUEUE.length} items
                    </p>
                  </div>
                  <button type="button" className="lv-px-link" onClick={() => toast("Wachtrij gepauzeerd")}>
                    Alles pauzeren
                  </button>
                </div>
                {MODELS_DOWNLOAD_QUEUE.map((item) => (
                  <div key={item.id} className="lv-px-queue-item">
                    <div className="lv-px-queue-top">
                      <strong>{item.name}</strong>
                      <span>{item.source}</span>
                    </div>
                    {item.state === "done" ? (
                      <span className="lv-px-done">Gereed</span>
                    ) : (
                      <>
                        <div className="lv-px-progress" aria-hidden="true">
                          <i style={{ width: `${item.progress ?? 0}%` }} />
                        </div>
                        <div className="lv-px-queue-meta">
                          <span>{item.progress}%</span>
                          <span>{item.eta}</span>
                        </div>
                      </>
                    )}
                  </div>
                ))}
              </section>

              <section className="lv-px-panel">
                <h3 className="lv-px-panel-title">Benchmark Snapshot</h3>
                <div className="lv-px-filters" style={{ marginTop: 8 }}>
                  <select className="lv-px-select" defaultValue={MODELS_BENCHMARK.modelId} aria-label="Benchmark model">
                    <option value={MODELS_BENCHMARK.modelId}>{MODELS_BENCHMARK.modelLabel}</option>
                  </select>
                  <button type="button" className="lv-px-btn is-gold" onClick={() => toast("Benchmark gestart")}>
                    Uitvoeren
                  </button>
                </div>
                {MODELS_BENCHMARK.metrics.map((metric) => (
                  <div key={metric.id} className="lv-px-bench-metric">
                    <span>{metric.label}</span>
                    <b>{metric.score.toFixed(1)}</b>
                    <div className="lv-px-bench-bar" aria-hidden="true">
                      <i style={{ width: `${metric.score}%` }} />
                    </div>
                  </div>
                ))}
              </section>

              <section className="lv-px-panel">
                <h3 className="lv-px-panel-title">VRAM / Memory Allocatie</h3>
                <div className="lv-px-donut-wrap" style={{ marginTop: 8 }}>
                  <div className="lv-px-donut">
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
                    <div className="lv-px-donut-center">
                      <strong>{MODELS_VRAM.usedPct}%</strong>
                      <span>VRAM</span>
                    </div>
                  </div>
                  <ul className="lv-px-vram-legend">
                    {MODELS_VRAM.slices.map((slice) => (
                      <li key={slice.label}>
                        <i style={{ background: slice.color }} />
                        <span>{slice.label}</span>
                        <b>{slice.gb} GB</b>
                      </li>
                    ))}
                  </ul>
                </div>
                <div className="lv-px-filters" style={{ justifyContent: "space-between", marginTop: 8 }}>
                  <span style={{ fontSize: 10, color: "var(--lv-text-muted)" }}>Totaal {MODELS_VRAM.totalGb} GB</span>
                  <button type="button" className="lv-px-btn" onClick={() => toast("Geheugen optimaliseren")}>
                    <PxIcon name="settings" /> Geheugen optimaliseren
                  </button>
                </div>
              </section>

              <section className="lv-px-panel">
                <div className="lv-px-panel-head">
                  <h3 className="lv-px-panel-title">Opgeslagen Profielen</h3>
                  <button type="button" className="lv-px-link" onClick={() => toast("Nieuw profiel")}>
                    Nieuw +
                  </button>
                </div>
                {MODELS_PROFILES.map((profile) => (
                  <div key={profile.id} className="lv-px-profile">
                    <PxIcon name={profile.icon} />
                    <div>
                      <strong>{profile.name}</strong>
                      <div style={{ fontSize: 9, color: "var(--lv-text-muted)" }}>{profile.detail}</div>
                    </div>
                    <span className="lv-px-profile-count">{profile.count}</span>
                  </div>
                ))}
              </section>
            </div>
          </div>

          <aside className="lv-px-rail">
            <section className="lv-px-rail-section">
              <h3 className="lv-px-rail-title">Actieve Runtime &amp; Routing</h3>
              <div className="lv-px-runtime-card">
                <span className="lv-px-runtime-ico">
                  <PxIcon name="brain" />
                </span>
                <div>
                  <strong>{MODELS_ACTIVE_RUNTIME.name}</strong>
                  <div style={{ fontSize: 9, color: "var(--lv-text-muted)" }}>
                    {MODELS_ACTIVE_RUNTIME.provider} • {MODELS_ACTIVE_RUNTIME.quant}
                  </div>
                  <span className="lv-px-badge-active">Actief</span>
                </div>
              </div>
              {MODELS_ROUTING_TOGGLES.map((toggle) => (
                <div key={toggle.id} className="lv-px-toggle-row">
                  <div>
                    <strong>{toggle.label}</strong>
                    <span>{toggle.hint}</span>
                  </div>
                  <PxSwitch
                    label={toggle.label}
                    on={!!toggles[toggle.id]}
                    onToggle={() => {
                      setToggles((prev) => ({ ...prev, [toggle.id]: !prev[toggle.id] }));
                      toast(toggle.label);
                    }}
                  />
                </div>
              ))}
              <div style={{ marginTop: 8, fontSize: 10 }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                  <span>Context geheugen</span>
                  <b>{MODELS_ACTIVE_RUNTIME.contextTokens} tokens</b>
                </div>
                <input
                  type="range"
                  min={8}
                  max={128}
                  defaultValue={32}
                  aria-label="Context geheugen"
                  onChange={() => toast("Context geheugen")}
                />
              </div>
            </section>

            <section className="lv-px-rail-section">
              <h3 className="lv-px-rail-title">Provider Status</h3>
              {MODELS_PROVIDERS.map((provider) => (
                <div key={provider.id} className="lv-px-provider-row">
                  <div className="lv-px-provider-top">
                    <div>
                      <strong>{provider.name}</strong>
                      <span style={{ color: "var(--lv-text-muted)" }}> · {provider.kind}</span>
                    </div>
                    <span style={{ color: provider.status === "degraded" ? "var(--lv-warning)" : "var(--lv-success)" }}>
                      {provider.status === "degraded" ? "Degraded" : "Online"}
                    </span>
                  </div>
                  <div className="lv-px-provider-bar" aria-hidden="true">
                    <i className={provider.status} style={{ width: `${provider.healthPct}%` }} />
                  </div>
                  <div className="lv-px-provider-meta">
                    <span>
                      {provider.loaded}/{provider.total}
                    </span>
                    <span>{provider.healthPct}%</span>
                  </div>
                </div>
              ))}
            </section>

            <section className="lv-px-rail-section">
              <h3 className="lv-px-rail-title">Snelkoppeling</h3>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                <button type="button" className="lv-px-btn" onClick={() => toast("Model Training")}>
                  Model Training
                </button>
                <button type="button" className="lv-px-btn is-gold" onClick={() => toast("LLM Studio")}>
                  LLM Studio
                </button>
              </div>
            </section>
          </aside>
        </div>
      </main>
    </AppShell>
  );
}
