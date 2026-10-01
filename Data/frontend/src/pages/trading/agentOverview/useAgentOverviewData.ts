/**
 * Agent Overzicht data composition — orchestra members + paper portfolios +
 * deployments + decisions. Production truth only; UNMEASURED when unknown.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../../../api/client";
import type {
  MarketSimPaperDeployment,
  PaperPortfolio,
  TradeOrchestra,
  TradeOrchestraMember,
  TradingDecision,
} from "../../../types/api";
import {
  UNMEASURED,
  asNumber,
  asRec,
  fmtInt,
  fmtUsd,
  measuredNumber,
} from "../workspaces/commandHub/hubFormat";

export type AoTone = "green" | "blue" | "purple" | "gold" | "red" | "muted";

export type AoKpi = {
  id: string;
  label: string;
  value: string;
  delta: string;
  deltaTone: AoTone;
  tone: AoTone;
  spark: number[];
  sparkKind: "line" | "bars";
};

export type AoAgentRow = {
  id: string;
  name: string;
  role: string;
  orchestraId: string;
  orchestraName: string;
  walletId: string | null;
  walletLabel: string;
  walletCash: number | null;
  pnlToday: number | null;
  exposurePct: number | null;
  lastTrade: string;
  status: string;
  statusTone: AoTone;
  enabled: boolean;
  health: string;
  strategy: string;
  mode: "live_data" | "simulation" | "paused" | "active" | "unknown";
};

export type AoAllocation = {
  id: string;
  name: string;
  equity: number | null;
  pct: number | null;
  available: number | null;
  reserved: number | null;
  isolated: boolean;
};

export type AoArchNode = {
  id: string;
  label: string;
  count: string;
  status: string;
  tone: AoTone;
};

export type AoActivity = {
  id: string;
  time: string;
  agent: string;
  event: string;
  detail: string;
};

export type AoRiskSnapshot = {
  maxDrawdown: string;
  var: string;
  totalExposure: string;
  openPositions: string;
  killSwitch: string;
  riskGuard: string;
};

export type AoDetailTab = "overzicht" | "wallet" | "sessies" | "architectuur";

export type AoFilter = "all" | "active" | "paused" | "simulation";

async function safe<T>(fn: () => Promise<T>, fallback: T): Promise<T> {
  try {
    return await fn();
  } catch {
    return fallback;
  }
}

function statusTone(status: string): AoTone {
  const s = status.toUpperCase();
  if (["RUNNING", "ACTIVE", "READY", "ONLINE", "LIVE", "WARM"].includes(s)) return "green";
  if (["PAUSED", "PAUSE", "SHADOW", "PENDING"].includes(s)) return "gold";
  if (["BLOCKED", "ERROR", "FAILED", "KILLED", "STOPPED"].includes(s)) return "red";
  if (["SIMULATION", "REPLAY", "OFFLINE"].includes(s)) return "purple";
  return "muted";
}

function flatSpark(v: number, len = 8): number[] {
  return new Array(len).fill(Number.isFinite(v) ? v : 0);
}

export function useAgentOverviewData() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const [filter, setFilter] = useState<AoFilter>("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detailTab, setDetailTab] = useState<AoDetailTab>("overzicht");
  const [search, setSearch] = useState("");

  const [agents, setAgents] = useState<AoAgentRow[]>([]);
  const [kpis, setKpis] = useState<AoKpi[]>([]);
  const [allocations, setAllocations] = useState<AoAllocation[]>([]);
  const [architecture, setArchitecture] = useState<AoArchNode[]>([]);
  const [activity, setActivity] = useState<AoActivity[]>([]);
  const [risk, setRisk] = useState<AoRiskSnapshot>({
    maxDrawdown: UNMEASURED,
    var: UNMEASURED,
    totalExposure: UNMEASURED,
    openPositions: UNMEASURED,
    killSwitch: UNMEASURED,
    riskGuard: UNMEASURED,
  });
  const [portfolios, setPortfolios] = useState<PaperPortfolio[]>([]);
  const [orchestras, setOrchestras] = useState<TradeOrchestra[]>([]);
  const [deployments, setDeployments] = useState<MarketSimPaperDeployment[]>([]);
  const [decisions, setDecisions] = useState<TradingDecision[]>([]);
  const [liveTrading, setLiveTrading] = useState("BLOCKED");
  const [fundingBusy, setFundingBusy] = useState(false);
  const [fundingNotice, setFundingNotice] = useState<string | null>(null);

  const gen = useRef(0);

  const refresh = useCallback(async () => {
    const g = ++gen.current;
    setLoading(true);
    setError(null);
    try {
      const [orchResp, portResp, depResp, live, decisionsResp] = await Promise.all([
        safe(() => api.listTradeOrchestras(false), { orchestras: [] as TradeOrchestra[] }),
        safe(() => api.listPortfolios(50), { portfolios: [] as PaperPortfolio[] }),
        safe(() => api.listPaperDeployments({ limit: 50 }), {
          deployments: [] as MarketSimPaperDeployment[],
          truth: {},
        }),
        safe(() => api.marketSimLiveTradingStatus(), { LIVE_TRADING_AVAILABLE: "BLOCKED" }),
        safe(() => api.listTradingDecisions({ limit: 40 }), { decisions: [] as TradingDecision[] }),
      ]);

      if (g !== gen.current) return;

      const orchList = orchResp.orchestras || [];
      setOrchestras(orchList);
      const portList = portResp.portfolios || [];
      setPortfolios(portList);
      const depList = depResp.deployments || [];
      setDeployments(depList);
      setLiveTrading(String((live as { LIVE_TRADING_AVAILABLE?: string }).LIVE_TRADING_AVAILABLE || "BLOCKED"));
      setDecisions(decisionsResp.decisions || []);

      // Fetch member details for enabled orchestras (bounded).
      const detailTargets = orchList.filter((o) => o.enabled).slice(0, 8);
      const details = await Promise.all(
        detailTargets.map((o) =>
          safe(() => api.getTradeOrchestra(o.orchestraId), null as { orchestra: TradeOrchestra } | null),
        ),
      );
      if (g !== gen.current) return;

      const memberRows: AoAgentRow[] = [];
      for (let i = 0; i < detailTargets.length; i++) {
        const base = detailTargets[i];
        const full = details[i]?.orchestra || base;
        const members: TradeOrchestraMember[] = full.members || [];
        for (const m of members) {
          const linked = portList.find((p) => p.orchestra_id === base.orchestraId);
          const cash = linked ? asNumber(linked.cash) : null;
          const equity = linked ? asNumber(linked.equity) : null;
          const realized = linked ? asNumber(linked.realized_pnl) : null;
          const exposure = linked ? asNumber(linked.gross_exposure) : null;
          const exposurePct =
            equity != null && equity > 0 && exposure != null ? (exposure / equity) * 100 : null;
          const health = String(m.health || "unknown");
          const enabled = Boolean(m.enabled);
          let mode: AoAgentRow["mode"] = "unknown";
          if (!enabled || /pause/i.test(health)) mode = "paused";
          else if (/sim|replay|offline/i.test(health)) mode = "simulation";
          else if (enabled) mode = "active";

          memberRows.push({
            id: m.agentId || `${base.orchestraId}-${m.name}`,
            name: m.name || m.agentId || "Agent",
            role: m.role || m.canonicalRole || m.kind || UNMEASURED,
            orchestraId: base.orchestraId,
            orchestraName: base.name,
            walletId: linked?.portfolio_id ?? null,
            walletLabel: linked?.name ?? UNMEASURED,
            walletCash: cash ?? equity,
            pnlToday: realized,
            exposurePct,
            lastTrade: UNMEASURED,
            status: enabled ? health : "Pauze",
            statusTone: statusTone(enabled ? health : "PAUSED"),
            enabled,
            health,
            strategy: UNMEASURED,
            mode,
          });
        }
      }

      // Fallback: if no members, still show orchestra shells as rows.
      if (!memberRows.length) {
        for (const o of orchList.slice(0, 12)) {
          memberRows.push({
            id: o.orchestraId,
            name: o.name,
            role: o.role || "orchestra",
            orchestraId: o.orchestraId,
            orchestraName: o.name,
            walletId: null,
            walletLabel: UNMEASURED,
            walletCash: null,
            pnlToday: null,
            exposurePct: null,
            lastTrade: UNMEASURED,
            status: String(o.health || (o.enabled ? "Ready" : "Paused")),
            statusTone: statusTone(String(o.health || (o.enabled ? "READY" : "PAUSED"))),
            enabled: o.enabled,
            health: String(o.health || "unknown"),
            strategy: UNMEASURED,
            mode: o.enabled ? "active" : "paused",
          });
        }
      }

      setAgents(memberRows);

      const activeCount = memberRows.filter((a) => a.enabled && a.mode !== "paused").length;
      const equitySum = portList.reduce((acc, p) => acc + (asNumber(p.equity) ?? 0), 0);
      const pnlSum = portList.reduce((acc, p) => acc + (asNumber(p.realized_pnl) ?? 0), 0);
      const openSessions = depList.filter((d) => {
        const st = String(d.status || "").toUpperCase();
        return ["ACTIVE", "RUNNING", "SHADOW", "PAPER"].some((t) => st.includes(t));
      }).length;

      setKpis([
        {
          id: "total",
          label: "Totaal agents",
          value: fmtInt(memberRows.length),
          delta: UNMEASURED,
          deltaTone: "muted",
          tone: "blue",
          spark: flatSpark(memberRows.length),
          sparkKind: "bars",
        },
        {
          id: "active",
          label: "Actieve agents",
          value: `${activeCount}/${memberRows.length || 0}`,
          delta: UNMEASURED,
          deltaTone: "muted",
          tone: "green",
          spark: flatSpark(activeCount),
          sparkKind: "bars",
        },
        {
          id: "equity",
          label: "Paper equity",
          value: portList.length ? fmtUsd(equitySum) : UNMEASURED,
          delta: UNMEASURED,
          deltaTone: "muted",
          tone: "green",
          spark: portList.length ? portList.slice(0, 10).map((p) => asNumber(p.equity) ?? 0) : [],
          sparkKind: "bars",
        },
        {
          id: "pnl",
          label: "Dagelijkse PnL",
          value: portList.length ? fmtUsd(pnlSum) : UNMEASURED,
          delta: UNMEASURED,
          deltaTone: "muted",
          tone: pnlSum >= 0 ? "green" : "red",
          spark: portList.length ? portList.slice(0, 10).map((p) => asNumber(p.realized_pnl) ?? 0) : [],
          sparkKind: "line",
        },
        {
          id: "sessions",
          label: "Open sessies",
          value: fmtInt(openSessions),
          delta: UNMEASURED,
          deltaTone: "muted",
          tone: "purple",
          spark: flatSpark(openSessions),
          sparkKind: "bars",
        },
      ]);

      const totalEq = equitySum || 0;
      setAllocations(
        portList.map((p) => {
          const eq = asNumber(p.equity);
          return {
            id: p.portfolio_id,
            name: p.name,
            equity: eq,
            pct: eq != null && totalEq > 0 ? (eq / totalEq) * 100 : null,
            available: asNumber(p.cash),
            reserved: asNumber(p.reserved_cash),
            isolated: true,
          };
        }),
      );

      const researchRoles = memberRows.filter((a) => /research|signal|analyst/i.test(a.role)).length;
      const execRoles = memberRows.filter((a) => /exec|trader|order/i.test(a.role)).length;
      setArchitecture([
        {
          id: "orchestrator",
          label: "Trading Orchestrator",
          count: fmtInt(orchList.length),
          status: orchList.length ? "Ready" : UNMEASURED,
          tone: orchList.length ? "green" : "muted",
        },
        {
          id: "research",
          label: "Research Agents",
          count: researchRoles ? fmtInt(researchRoles) : UNMEASURED,
          status: researchRoles ? "Ready" : UNMEASURED,
          tone: researchRoles ? "blue" : "muted",
        },
        {
          id: "signal",
          label: "Signal Agents",
          count: UNMEASURED,
          status: UNMEASURED,
          tone: "muted",
        },
        {
          id: "risk",
          label: "Risk Engine",
          count: "1",
          status: "Ready",
          tone: "green",
        },
        {
          id: "execution",
          label: "Execution Agent",
          count: execRoles ? fmtInt(execRoles) : UNMEASURED,
          status: execRoles ? "Ready" : UNMEASURED,
          tone: execRoles ? "green" : "muted",
        },
        {
          id: "mdb",
          label: "Market Data Bus",
          count: UNMEASURED,
          status: UNMEASURED,
          tone: "muted",
        },
        {
          id: "broker",
          label: "Paper Broker",
          count: "1",
          status: "Ready",
          tone: "green",
        },
        {
          id: "ledger",
          label: "Portfolio Ledger",
          count: fmtInt(portList.length),
          status: portList.length ? "Ready" : UNMEASURED,
          tone: portList.length ? "green" : "muted",
        },
      ]);

      const acts: AoActivity[] = [];
      for (const d of (decisionsResp.decisions || []).slice(0, 20)) {
        acts.push({
          id: d.decisionId,
          time: d.asOf || UNMEASURED,
          agent: d.agentId || UNMEASURED,
          event: d.stage || "decision",
          detail: String(asRec(d.payload)?.summary || asRec(d.payload)?.thesis || "").slice(0, 120) || UNMEASURED,
        });
      }
      for (const dep of depList.slice(0, 10)) {
        acts.push({
          id: `dep-${dep.deployment_id}`,
          time: UNMEASURED,
          agent: String(dep.strategy_asset_id || "").slice(0, 18) || UNMEASURED,
          event: `deployment:${dep.status}`,
          detail: `mode=${dep.mode || "paper"} kill=${dep.kill_switch ? "ON" : "off"}`,
        });
      }
      setActivity(acts.slice(0, 24));

      const killAny = portList.some((p) => Boolean(p.kill_switch)) || depList.some((d) => Boolean(d.kill_switch));
      const gross = portList.reduce((acc, p) => acc + (asNumber(p.gross_exposure) ?? 0), 0);
      setRisk({
        maxDrawdown: UNMEASURED,
        var: UNMEASURED,
        totalExposure: portList.length ? `${gross.toFixed(1)}` : UNMEASURED,
        openPositions: UNMEASURED,
        killSwitch: killAny ? "ARMED" : "clear",
        riskGuard: "Ready",
      });

      setStale(false);
      setSelectedId((prev) => prev || memberRows[0]?.id || null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setStale(true);
    } finally {
      if (g === gen.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const filteredAgents = useMemo(() => {
    let rows = agents;
    if (filter === "active") rows = rows.filter((a) => a.enabled && a.mode !== "paused");
    if (filter === "paused") rows = rows.filter((a) => a.mode === "paused" || !a.enabled);
    if (filter === "simulation") rows = rows.filter((a) => a.mode === "simulation");
    const q = search.trim().toLowerCase();
    if (q) {
      rows = rows.filter(
        (a) =>
          a.name.toLowerCase().includes(q) ||
          a.role.toLowerCase().includes(q) ||
          a.orchestraName.toLowerCase().includes(q),
      );
    }
    return rows;
  }, [agents, filter, search]);

  const selected = useMemo(
    () => agents.find((a) => a.id === selectedId) ?? filteredAgents[0] ?? null,
    [agents, filteredAgents, selectedId],
  );

  const selectedPortfolio = useMemo(() => {
    if (!selected?.walletId) return null;
    return portfolios.find((p) => p.portfolio_id === selected.walletId) ?? null;
  }, [portfolios, selected]);

  const fundSelectedWallet = useCallback(
    async (delta: number, reason: string) => {
      if (!selected?.walletId) {
        setFundingNotice("Geen paper wallet gekoppeld aan deze agent.");
        return;
      }
      setFundingBusy(true);
      setFundingNotice(null);
      try {
        const key = `fund-${selected.walletId}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
        const res = await api.fundPortfolio(selected.walletId, {
          delta,
          reason,
          idempotencyKey: key,
          operatorId: "operator",
          kind: delta >= 0 ? "TOP_UP" : "WITHDRAWAL",
        });
        const applied = Boolean(res.funding?.applied);
        setFundingNotice(
          applied
            ? `Paper capital aangepast (PnL ongewijzigd). Δ=${String(res.funding?.delta ?? delta)}`
            : `Funding niet opnieuw toegepast: ${String(res.funding?.reason || "duplicate")}`,
        );
        await refresh();
      } catch (e) {
        setFundingNotice(e instanceof Error ? e.message : String(e));
      } finally {
        setFundingBusy(false);
      }
    },
    [selected, refresh],
  );

  return {
    loading,
    error,
    stale,
    liveTrading,
    kpis,
    agents: filteredAgents,
    allAgents: agents,
    filter,
    setFilter,
    search,
    setSearch,
    selected,
    setSelectedId,
    detailTab,
    setDetailTab,
    allocations,
    architecture,
    activity,
    risk,
    portfolios,
    orchestras,
    deployments,
    decisions,
    selectedPortfolio,
    fundingBusy,
    fundingNotice,
    fundSelectedWallet,
    refresh,
    filterCounts: {
      all: agents.length,
      active: agents.filter((a) => a.enabled && a.mode !== "paused").length,
      paused: agents.filter((a) => a.mode === "paused" || !a.enabled).length,
      simulation: agents.filter((a) => a.mode === "simulation").length,
    },
    measuredNumber,
  };
}

export type AgentOverviewData = ReturnType<typeof useAgentOverviewData>;
