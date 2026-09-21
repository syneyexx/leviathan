/** FINALBETA Models — live LM Studio / model discovery. */
"use client";

import { useMemo, useState } from "react";
import { toast } from "sonner";
import { useHadesQuery, invalidateHadesQuery } from "@/hooks/use-hades-query";
import { hadesApi } from "@/lib/hades-api";
import { FinalBetaShell } from "../shell/finalbeta-shell";
import type { FinalBetaNavigate } from "../types";

type Props = { onNavigate: FinalBetaNavigate };

export function ModelsPage({ onNavigate }: Props) {
  const [query, setQuery] = useState("");
  const modelsQuery = useHadesQuery(
    "hades:models",
    async () => hadesApi.models(),
    { staleTime: 5_000, refetchInterval: 15_000 },
  );
  const settingsQuery = useHadesQuery(
    "hades:settings:models-page",
    async () => hadesApi.settings(),
    { staleTime: 10_000 },
  );

  const data = modelsQuery.data;
  const models = data?.models ?? [];
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return models;
    return models.filter((m) => m.id.toLowerCase().includes(q) || String(m.owned_by || "").toLowerCase().includes(q));
  }, [models, query]);

  const activeProfile = data?.active_profile;
  const gateway = data?.gateway;
  const lmUrl = settingsQuery.data?.values?.lm_studio_base_url || "—";

  const refresh = async () => {
    invalidateHadesQuery("hades:models");
    try {
      await modelsQuery.refetch();
      toast.success("Modellen vernieuwd");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Vernieuwen mislukt");
    }
  };

  const body = (
    <>
      <div className="page-head" data-live="models">
        <div>
          <h1 className="page-title">Modellen</h1>
          <p className="page-sub">Beheer lokale modellen en runtime-instellingen.</p>
        </div>
        <div className="page-actions">
          <button className="btn btn-gold" type="button" onClick={() => void refresh()}>
            Modellen zoeken
          </button>
          <button className="btn btn-outline" type="button" onClick={() => onNavigate("settings-llm-studio")}>
            LLM Studio
          </button>
        </div>
      </div>

      {modelsQuery.error ? (
        <div className="card card-pad" role="alert" style={{ marginBottom: 12 }}>
          <strong>Model discovery mislukt.</strong> {modelsQuery.error.message}
        </div>
      ) : null}

      <div className="stat-grid-3" style={{ marginBottom: 12 }}>
        <div className="card card-pad">
          <div className="muted">LM Studio</div>
          <div style={{ fontWeight: 700 }}>{data?.connected ? "Verbonden" : data ? "Offline" : "…"}</div>
          <div className="muted" style={{ fontSize: 11 }}>{lmUrl}</div>
        </div>
        <div className="card card-pad">
          <div className="muted">Actief model</div>
          <div style={{ fontWeight: 700 }}>
            {activeProfile?.model_id || gateway?.models_in_use?.[0] || (data?.connected ? "—" : "Onbekend")}
          </div>
          <div className="muted" style={{ fontSize: 11 }}>
            {data?.latency_ms != null ? `${data.latency_ms} ms discovery` : "geen latency"}
          </div>
        </div>
        <div className="card card-pad">
          <div className="muted">Ontdekt</div>
          <div style={{ fontWeight: 700 }}>{models.length}</div>
          <div className="muted" style={{ fontSize: 11 }}>
            {gateway?.active_count != null ? `${gateway.active_count} actieve calls` : "geen gateway metrics"}
          </div>
        </div>
      </div>

      <section className="card" style={{ padding: 0, overflow: "hidden" }}>
        <div style={{ padding: "10px 12px", display: "flex", gap: 8, borderBottom: "1px solid var(--border-soft)" }}>
          <div className="search-bar grow">
            <input
              placeholder="Zoek ontdekte modellen..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              aria-label="Zoek modellen"
            />
          </div>
        </div>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Model</th>
                <th>Provider</th>
                <th>Type</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {!data && modelsQuery.status === "loading" ? (
                <tr>
                  <td colSpan={4} className="muted">
                    Modellen laden…
                  </td>
                </tr>
              ) : null}
              {data && filtered.length === 0 ? (
                <tr>
                  <td colSpan={4} className="muted">
                    {data.connected
                      ? "Geen modellen gevonden."
                      : data.error || "LM Studio niet bereikbaar — geen fake geladen modellen."}
                  </td>
                </tr>
              ) : null}
              {filtered.map((model) => {
                const selected = activeProfile?.model_id === model.id;
                return (
                  <tr key={model.id} className={selected ? "selected" : undefined}>
                    <td>
                      <strong>{model.id}</strong>
                    </td>
                    <td>{model.owned_by || "LM Studio"}</td>
                    <td>{model.object || "model"}</td>
                    <td>
                      <span className={`tag${selected ? " green" : ""}`}>
                        {selected ? "Actief profiel" : data?.connected ? "Beschikbaar" : "Onbekend"}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <div className="page-grid-2" style={{ marginTop: 12 }}>
        <section className="card card-pad">
          <h2 className="section-title">Routering / gateway</h2>
          <div className="kv">
            <span>Models in use</span>
            <span>{gateway?.models_in_use?.join(", ") || "—"}</span>
          </div>
          <div className="kv">
            <span>Queue depth</span>
            <span>{gateway?.queue_depth ?? "—"}</span>
          </div>
          <div className="kv">
            <span>Active calls</span>
            <span>{gateway?.active_count ?? "—"}</span>
          </div>
        </section>
        <section className="card card-pad">
          <h2 className="section-title">Profiel</h2>
          <div className="kv">
            <span>Model</span>
            <span>{activeProfile?.model_id || "—"}</span>
          </div>
          <div className="kv">
            <span>Temperature</span>
            <span>{activeProfile?.temperature ?? "—"}</span>
          </div>
          <div className="kv">
            <span>Max tokens</span>
            <span>{activeProfile?.max_tokens ?? "—"}</span>
          </div>
        </section>
      </div>
    </>
  );

  const inspector = (
    <>
      <p className="quote">
        “Sovereign AI. Local power.
        <br />
        Infinite possibilities.”
      </p>
      <section className="insp-section">
        <h3 className="insp-title">Modeldetail</h3>
        <div className="insp-card">
          <div className="detail-row">
            <span className="k">Status</span>
            <span className={`v${data?.connected ? " green" : ""}`}>
              {data?.connected ? "● Online" : data ? "● Offline" : "…"}
            </span>
          </div>
          <div className="detail-row">
            <span className="k">Bron</span>
            <span className="v">/api/models</span>
          </div>
          <div className="detail-row">
            <span className="k">Count</span>
            <span className="v">{models.length}</span>
          </div>
          <div className="detail-row">
            <span className="k">UI</span>
            <span className="v">FINALBETA live</span>
          </div>
        </div>
      </section>
      <section className="insp-section">
        <h3 className="insp-title">Snelacties</h3>
        <div className="insp-card" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <button className="btn btn-sm btn-outline btn-block" type="button" onClick={() => void refresh()}>
            Refresh
          </button>
          <button className="btn btn-sm btn-gold btn-block" type="button" onClick={() => onNavigate("tasks")}>
            Open Work Runtime
          </button>
        </div>
      </section>
    </>
  );

  return <FinalBetaShell page="models" body={body} inspector={inspector} onNavigate={onNavigate} />;
}
