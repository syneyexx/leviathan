import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../../../../api/client";
import { marketSimLabApi } from "../../../../api/domains/marketSimLab";
import { researchCommandApi } from "../../../../api/domains/researchCommand";
import type { ResearchCommandSnapshot } from "../../../../types/researchCommand";
import type {
  MarketSimCapabilities,
  MarketSimPaperDeployment,
  PaperPortfolio,
  TradeOrchestraMember,
} from "../../../../types/api";
import {
  UNMEASURED,
  asNumber,
  asRec,
  fmtClock,
  fmtInt,
  fmtPct,
  fmtUsd,
  measuredNumber,
  shortId,
} from "./hubFormat";
import type {
  CommandHubData,
  HubAgentRow,
  HubAttentionRow,
  HubCapability,
  HubKpiCard,
  HubMarketPanel,
  HubQueueRow,
  HubSessionRow,
  HubSourceRow,
  HubTone,
  HubWatchRow,
} from "./hubTypes";

function flatSpark(value: number, len = 8): number[] {
  const v = Number.isFinite(value) ? value : 0;
  return new Array(len).fill(v);
}

function toneForHealth(health: string | null | undefined): HubTone {
  const h = String(health || "").toLowerCase();
  if (h === "busy" || h === "active" || h === "running") return "green";
  if (h === "error" || h === "failed") return "red";
  if (h === "disabled" || h === "archived") return "muted";
  return "blue";
}

function toneForStatus(status: string | null | undefined): HubTone {
  const s = String(status || "").toUpperCase();
  if (["RUNNING", "ACTIVE", "READY", "ONLINE", "QUALIFIED", "ACCEPTED", "FILLED"].includes(s)) return "green";
  if (["BLOCKED", "ERROR", "FAILED", "REJECTED", "KILLED"].includes(s)) return "red";
  if (["PENDING", "SHADOW", "AWAITING_PROMOTION", "PAUSED", "DRAFT"].includes(s)) return "gold";
  if (["ARCHIVED", "STOPPED", "CANCELLED", "DISABLED"].includes(s)) return "muted";
  return "blue";
}

function priorityFromLevel(level: "Hoog" | "Medium" | "Laag"): "Hoog" | "Medium" | "Laag" {
  return level;
}

async function safe<T>(fn: () => Promise<T>, fallback: T): Promise<T> {
  try {
    return await fn();
  } catch {
    return fallback;
  }
}

export function useCommandHubData(market: string, timeframe: string): CommandHubData {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [liveTrading, setLiveTrading] = useState("BLOCKED");
  const [capabilities, setCapabilities] = useState<HubCapability[]>([]);
  const [kpis, setKpis] = useState<HubKpiCard[]>([]);
  const [agents, setAgents] = useState<HubAgentRow[]>([]);
  const [market_, setMarketPanel] = useState<HubMarketPanel>({
    symbol: market,
    price: UNMEASURED,
    change: UNMEASURED,
    changeTone: "muted",
    spark: [],
    volatility: UNMEASURED,
    volatilityTone: "muted",
    liquidity: UNMEASURED,
    funding: UNMEASURED,
    regime: UNMEASURED,
    regimeTone: "muted",
    measured: false,
  });
  const [sources, setSources] = useState<HubSourceRow[]>([]);
  const [sourcesOnline, setSourcesOnline] = useState(0);
  const [paperSessions, setPaperSessions] = useState<HubSessionRow[]>([]);
  const [researchSessions, setResearchSessions] = useState<HubSessionRow[]>([]);
  const [watching, setWatching] = useState<HubWatchRow[]>([]);
  const [attention, setAttention] = useState<HubAttentionRow[]>([]);
  const [queue, setQueue] = useState<HubQueueRow[]>([]);

  const marketRef = useRef(market);
  const timeframeRef = useRef(timeframe);
  marketRef.current = market;
  timeframeRef.current = timeframe;

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [
        overview,
        labsResp,
        portfoliosResp,
        deploymentsResp,
        sourcesResp,
        caps,
        live,
        status,
        rcRaw,
        orchestrasResp,
        bars,
      ] = await Promise.all([
        safe(() => marketSimLabApi.marketSimLabOverview(), {} as Record<string, unknown>),
        safe(() => marketSimLabApi.marketSimLabListRuns(50), { labs: [] as Record<string, unknown>[] }),
        safe(() => api.listPortfolios(50), { portfolios: [] as PaperPortfolio[] }),
        safe(
          () => api.listPaperDeployments({ limit: 50 }),
          { deployments: [] as MarketSimPaperDeployment[], truth: {} },
        ),
        safe(() => api.listMarketData(200), { sources: [] as import("../../../../types/api").MarketDataSource[] }),
        safe(() => api.marketSimCapabilities(), null as MarketSimCapabilities | null),
        safe(() => api.marketSimLiveTradingStatus(), { LIVE_TRADING_AVAILABLE: "BLOCKED" } as Record<string, unknown>),
        safe(() => api.marketSimStatus(), null),
        safe(() => researchCommandApi.researchCommandSnapshot(), null as ResearchCommandSnapshot | null),
        safe(() => api.listTradeOrchestras(false), { orchestras: [] }),
        safe(
          () => api.fetchMarketBars({ symbol: marketRef.current, timeframe: timeframeRef.current, limit: 60 }),
          null,
        ),
      ]);

      const liveAvail = String(
        (live as { LIVE_TRADING_AVAILABLE?: string })?.LIVE_TRADING_AVAILABLE ??
          caps?.live_trading_default ??
          "BLOCKED",
      );
      setLiveTrading(liveAvail);

      // ---- Capabilities badges ----
      const capRows: HubCapability[] = [
        {
          id: "paper-only",
          label: "Paper Only",
          sub: "Veilig en risicoloos",
          tone: "green",
          active: true,
        },
        {
          id: "offline-live",
          label: "Offline + Live Data",
          sub: caps?.binance_public_reachable ? "Historisch en realtime" : "Historisch (offline)",
          tone: "blue",
          active: Boolean(caps?.binance_public_reachable) || Boolean((status as { enabled?: boolean } | null)?.enabled),
        },
        {
          id: "self-learning",
          label: "Zelflerend",
          sub: "Continu verbeteren",
          tone: "purple",
          active: Boolean((overview as { learning_algorithm?: string })?.learning_algorithm),
        },
        {
          id: "risk-guarded",
          label: "Risk Guarded",
          sub: "Meerdere waarborgen",
          tone: "gold",
          active: Boolean(caps?.force_live_blocked ?? true),
        },
      ];
      setCapabilities(capRows);

      // ---- Sources / Databronnen ----
      const srcList = sourcesResp.sources || [];
      const readySrc = srcList.filter((s) => s.status === "READY");
      const sourceRows: HubSourceRow[] = srcList.slice(0, 12).map((s) => {
        const meta = asRec(s.metadata);
        const provider = meta && typeof meta.provider === "string" ? meta.provider : s.kind;
        return {
          id: s.source_id,
          name: `${s.symbol} · ${s.timeframe}`,
          tag: String(provider || s.kind || "dataset"),
          online: s.status === "READY" ? true : s.status === "ERROR" ? false : null,
        };
      });
      setSources(sourceRows);
      setSourcesOnline(readySrc.length);

      // ---- Labs / Active Experimenten ----
      const labList = labsResp.labs || [];
      const activeLabs = labList.filter((l) => {
        const st = String(l.status || l.state || "").toUpperCase();
        return ["RUNNING", "ACTIVE", "LEARNING", "STARTED"].includes(st);
      });

      // ---- Portfolios / Wallets ----
      const portList = portfoliosResp.portfolios || [];
      const equitySum = portList.reduce((acc, p) => acc + (asNumber(p.equity) ?? 0), 0);

      // ---- Deployments / Paper sessions ----
      const depList = deploymentsResp.deployments || [];

      // ---- Research Command snapshot ----
      const rc = rcRaw;

      // ---- Promotion / control queue ----
      const queueRows: HubQueueRow[] = [];
      for (const d of depList) {
        const st = String(d.status || "").toUpperCase();
        const isPending = ["SHADOW", "PENDING_PROMOTION", "AWAITING_PROMOTION", "PENDING"].some((tok) =>
          st.includes(tok),
        );
        if (!isPending) continue;
        queueRows.push({
          id: `deploy-${d.deployment_id}`,
          task: `Promoveer ${shortId(d.strategy_asset_id, 22)}`,
          type: "Promotie",
          agent: d.mode === "shadow" ? "Shadow Executor" : "Executor",
          priority: d.kill_switch ? "Hoog" : "Medium",
          started: "—",
          status: d.status,
          statusTone: toneForStatus(d.status),
        });
      }
      const driftTickets = rc?.paperForward?.driftTickets || [];
      for (const t of driftTickets.slice(0, 8)) {
        queueRows.push({
          id: `drift-${t.ticketId || Math.random()}`,
          task: t.researchQuestion || "Drift review",
          type: "Drift",
          agent: "Research",
          priority: "Medium",
          started: "—",
          status: String(t.status || "OPEN"),
          statusTone: "gold",
        });
      }
      setQueue(queueRows);

      // ---- KPI cards ----
      const trialCount = asNumber((overview as { trial_ledger_count?: number })?.trial_ledger_count) ?? null;
      const readyPct = srcList.length ? Math.round((readySrc.length / srcList.length) * 100) : null;
      const kpiCards: HubKpiCard[] = [
        {
          id: "candidates",
          label: "Candidate Strategieën",
          value: fmtInt(trialCount),
          delta: UNMEASURED,
          deltaTone: "muted",
          tone: "blue",
          spark: flatSpark(trialCount ?? 0),
          sparkKind: "line",
          href: "/trading/strategy-lab?surface=lab",
        },
        {
          id: "experiments",
          label: "Actieve Experimenten",
          value: fmtInt(activeLabs.length),
          delta: UNMEASURED,
          deltaTone: "muted",
          tone: "purple",
          spark: flatSpark(activeLabs.length),
          sparkKind: "line",
          href: "/trading/strategy-lab?surface=lab",
        },
        {
          id: "paper",
          label: "Paper Sessies",
          value: fmtInt(depList.length),
          delta: UNMEASURED,
          deltaTone: "muted",
          tone: "green",
          spark: depList.length
            ? depList.slice(0, 10).map((d) => (String(d.status || "").toUpperCase() === "ACTIVE" ? 1 : 0))
            : flatSpark(0),
          sparkKind: "bars",
          href: "/trading/trading-desk?surface=paper",
        },
        {
          id: "datasets",
          label: "Databronnen",
          value: fmtInt(readySrc.length),
          delta: readyPct == null ? UNMEASURED : `${readyPct}% online`,
          deltaTone: readyPct != null && readyPct >= 90 ? "green" : "muted",
          tone: "gold",
          spark: srcList.length
            ? srcList.slice(0, 12).map((s) => (s.status === "READY" ? 1 : 0))
            : flatSpark(0),
          sparkKind: "bars",
          href: "/trading/market-data",
        },
        {
          id: "wallets",
          label: "Wallets (Paper)",
          value: fmtInt(portList.length),
          delta: fmtUsd(equitySum),
          deltaTone: "muted",
          tone: "green",
          spark: portList.length
            ? portList.slice(0, 10).map((p) => asNumber(p.equity) ?? 0)
            : flatSpark(0),
          sparkKind: "bars",
          href: "/trading/trading-desk?surface=portfolio",
        },
        {
          id: "queue",
          label: "Promotie Queue",
          value: fmtInt(queueRows.length),
          delta: `${queueRows.filter((q) => q.priority === "Hoog").length} urgent`,
          deltaTone: queueRows.some((q) => q.priority === "Hoog") ? "red" : "muted",
          tone: "purple",
          spark: [
            queueRows.filter((q) => q.priority === "Hoog").length,
            queueRows.filter((q) => q.priority === "Medium").length,
            queueRows.filter((q) => q.priority === "Laag").length,
          ],
          sparkKind: "bars",
          href: "#control-room",
        },
      ];
      setKpis(kpiCards);

      // ---- Agents / Active Operations ----
      let memberRows: TradeOrchestraMember[] = [];
      let sessionUniverse: string[] = [];
      if (rc && rc.team.members.length) {
        sessionUniverse = rc.session.universe || [];
        memberRows = rc.team.members.map((m) => ({
          agentId: m.agentId || "",
          name: m.name || m.agentId || "Agent",
          kind: m.kind || "",
          role: m.role || "",
          canonicalRole: m.role || "",
          enabled: m.enabled,
          health: m.health || m.state || "unknown",
        }));
      } else {
        const orchList = orchestrasResp.orchestras || [];
        const first = orchList.find((o) => o.enabled) || orchList[0];
        if (first) {
          const full = await safe(() => api.getTradeOrchestra(first.orchestraId), null);
          memberRows = full?.orchestra.members || [];
        }
      }
      const agentRows: HubAgentRow[] = memberRows.slice(0, 10).map((m) => ({
        id: m.agentId,
        name: m.name,
        status: rc?.team.members.find((x) => x.agentId === m.agentId)?.state || String(m.health || "unknown"),
        statusTone: toneForHealth(m.health),
        task: m.role || m.canonicalRole || "—",
        market: sessionUniverse[0] || marketRef.current,
        workload: null,
      }));
      setAgents(agentRows);

      // ---- Watching / "Wat kijken de agents nu?" ----
      const watchRows: HubWatchRow[] = [];
      if (rc && rc.decisions.length) {
        const byAgent = new Map(memberRows.map((m) => [m.agentId, m.name]));
        for (const d of rc.decisions.slice(0, 6)) {
          const payload = asRec(d.payload) || {};
          watchRows.push({
            id: d.decisionId,
            agent: byAgent.get(d.agentId || "") || d.role || d.agentId || "Agent",
            focus:
              (typeof payload.symbol === "string" && payload.symbol) ||
              sessionUniverse[0] ||
              marketRef.current,
            hypothesis:
              (typeof payload.hypothesis === "string" && payload.hypothesis) ||
              rc.thesis.primary ||
              UNMEASURED,
            finding:
              (typeof payload.summary === "string" && payload.summary) ||
              (typeof payload.finding === "string" && (payload.finding as string)) ||
              d.stage,
            confidence: asNumber(payload.confidence) ?? measuredNumber(rc.thesis.confidence),
            last: fmtClock(d.createdAt || d.asOf || null),
          });
        }
      } else if (rc && rc.watching.watchlist.length) {
        for (const w of rc.watching.watchlist.slice(0, 6)) {
          watchRows.push({
            id: w.symbol,
            agent: "Research Command",
            focus: w.symbol,
            hypothesis: w.why || UNMEASURED,
            finding: w.whySource || UNMEASURED,
            confidence: null,
            last: "—",
          });
        }
      }
      setWatching(watchRows);

      // ---- Market & Regime panel ----
      const barList = bars?.bars || [];
      const closes = barList.map((b) => b.close);
      const lastClose = closes.length ? closes[closes.length - 1] : null;
      const firstClose = closes.length ? closes[0] : null;
      const changePct =
        lastClose != null && firstClose != null && firstClose !== 0
          ? ((lastClose - firstClose) / firstClose) * 100
          : null;
      const watchMatch = rc?.watching.watchlist.find((w) => w.symbol.toUpperCase() === marketRef.current.toUpperCase());
      const volMeasured = measuredNumber(watchMatch?.volatility);
      setMarketPanel({
        symbol: marketRef.current,
        price: lastClose != null ? fmtUsd(lastClose, lastClose < 10 ? 4 : 2) : UNMEASURED,
        change: fmtPct(changePct),
        changeTone: changePct == null ? "muted" : changePct >= 0 ? "green" : "red",
        spark: closes.length ? closes : [],
        volatility: volMeasured != null ? fmtPct(volMeasured) : UNMEASURED,
        volatilityTone: volMeasured == null ? "muted" : volMeasured > 3 ? "red" : "green",
        liquidity: UNMEASURED,
        funding: UNMEASURED,
        regime: UNMEASURED,
        regimeTone: "muted",
        measured: closes.length > 0,
      });

      // ---- Paper & Research sessions tables ----
      const paperRows: HubSessionRow[] = depList.slice(0, 12).map((d) => ({
        id: d.deployment_id,
        name: shortId(d.strategy_asset_id, 18),
        strategy: `v${d.strategy_version}`,
        wallet: shortId(d.session_id, 14),
        market: (d.universe && d.universe[0]) || "—",
        focus: d.mode === "shadow" ? "Shadow" : "Autonomous paper",
        result: UNMEASURED,
        progress: null,
        status: d.status,
        statusTone: toneForStatus(d.status),
      }));
      setPaperSessions(paperRows);

      const researchRows: HubSessionRow[] = labList.slice(0, 12).map((l) => {
        const status = String(l.status || l.state || "UNMEASURED");
        return {
          id: String(l.lab_id || l.id || shortId(l.name)),
          name: String(l.name || shortId(l.lab_id, 18)),
          strategy: String(l.strategy_id || "—"),
          wallet: "—",
          market: String(l.symbol || "Multi"),
          focus: String(l.hypothesis || "Evolution"),
          result: UNMEASURED,
          progress: asNumber(l.progress),
          status,
          statusTone: toneForStatus(status),
        };
      });
      setResearchSessions(researchRows);

      // ---- Attention / Decisions ----
      const attn: HubAttentionRow[] = [];
      if (liveAvail === "BLOCKED") {
        attn.push({
          id: "live-blocked",
          time: fmtClock(new Date().toISOString()),
          type: "Safety",
          message: "LIVE_TRADING_AVAILABLE=BLOCKED — paper / research only",
          priority: priorityFromLevel("Hoog"),
        });
      }
      const blockers = ((overview as { blockers?: unknown[] })?.blockers || []).slice(0, 5);
      for (const [i, b] of blockers.entries()) {
        attn.push({
          id: `blocker-${i}`,
          time: "—",
          type: "Kwalificatie",
          message: String(b),
          priority: "Hoog",
        });
      }
      if (!readySrc.length) {
        attn.push({
          id: "no-data",
          time: "—",
          type: "Data",
          message: "Geen READY databronnen — open Market Data om te scannen",
          priority: "Medium",
        });
      }
      for (const t of driftTickets.slice(0, 4)) {
        attn.push({
          id: `attn-drift-${t.ticketId || Math.random()}`,
          time: "—",
          type: "Research",
          message: t.researchQuestion || t.reason || "Drift ticket open",
          priority: "Medium",
        });
      }
      if (rc?.guardrails.cannotEnableLive) {
        attn.push({
          id: "guard-live",
          time: "—",
          type: "Guardrail",
          message: "Live trading kan niet worden ingeschakeld (mandaat)",
          priority: "Laag",
        });
      }
      if (!attn.length) {
        attn.push({
          id: "ok",
          time: "—",
          type: "Systeem",
          message: "Geen open attention items op dit moment",
          priority: "Laag",
        });
      }
      setAttention(attn);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load Command Hub");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [market, timeframe]);

  return useMemo<CommandHubData>(
    () => ({
      loading,
      error,
      liveTrading,
      capabilities,
      kpis,
      agents,
      market: market_,
      sources,
      sourcesOnline,
      paperSessions,
      researchSessions,
      watching,
      attention,
      queue,
      refresh,
    }),
    [
      loading,
      error,
      liveTrading,
      capabilities,
      kpis,
      agents,
      market_,
      sources,
      sourcesOnline,
      paperSessions,
      researchSessions,
      watching,
      attention,
      queue,
      refresh,
    ],
  );
}
