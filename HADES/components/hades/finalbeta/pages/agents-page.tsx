/** FINALBETA Agents — live agents console. */
"use client";

import { useMemo, useState } from "react";
import { toast } from "sonner";
import { useHadesQuery, invalidateHadesQuery } from "@/hooks/use-hades-query";
import { hadesApi, type HadesAgent } from "@/lib/hades-api";
import { FinalBetaShell } from "../shell/finalbeta-shell";
import type { FinalBetaNavigate } from "../types";

type Props = { onNavigate: FinalBetaNavigate };

function statusTag(agent: HadesAgent) {
  if (agent.status === "running" || agent.status === "busy") return { label: agent.status_label || "Bezig", tone: "gold" };
  if (agent.status === "error") return { label: agent.status_label || "Fout", tone: "warn" };
  if (!agent.enabled) return { label: "Uitgeschakeld", tone: "" };
  if (agent.planned && !agent.implemented) return { label: "Gepland", tone: "warn" };
  return { label: agent.status_label || "Gereed", tone: "green" };
}

export function AgentsPage({ onNavigate }: Props) {
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const agentsQuery = useHadesQuery(
    "hades:agents",
    async () => hadesApi.agents(),
    { staleTime: 4_000, refetchInterval: 8_000 },
  );

  const items = agentsQuery.data?.items ?? [];
  const summary = agentsQuery.data?.summary;
  const activity = agentsQuery.data?.activity ?? [];

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter(
      (a) =>
        a.name.toLowerCase().includes(q) ||
        a.role.toLowerCase().includes(q) ||
        a.description.toLowerCase().includes(q) ||
        a.id.toLowerCase().includes(q),
    );
  }, [items, query]);

  const selected = items.find((a) => a.id === selectedId) ?? filtered[0] ?? null;

  const refresh = async () => {
    invalidateHadesQuery("hades:agents");
    try {
      await agentsQuery.refetch();
      toast.success("Agents vernieuwd");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Vernieuwen mislukt");
    }
  };

  const body = (
    <>
      <div className="page-head" data-live="agents">
        <div>
          <h1 className="page-title">Agents</h1>
          <p className="page-sub">Specialisten voor research, coding, planning en meer.</p>
        </div>
        <div className="page-actions">
          <button className="btn btn-outline" type="button" onClick={() => void refresh()}>
            Vernieuwen
          </button>
          <button className="btn btn-gold" type="button" onClick={() => onNavigate("tasks")}>
            Taken
          </button>
        </div>
      </div>

      {agentsQuery.error ? (
        <div className="card card-pad" role="alert" style={{ marginBottom: 12 }}>
          <strong>Agents laden mislukt.</strong> {agentsQuery.error.message}
        </div>
      ) : null}

      <div className="stat-grid-3" style={{ marginBottom: 12 }}>
        <div className="card card-pad">
          <div className="muted">Totaal</div>
          <div style={{ fontWeight: 700 }}>{summary?.total ?? (agentsQuery.status === "loading" ? "…" : 0)}</div>
        </div>
        <div className="card card-pad">
          <div className="muted">Enabled / running</div>
          <div style={{ fontWeight: 700 }}>
            {summary ? `${summary.enabled} / ${summary.running}` : "—"}
          </div>
        </div>
        <div className="card card-pad">
          <div className="muted">Provider</div>
          <div style={{ fontWeight: 700 }}>
            {summary?.provider_connected ? summary.active_model || summary.provider : "Offline"}
          </div>
        </div>
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
        <div className="search-bar grow">
          <input
            placeholder="Zoek agents..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Zoek agents"
          />
        </div>
      </div>

      {agentsQuery.status === "loading" && !items.length ? <p className="muted">Agents laden…</p> : null}
      {items.length === 0 && agentsQuery.status !== "loading" ? (
        <p className="muted">Geen agents beschikbaar.</p>
      ) : null}

      <div className="agent-grid">
        {filtered.map((agent) => {
          const tag = statusTag(agent);
          const isSelected = selected?.id === agent.id;
          return (
            <button
              key={agent.id}
              type="button"
              className={`card agent-card${isSelected ? " selected" : ""}`}
              onClick={() => setSelectedId(agent.id)}
              data-agent-id={agent.id}
            >
              <div className="agent-ico">◇</div>
              <div>
                <div className="agent-name">{agent.name}</div>
                <div className="agent-desc">{agent.description || agent.role}</div>
                <div style={{ marginTop: 6, fontSize: 11 }}>
                  <span className={`tag ${tag.tone}`.trim()}>{tag.label}</span>
                </div>
              </div>
              <div className="muted" style={{ fontSize: 11, textAlign: "right" }}>
                {agent.model || agent.provider || "—"}
              </div>
            </button>
          );
        })}
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
        <h3 className="insp-title">Agentprofiel</h3>
        <div className="insp-card">
          {selected ? (
            <>
              <div className="detail-row">
                <span className="k">Naam</span>
                <span className="v">{selected.name}</span>
              </div>
              <div className="detail-row">
                <span className="k">Status</span>
                <span className="v">{selected.status_label || selected.status || "—"}</span>
              </div>
              <div className="detail-row">
                <span className="k">Health</span>
                <span className="v">{selected.health_label || selected.health || "—"}</span>
              </div>
              <div className="detail-row">
                <span className="k">Model</span>
                <span className="v">{selected.model || "—"}</span>
              </div>
              <div className="detail-row">
                <span className="k">Current task</span>
                <span className="v">{selected.current_task?.title || "—"}</span>
              </div>
              {selected.last_error ? (
                <div className="detail-row">
                  <span className="k">Error</span>
                  <span className="v">{selected.last_error}</span>
                </div>
              ) : null}
            </>
          ) : (
            <p className="muted">Geen agent geselecteerd.</p>
          )}
        </div>
      </section>
      <section className="insp-section">
        <h3 className="insp-title">Recente activiteit</h3>
        <div className="insp-card">
          {activity.length === 0 ? (
            <p className="muted">Geen recente events.</p>
          ) : (
            activity.slice(0, 8).map((row, idx) => (
              <div className="detail-row" key={`${row.at}-${idx}`}>
                <span className="k">{row.agent_id || row.source || "event"}</span>
                <span className="v">{row.message || "—"}</span>
              </div>
            ))
          )}
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

  return <FinalBetaShell page="agents" body={body} inspector={inspector} onNavigate={onNavigate} />;
}
