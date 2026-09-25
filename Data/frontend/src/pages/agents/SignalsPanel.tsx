/**
 * AGENT COMMUNICATION / SIGNALS panel — real Signal Fabric data (no mocks).
 */
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api } from "../../api/client";
import type {
  AgentCommunicationGraph,
  AgentSignal,
  AgentSignalDeadLetter,
  AgentSignalDelivery,
  AgentSignalMetrics,
  AgentSignalStats,
  SignalCausalChain,
} from "../../types/api";
import { matchesSignalFilter, SIGNAL_FILTERS, type SignalFilterId } from "./signalHelpers";

type Props = {
  selectedAgentId: string | null;
  selectedMissionId: string | null;
  agentNameById: Record<string, string>;
  /** Dense layout: metrics, graph and dead letters collapse into an expandable section. */
  compact?: boolean;
};

type InspectorTab = "Overview" | "Payload" | "Deliveries" | "Causal Chain" | "Mission" | "Evidence";

export function SignalsPanel({ selectedAgentId, selectedMissionId, agentNameById, compact = false }: Props) {
  const [filter, setFilter] = useState<SignalFilterId>("ALL");
  const [signals, setSignals] = useState<AgentSignal[]>([]);
  const [metrics, setMetrics] = useState<AgentSignalMetrics | null>(null);
  const [graph, setGraph] = useState<AgentCommunicationGraph | null>(null);
  const [deadLetters, setDeadLetters] = useState<AgentSignalDeadLetter[]>([]);
  const [agentStats, setAgentStats] = useState<AgentSignalStats | null>(null);
  const [enabled, setEnabled] = useState(true);
  const [live, setLive] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>("Overview");
  const [deliveries, setDeliveries] = useState<AgentSignalDelivery[]>([]);
  const [chain, setChain] = useState<SignalCausalChain | null>(null);
  const [graphWindow, setGraphWindow] = useState<"1" | "24" | "mission">("24");
  const inflight = useRef(false);
  const gen = useRef(0);

  const label = useCallback(
    (id: string) => agentNameById[id] || id.slice(0, 12),
    [agentNameById],
  );

  const load = useCallback(async () => {
    if (inflight.current) return;
    inflight.current = true;
    const g = ++gen.current;
    try {
      const listOpts: Parameters<typeof api.listAgentSignals>[0] = { limit: 80 };
      if (selectedAgentId) listOpts.agentId = selectedAgentId;
      if (selectedMissionId) listOpts.missionId = selectedMissionId;

      const windowHours = graphWindow === "1" ? 1 : 24;
      const [listRes, metricsRes, graphRes, deadRes] = await Promise.all([
        api.listAgentSignals(listOpts),
        api.getAgentSignalMetrics({ windowMinutes: 60 }),
        api.getAgentSignalGraph({
          windowHours,
          missionId: graphWindow === "mission" && selectedMissionId ? selectedMissionId : undefined,
        }),
        api.listAgentSignalDeadLetters({ limit: 20 }),
      ]);
      if (g !== gen.current) return;
      setSignals(listRes.signals ?? []);
      setEnabled(listRes.enabled !== false && metricsRes.enabled !== false);
      setMetrics(metricsRes.metrics ?? null);
      setGraph(graphRes.graph ?? null);
      setDeadLetters(deadRes.deadLetters ?? []);
      setLive(true);
      setError(null);

      if (selectedAgentId) {
        try {
          const agentRes = await api.listSignalsForAgent(selectedAgentId, { limit: 40 });
          if (g === gen.current) setAgentStats(agentRes.stats);
        } catch {
          /* soft-fail */
        }
      } else {
        setAgentStats(null);
      }
    } catch (err) {
      if (g !== gen.current) return;
      setLive(false);
      setError(err instanceof Error ? err.message : "Signal Fabric unreachable");
    } finally {
      if (g === gen.current) setLoading(false);
      inflight.current = false;
    }
  }, [selectedAgentId, selectedMissionId, graphWindow]);

  useEffect(() => {
    void load();
    const id = window.setInterval(() => {
      if (document.visibilityState === "hidden") return;
      void load();
    }, 2500);
    return () => window.clearInterval(id);
  }, [load]);

  useEffect(() => {
    if (!selectedId) {
      setDeliveries([]);
      setChain(null);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const [d, c] = await Promise.all([
          api.listAgentSignalDeliveries(selectedId, { limit: 50 }),
          api.getAgentSignalChain(selectedId, { depth: 4, limit: 40 }),
        ]);
        if (cancelled) return;
        setDeliveries(d.deliveries ?? []);
        setChain(c);
      } catch {
        if (!cancelled) {
          setDeliveries([]);
          setChain(null);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  const filtered = useMemo(
    () => signals.filter((s) => matchesSignalFilter(s, filter)),
    [signals, filter],
  );

  const selected = useMemo(
    () => signals.find((s) => s.signalId === selectedId) ?? chain?.signal ?? null,
    [signals, selectedId, chain],
  );

  async function onRetryDead(id: string) {
    await api.retryAgentSignalDeadLetter(id);
    void load();
  }

  return (
    <div className={`lv-ag-signals${compact ? " is-compact" : ""}`}>
      <div className="lv-ag-panel-bar">
        <strong>AGENT COMMUNICATION / SIGNALS</strong>
        <span className={`lv-ag-live ${live ? "is-on" : "is-off"}`}>
          {live ? "LIVE" : error ? "STALE" : "…"}
        </span>
      </div>

      {!enabled ? (
        <p className="lv-ag-empty">
          Signal Fabric is disabled (LEVIATHAN_FEATURE_SIGNAL_FABRIC / agents flag). Existing fleet
          missions continue to work.
        </p>
      ) : null}

      {error ? <p className="lv-ag-empty lv-ag-warn">{error}</p> : null}

      {agentStats ? (
        <div className="lv-ag-signal-stats">
          <span>Sent {agentStats.signalsSent}</span>
          <span>Recv {agentStats.signalsReceived}</span>
          <span>Handoffs {agentStats.handoffs}</span>
          <span>Verify {agentStats.verificationRequests}</span>
          <span>Blocks {agentStats.blocksRejections}</span>
        </div>
      ) : null}

      {metrics && !compact ? (
        <div className="lv-ag-signal-metrics">
          <span>Total {metrics.signalsTotal}</span>
          <span>Delivered {metrics.delivered}</span>
          <span>ACK {metrics.acknowledged}</span>
          <span>Failed {metrics.failed}</span>
          <span>DLQ {metrics.deadLetter}</span>
          {metrics.avgDeliveryLatencyS != null ? (
            <span>Avg lat {metrics.avgDeliveryLatencyS.toFixed(2)}s</span>
          ) : null}
        </div>
      ) : null}

      <div className="lv-ag-tabs">
        {SIGNAL_FILTERS.map((f) => (
          <button
            key={f.id}
            type="button"
            className={filter === f.id ? "is-active" : ""}
            onClick={() => setFilter(f.id)}
          >
            {f.label}
          </button>
        ))}
      </div>

      {loading && signals.length === 0 ? <p className="lv-ag-empty">Loading signals…</p> : null}

      {!loading && filtered.length === 0 ? (
        <p className="lv-ag-empty">
          No signals yet. Missions, handoffs, findings and verification will appear here as the
          fleet communicates.
        </p>
      ) : null}

      <ul className="lv-ag-logs lv-ag-signal-feed">
        {filtered.map((s) => (
          <li key={s.signalId} className={selectedId === s.signalId ? "is-selected" : ""}>
            <button type="button" className="lv-ag-signal-row" onClick={() => setSelectedId(s.signalId)}>
              <time>{(s.createdAt || "").slice(11, 19) || "—"}</time>
              <span className="lv-ag-log-src">
                {label(s.senderId)} → {label(s.recipientId)}
              </span>
              <span className="lv-ag-signal-type">{s.signalType}</span>
              <span className="lv-ag-log-text">{s.subject || s.signalType}</span>
              <span className="lv-ag-signal-status">{s.status}</span>
              {s.confidence != null ? (
                <span className="lv-ag-signal-conf">{Math.round(s.confidence * 100)}%</span>
              ) : null}
            </button>
          </li>
        ))}
      </ul>

      {selected ? (
        <div className="lv-ag-signal-inspector">
          <div className="lv-ag-panel-bar">
            <strong>Signal Inspector</strong>
            <button type="button" className="lv-ag-btn-teal" onClick={() => setSelectedId(null)}>
              Close
            </button>
          </div>
          <div className="lv-ag-tabs">
            {(["Overview", "Payload", "Deliveries", "Causal Chain", "Mission", "Evidence"] as InspectorTab[]).map(
              (tab) => (
                <button
                  key={tab}
                  type="button"
                  className={inspectorTab === tab ? "is-active" : ""}
                  onClick={() => setInspectorTab(tab)}
                >
                  {tab}
                </button>
              ),
            )}
          </div>
          {inspectorTab === "Overview" ? (
            <dl className="lv-ag-signal-dl">
              <dt>ID</dt>
              <dd>{selected.signalId}</dd>
              <dt>Type</dt>
              <dd>{selected.signalType}</dd>
              <dt>Priority</dt>
              <dd>{selected.priority}</dd>
              <dt>Sender</dt>
              <dd>
                {selected.senderType}/{label(selected.senderId)}
              </dd>
              <dt>Recipient</dt>
              <dd>
                {selected.recipientType}/{label(selected.recipientId)}
              </dd>
              <dt>Status</dt>
              <dd>{selected.status}</dd>
              <dt>Mission</dt>
              <dd>{selected.missionId || "—"}</dd>
              <dt>Run / Trace</dt>
              <dd>
                {selected.runId || "—"} / {selected.traceId || "—"}
              </dd>
              <dt>Correlation</dt>
              <dd>{selected.correlationId || "—"}</dd>
              <dt>Parent</dt>
              <dd>{selected.parentSignalId || "—"}</dd>
              <dt>Hops</dt>
              <dd>
                {selected.hopCount}/{selected.maxHops}
              </dd>
              <dt>ACK required</dt>
              <dd>{selected.requiresAck ? "yes" : "no"}</dd>
              <dt>Confidence</dt>
              <dd>{selected.confidence != null ? selected.confidence : "—"}</dd>
            </dl>
          ) : null}
          {inspectorTab === "Payload" ? (
            <pre className="lv-ag-signal-pre">{JSON.stringify(selected.payload ?? {}, null, 2)}</pre>
          ) : null}
          {inspectorTab === "Deliveries" ? (
            <ul className="lv-ag-logs">
              {deliveries.map((d) => (
                <li key={d.deliveryId}>
                  <span className="lv-ag-log-src">{d.state}</span>
                  <span className="lv-ag-log-text">
                    {d.resolvedAgentId || d.recipientId} · attempts {d.attemptCount}/
                    {d.maxAttempts}
                    {d.lastError ? ` · ${d.lastError}` : ""}
                  </span>
                </li>
              ))}
              {deliveries.length === 0 ? <li className="lv-ag-empty">No deliveries</li> : null}
            </ul>
          ) : null}
          {inspectorTab === "Causal Chain" ? (
            <ol className="lv-ag-signal-chain">
              {(chain?.ancestors ?? [])
                .slice()
                .reverse()
                .map((a) => (
                  <li key={a.signalId}>
                    {label(a.senderId)} → {a.signalType} → {label(a.recipientId)}
                  </li>
                ))}
              <li className="is-current">
                {label(selected.senderId)} → <strong>{selected.signalType}</strong> →{" "}
                {label(selected.recipientId)}
              </li>
              {(chain?.children ?? []).map((c) => (
                <li key={c.signalId}>
                  {label(c.senderId)} → {c.signalType} → {label(c.recipientId)}
                </li>
              ))}
              {!chain ? <li className="lv-ag-empty">Loading chain…</li> : null}
            </ol>
          ) : null}
          {inspectorTab === "Mission" ? (
            <pre className="lv-ag-signal-pre">
              {JSON.stringify(chain?.mission ?? { missionId: selected.missionId }, null, 2)}
            </pre>
          ) : null}
          {inspectorTab === "Evidence" ? (
            <div>
              <p>Artifact refs: {(selected.artifactRefs || []).join(", ") || "—"}</p>
              <p>Evidence refs: {(selected.evidenceRefs || []).join(", ") || "—"}</p>
            </div>
          ) : null}
        </div>
      ) : null}

      <Collapsible compact={compact} summary={`Graph · metrics${deadLetters.length ? ` · ${deadLetters.length} dead letters` : ""}`}>
        {compact && metrics ? (
          <div className="lv-ag-signal-metrics">
            <span>Total {metrics.signalsTotal}</span>
            <span>Delivered {metrics.delivered}</span>
            <span>ACK {metrics.acknowledged}</span>
            <span>Failed {metrics.failed}</span>
            <span>DLQ {metrics.deadLetter}</span>
            {metrics.avgDeliveryLatencyS != null ? (
              <span>Avg lat {metrics.avgDeliveryLatencyS.toFixed(2)}s</span>
            ) : null}
          </div>
        ) : null}
      <div className="lv-ag-panel-bar" style={{ marginTop: "0.75rem" }}>
        <strong>Communication Graph</strong>
        <div className="lv-ag-tabs">
          {(
            [
              ["1", "Last hour"],
              ["24", "Last 24h"],
              ["mission", "Current mission"],
            ] as const
          ).map(([id, lab]) => (
            <button
              key={id}
              type="button"
              className={graphWindow === id ? "is-active" : ""}
              onClick={() => setGraphWindow(id)}
            >
              {lab}
            </button>
          ))}
        </div>
      </div>
      {graph && graph.edges.length > 0 ? (
        <ul className="lv-ag-logs">
          {graph.edges.slice(0, 40).map((e) => (
            <li key={`${e.from}->${e.to}`}>
              <span className="lv-ag-log-src">
                {label(e.from)} → {label(e.to)}
              </span>
              <span className="lv-ag-log-text">
                {e.signalCount} signals
                {e.handoffs ? ` · ${e.handoffs} handoffs` : ""}
                {e.verificationRequests ? ` · ${e.verificationRequests} verify` : ""}
                {e.blocks ? ` · ${e.blocks} blocks` : ""}
                {e.avgDeliveryLatencyS != null
                  ? ` · avg ${e.avgDeliveryLatencyS.toFixed(2)}s`
                  : ""}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="lv-ag-empty">No aggregated communication edges in this window.</p>
      )}

      {deadLetters.length > 0 ? (
        <>
          <div className="lv-ag-panel-bar" style={{ marginTop: "0.75rem" }}>
            <strong>Dead Letters</strong>
          </div>
          <ul className="lv-ag-logs">
            {deadLetters.map((d) => (
              <li key={d.deadLetterId}>
                <span className="lv-ag-log-src">{d.reason || "dead"}</span>
                <span className="lv-ag-log-text">
                  {d.signalId.slice(0, 16)} · {d.lastError || "—"}
                </span>
                {d.retryable ? (
                  <button
                    type="button"
                    className="lv-ag-btn-gold"
                    onClick={() => void onRetryDead(d.deadLetterId)}
                  >
                    Retry
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
        </>
      ) : null}
      </Collapsible>
    </div>
  );
}

function Collapsible({
  compact,
  summary,
  children,
}: {
  compact: boolean;
  summary: string;
  children: ReactNode;
}) {
  if (!compact) return <>{children}</>;
  return (
    <details className="lv-ag-signal-more">
      <summary>{summary}</summary>
      {children}
    </details>
  );
}

export default SignalsPanel;
