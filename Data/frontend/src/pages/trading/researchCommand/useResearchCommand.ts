import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../../../api/client";
import type { ResearchCommandSnapshot } from "../../../types/researchCommand";
import { parseUniverse, TRADING_MISSION_KINDS } from "../../agents/tradingHelpers";

const POLL_MS = 8000;

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function useResearchCommand() {
  const navigate = useNavigate();
  const [orchestraId, setOrchestraId] = useState<string | null>(null);
  const [portfolioId, setPortfolioId] = useState<string | null>(null);
  const [labId, setLabId] = useState<string | null>(null);
  const [asOf, setAsOf] = useState("");
  const [snapshot, setSnapshot] = useState<ResearchCommandSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [feedOpen, setFeedOpen] = useState(false);
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const [flattenOpen, setFlattenOpen] = useState(false);
  const [watchTab, setWatchTab] = useState<"watchlist" | "opportunities" | "volatility" | "news">("watchlist");
  const [positionTab, setPositionTab] = useState<"open" | "closed">("open");
  const [missionKind, setMissionKind] = useState<string>(TRADING_MISSION_KINDS[0].kind);
  const [missionAsOf, setMissionAsOf] = useState("");
  const [createName, setCreateName] = useState("");
  const [createUniverse, setCreateUniverse] = useState("BTCUSD");
  const [createCapital, setCreateCapital] = useState("100000");
  const [feedName, setFeedName] = useState("");
  const [feedUrl, setFeedUrl] = useState("");
  const [latency, setLatency] = useState("0");
  const [license, setLicense] = useState("UNKNOWN");
  const [watchSymbol, setWatchSymbol] = useState("");
  const [watchReason, setWatchReason] = useState("");

  const abortRef = useRef<AbortController | null>(null);
  const seq = useRef(0);
  const effectiveOrchestraId = orchestraId ?? snapshot?.catalogs.orchestras[0]?.orchestraId ?? "";
  const effectivePortfolioId =
    portfolioId ?? snapshot?.session.portfolioId ?? snapshot?.catalogs.portfolios[0]?.portfolioId ?? "";
  const effectiveLabId = labId ?? snapshot?.session.labId ?? "";

  const refresh = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const token = ++seq.current;
    try {
      const next = await api.researchCommandSnapshot(
        {
          orchestraId: effectiveOrchestraId || undefined,
          portfolioId: effectivePortfolioId || undefined,
          labId: effectiveLabId || undefined,
          asOf: asOf.trim() || undefined,
        },
        { signal: controller.signal },
      );
      if (token !== seq.current) return;
      setSnapshot(next);
      setError(null);
    } catch (err) {
      if (token !== seq.current || controller.signal.aborted) return;
      setError(messageOf(err));
    } finally {
      if (token === seq.current) setLoading(false);
    }
  }, [asOf, effectiveLabId, effectiveOrchestraId, effectivePortfolioId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.visibilityState === "hidden") return;
      void refresh();
    }, POLL_MS);
    return () => {
      window.clearInterval(timer);
      abortRef.current?.abort();
    };
  }, [refresh]);

  const run = useCallback(
    async (key: string, work: () => Promise<void>) => {
      setBusy(key);
      setNotice(null);
      try {
        await work();
        await refresh();
      } catch (err) {
        setError(messageOf(err));
      } finally {
        setBusy(null);
      }
    },
    [refresh],
  );

  const startSession = () =>
    run("start", async () => {
      if (!effectiveOrchestraId || !effectivePortfolioId) return;
      await api.researchCommandStart({
        orchestraId: effectiveOrchestraId,
        portfolioId: effectivePortfolioId,
        labId: effectiveLabId || undefined,
      });
    });

  const pauseSession = () =>
    run("pause", async () => {
      await api.researchCommandPause({
        sessionId: snapshot?.selection.sessionId,
        orchestraId: effectiveOrchestraId,
      });
    });

  const confirmFlatten = () =>
    run("flatten", async () => {
      const sessionId = snapshot?.selection.sessionId;
      if (!sessionId) return;
      await api.researchCommandFlatten({ sessionId, confirm: "FLATTEN_PAPER" });
      setFlattenOpen(false);
    });

  const armKillSwitch = () =>
    run("kill", async () => {
      const sessionId = snapshot?.selection.sessionId;
      if (!sessionId) return;
      await api.researchCommandKill({ sessionId, armed: true });
    });

  const evolve = () =>
    run("evolve", async () => {
      if (!effectiveLabId) return;
      await api.researchCommandEvolve({ labId: effectiveLabId });
    });

  const launchMission = () =>
    run("mission", async () => {
      if (!effectiveOrchestraId) return;
      const result = await api.launchTradeMission(effectiveOrchestraId, {
        kind: missionKind,
        asOf: missionAsOf.trim() || undefined,
      });
      setNotice(`${result.mission.missionId} · ${result.mission.status}`);
    });

  const createOrchestra = () =>
    run("create-orchestra", async () => {
      if (!createName.trim()) return;
      const { orchestra } = await api.createTradeOrchestra({
        name: createName.trim(),
        mandate: {
          universe: parseUniverse(createUniverse),
          paperCapital: Number(createCapital) || 100000,
        },
      });
      setCreateName("");
      setOrchestraId(orchestra.orchestraId);
    });

  const addWatch = () =>
    run("watch", async () => {
      const sessionId = snapshot?.selection.sessionId;
      if (!sessionId || !watchSymbol.trim() || !watchReason.trim()) return;
      await api.researchCommandWatch({
        sessionId,
        symbol: watchSymbol.trim(),
        reason: watchReason.trim(),
      });
      setWatchSymbol("");
      setWatchReason("");
    });

  const addFeed = () =>
    run("feed-create", async () => {
      if (!feedName.trim() || !feedUrl.trim()) return;
      await api.createTradingNewsFeed({
        name: feedName.trim(),
        url: feedUrl.trim(),
        declaredLatencySeconds: Number(latency) || 0,
        licenseState: license,
      });
      setFeedName("");
      setFeedUrl("");
    });

  const pollFeeds = (feedId?: string) =>
    run(feedId ? `poll:${feedId}` : "poll-all", async () => {
      const res = await api.pollTradingNews(feedId);
      setNotice(
        `${String(res.status)} · via ${String(res.executedVia ?? "?")}${
          res.inserted !== undefined ? ` · ${String(res.inserted)} new` : ""
        }`,
      );
    });

  const toggleFeed = (feedId: string, enabled: boolean) =>
    run(`feed:${feedId}`, async () => {
      await api.updateTradingNewsFeed(feedId, { enabled: !enabled });
    });

  const removeFeed = (feedId: string) =>
    run(`feed-delete:${feedId}`, async () => {
      await api.deleteTradingNewsFeed(feedId);
    });

  return {
    snapshot,
    loading,
    error,
    busy,
    notice,
    orchestraId: effectiveOrchestraId,
    portfolioId: effectivePortfolioId,
    labId: effectiveLabId,
    asOf,
    feedOpen,
    evidenceOpen,
    flattenOpen,
    watchTab,
    positionTab,
    missionKind,
    missionAsOf,
    createName,
    createUniverse,
    createCapital,
    feedName,
    feedUrl,
    latency,
    license,
    watchSymbol,
    watchReason,
    setOrchestraId,
    setPortfolioId,
    setLabId,
    setAsOf,
    setFeedOpen,
    setEvidenceOpen,
    setFlattenOpen,
    setWatchTab,
    setPositionTab,
    setMissionKind,
    setMissionAsOf,
    setCreateName,
    setCreateUniverse,
    setCreateCapital,
    setFeedName,
    setFeedUrl,
    setLatency,
    setLicense,
    setWatchSymbol,
    setWatchReason,
    refresh,
    startSession,
    pauseSession,
    confirmFlatten,
    armKillSwitch,
    evolve,
    launchMission,
    createOrchestra,
    addWatch,
    addFeed,
    pollFeeds,
    toggleFeed,
    removeFeed,
    openPaper: () => navigate("/trading/paper"),
    openAgent: (agentId: string) => navigate(`/agents?agent=${encodeURIComponent(agentId)}`),
    dismissError: () => setError(null),
  };
}
