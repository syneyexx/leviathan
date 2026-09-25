import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import type { TradeOrchestra, TradeOrchestraSummary, TradingDecision } from "../../types/api";
import {
  TRADING_MISSION_KINDS,
  autonomyLabel,
  decisionOneLiner,
  liveTradingLabel,
  paperCapitalLabel,
  paperPnlLabel,
  parseUniverse,
  readinessLabel,
  readinessReason,
  stageLabel,
  universeLabel,
} from "./tradingHelpers";

type Props = {
  onSelectAgent?: (agentId: string) => void;
  onChanged?: () => void;
  compact?: boolean;
};

export function TradeOrchestraSection({ onSelectAgent, onChanged, compact = false }: Props) {
  const [summary, setSummary] = useState<TradeOrchestraSummary | null>(null);
  const [orchestras, setOrchestras] = useState<TradeOrchestra[]>([]);
  const [selectedId, setSelectedId] = useState<string>("");
  const [detail, setDetail] = useState<TradeOrchestra | null>(null);
  const [decisions, setDecisions] = useState<TradingDecision[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState("");
  const [universe, setUniverse] = useState("BTCUSD");
  const [capital, setCapital] = useState("100000");
  const [asOf, setAsOf] = useState("");
  const [missionKind, setMissionKind] = useState<string>("deliberation_round");
  const [lastMission, setLastMission] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [s, list] = await Promise.all([api.tradeOrchestraSummary(), api.listTradeOrchestras()]);
      setSummary(s);
      setOrchestras(list.orchestras);
      setError(null);
      if (!selectedId && list.orchestras.length) setSelectedId(list.orchestras[0].orchestraId);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [selectedId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!selectedId) {
        await Promise.resolve();
        if (!cancelled) {
          setDetail(null);
          setDecisions([]);
        }
        return;
      }
      try {
        const [d, decs] = await Promise.all([
          api.getTradeOrchestra(selectedId),
          api.listTradingDecisions({ orchestraId: selectedId, limit: 40 }),
        ]);
        if (cancelled) return;
        setDetail(d.orchestra);
        setDecisions(decs.decisions);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedId, lastMission]);

  const create = async () => {
    if (!name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const { orchestra } = await api.createTradeOrchestra({
        name: name.trim(),
        mandate: { universe: parseUniverse(universe), paperCapital: Number(capital) || 100000 },
      });
      setName("");
      setSelectedId(orchestra.orchestraId);
      await load();
      onChanged?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const launch = async () => {
    if (!selectedId) return;
    setBusy(true);
    setError(null);
    try {
      const { mission } = await api.launchTradeMission(selectedId, {
        kind: missionKind,
        asOf: asOf.trim() || undefined,
      });
      setLastMission(`${mission.missionId} · ${mission.status}${mission.error ? ` · ${mission.error}` : ""}`);
      await load();
      onChanged?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="lv-ag-trading">
      {error ? <div className="lv-ag-empty">{error}</div> : null}
      {summary ? (
        <div className="lv-ag-usage-meta lv-ag-trading-meta">
          <span>
            Orkesten <em>{summary.orchestras}</em>
          </span>
          <span>
            Model <em>{summary.modelAvailable ? summary.model : "UNAVAILABLE"}</em>
          </span>
          <span>
            Nieuwsfeeds <em>{summary.feedsEnabled}/{summary.feeds}</em>
          </span>
          <span>
            Nieuwsitems <em>{summary.newsItems}</em>
          </span>
          <span>
            Live trading <em>{String(summary.truth?.live_trading ?? "ONBEKEND")}</em>
          </span>
          <span>
            Uitvoering <em>{summary.externalized ? "workers" : "in-process"}</em>
          </span>
        </div>
      ) : null}

      <div className="lv-ag-trading-grid">
        <div className="lv-ag-trading-list">
          {orchestras.length === 0 ? (
            <p className="lv-ag-empty">
              Nog geen trade-orkest. Maak er een aan; de leden (nieuws-analist, signaal-analist, criticus,
              risk officer, executie-agent, post-mortem) worden als trading-agents aangemaakt.
            </p>
          ) : (
            <ul className="lv-ag-logs">
              {orchestras.map((o) => (
                <li key={o.orchestraId}>
                  <button
                    type="button"
                    className={`lv-ag-linkish lv-ag-log-text${o.orchestraId === selectedId ? " is-active" : ""}`}
                    onClick={() => setSelectedId(o.orchestraId)}
                  >
                    {o.name} · {autonomyLabel(o.autonomyLevel)} · {readinessLabel(o)} · {o.decisionStats.total} besluiten
                  </button>
                </li>
              ))}
            </ul>
          )}
          <div className="lv-ag-trading-form">
            <input placeholder="Naam orkest" value={name} onChange={(e) => setName(e.target.value)} />
            <input placeholder="Universum (BTCUSD, ETHUSD)" value={universe} onChange={(e) => setUniverse(e.target.value)} />
            <input placeholder="Paper kapitaal" value={capital} onChange={(e) => setCapital(e.target.value)} />
            <button type="button" className="lv-ag-btn-teal" disabled={busy || !name.trim()} onClick={() => void create()}>
              Orkest aanmaken
            </button>
          </div>
        </div>

        <div className="lv-ag-trading-detail">
          {detail ? (
            <>
              <div className="lv-ag-trading-kpis">
                <div>
                  <span>Autonomie</span>
                  <strong>{autonomyLabel(detail.mandate.autonomyLevel)}</strong>
                </div>
                <div>
                  <span>Gereedheid</span>
                  <strong title={readinessReason(detail)}>{readinessLabel(detail)}</strong>
                </div>
                <div>
                  <span>Paper kapitaal</span>
                  <strong>{paperCapitalLabel(detail.mandate)}</strong>
                </div>
                <div>
                  <span>Paper PnL</span>
                  <strong>{paperPnlLabel(detail.decisionStats)}</strong>
                </div>
                <div>
                  <span>Risico-weigeringen</span>
                  <strong>{detail.decisionStats.riskRejections}</strong>
                </div>
                <div>
                  <span>Live trading</span>
                  <strong>{liveTradingLabel(detail)}</strong>
                </div>
              </div>
              <p className="lv-ag-trading-mandate">
                Universum: {universeLabel(detail.mandate)} · max {detail.mandate.maxOrdersPerDay} orders/dag ·{" "}
                {detail.mandate.perTradeRiskPct}% risico/trade · {detail.mandate.maxSymbolExposurePct}% per symbool ·{" "}
                max drawdown {detail.mandate.maxDrawdownPct}% · cadans {detail.mandate.decisionCadence} · mandaat{" "}
                <code>{detail.mandateFingerprint}</code>
              </p>
              <div className="lv-ag-trading-members">
                {(detail.members ?? []).map((m) => (
                  <button
                    key={m.agentId}
                    type="button"
                    className="lv-ag-badge is-inline"
                    title={`${m.kind} · ${m.role}`}
                    onClick={() => onSelectAgent?.(m.agentId)}
                  >
                    {m.name.replace(`${detail.name} · `, "")} {m.enabled ? "" : "(uit)"}
                  </button>
                ))}
              </div>
              <div className="lv-ag-trading-form is-row">
                <select value={missionKind} onChange={(e) => setMissionKind(e.target.value)}>
                  {TRADING_MISSION_KINDS.map((k) => (
                    <option key={k.kind} value={k.kind}>
                      {k.label}
                    </option>
                  ))}
                </select>
                <input
                  placeholder="as_of (ISO, leeg = nu)"
                  value={asOf}
                  onChange={(e) => setAsOf(e.target.value)}
                />
                <button type="button" className="lv-ag-btn-gold" disabled={busy} onClick={() => void launch()}>
                  Missie starten
                </button>
              </div>
              {lastMission ? <p className="lv-ag-trading-last">Laatste missie: {lastMission}</p> : null}
              {!compact ? (
                <ul className="lv-ag-logs lv-ag-trading-decisions">
                  {decisions.length === 0 ? (
                    <li className="lv-ag-empty">Nog geen beslissingsrecords voor dit orkest.</li>
                  ) : (
                    decisions.map((d) => (
                      <li key={d.decisionId}>
                        <time>{d.asOf.slice(0, 16)}</time>
                        <span className="lv-ag-log-src">[{stageLabel(d.stage)}]</span>
                        <span className="lv-ag-log-text">{decisionOneLiner(d)}</span>
                        <em>{d.modelId ?? "tier0"}</em>
                      </li>
                    ))
                  )}
                </ul>
              ) : null}
              <p className="lv-ag-trading-footer">
                <Link to="/trading/onderzoek">Trading-onderzoek (nieuws, signalen, beslissingen)</Link>
              </p>
            </>
          ) : (
            <p className="lv-ag-empty">Selecteer een orkest.</p>
          )}
        </div>
      </div>
    </div>
  );
}
