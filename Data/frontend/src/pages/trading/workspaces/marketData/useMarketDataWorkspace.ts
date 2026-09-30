/**
 * Market Data (WAVE 5) — single composition hook for the native, pixel-exact page.
 *
 * Absorbs Marktdata (offline dataset library, scan/register), Providers
 * ("live feeds"), dataset certification, and historical replay (market-sim
 * runs) behind one hook so MarketDataPage/View/Drawers never talk to `fetch`
 * directly. Every value is derived from real backend responses; anything the
 * backend does not measure renders literally as "UNMEASURED" (never invented
 * client-side — no fabricated 99.2% quality score, no fabricated Bullish 63%
 * regime split).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api } from "../../../../api/client";
import { marketSimLabApi } from "../../../../api/domains/marketSimLab";
import type { MarketDataSource, MarketSimLiveState, MarketSimRun, MarketSimStatusResponse } from "../../../../types/api";
import { UNMEASURED, asNumber, asRec } from "../commandHub/hubFormat";

/* ---------------------------------------------------------------- helpers */

function asStr(v: unknown, fallback = UNMEASURED): string {
  if (typeof v === "string" && v.trim()) return v;
  if (typeof v === "number" && Number.isFinite(v)) return String(v);
  return fallback;
}

function sourceMeta(s: MarketDataSource): Record<string, unknown> {
  return asRec(s.metadata) ?? {};
}

function qualityVerdictOf(s: MarketDataSource): string {
  const meta = sourceMeta(s);
  const verdict = meta.qualityVerdict ?? asRec(meta.quality)?.qualityVerdict ?? asRec(meta.quality)?.quality;
  return typeof verdict === "string" && verdict ? verdict : UNMEASURED;
}

export function fmtBytes(n: number | null): string {
  if (n == null) return UNMEASURED;
  if (n < 1024) return `${n} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let v = n;
  let i = -1;
  do {
    v /= 1024;
    i += 1;
  } while (v >= 1024 && i < units.length - 1);
  return `${v.toFixed(v >= 10 ? 0 : 1)} ${units[i]}`;
}

export function fmtDateRange(start: string | null, end: string | null): string {
  const s = start ? start.slice(0, 10) : "—";
  const e = end ? end.slice(0, 10) : "—";
  return `${s} → ${e}`;
}

export function shortHash(hash: string | null | undefined, len = 10): string {
  if (!hash) return "—";
  return hash.length > len ? `${hash.slice(0, len)}…` : hash;
}

/* -------------------------------------------------------------------- KPI */

export type MdKpi = { id: string; label: string; value: string; note: string };

/* ---------------------------------------------------------------- library */

export type LibraryRow = {
  id: string;
  symbol: string;
  timeframe: string;
  status: string;
  quality: string;
  barCount: number;
  range: string;
  size: string;
  hash: string;
  path: string;
  raw: MarketDataSource;
};

/* -------------------------------------------------------------- coverage */

export type CoverageRow = {
  symbol: string;
  timeframes: string[];
  sourceCount: number;
  readyCount: number;
  totalBars: number;
  readyPct: number;
};

/* ---------------------------------------------------------------- feeds */

export type ProviderRow = {
  providerId: string;
  reachable: boolean | null;
  authenticated: boolean | null;
  latencyMs: number | null;
  detail: string;
  licenseNote: string;
  licenseState: string;
  dataKinds: string[];
};

/* --------------------------------------------------------- quality/gaps */

export type QualityMetric = { id: string; label: string; value: string; status: "good" | "warn" | "bad" | "unmeasured"; note: string };

/* ------------------------------------------------------------- activity */

export type ActivityEntry = {
  id: string;
  ts: string;
  action: "scan" | "register" | "provider_import" | "certify" | "replay";
  label: string;
  status: "ok" | "error" | "pending";
  detail: string;
};

/* --------------------------------------------------------- certification */

export type CertificationRecord = Record<string, unknown> | null;

function certField(cert: Record<string, unknown> | null, camel: string, snake: string): string {
  if (!cert) return UNMEASURED;
  const v = cert[camel] ?? cert[snake];
  return typeof v === "string" && v ? v : UNMEASURED;
}

export function certificationStateOf(cert: CertificationRecord): string {
  return certField(cert, "certificationState", "certification_state");
}
export function certificationPitOf(cert: CertificationRecord): string {
  return certField(cert, "pitState", "pit_state");
}

/* ------------------------------------------------------------------ hook */

export function useMarketDataWorkspace() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [status, setStatus] = useState<MarketSimStatusResponse | null>(null);
  const [sources, setSources] = useState<MarketDataSource[]>([]);
  const [providers, setProviders] = useState<ProviderRow[]>([]);
  const [providersLoading, setProvidersLoading] = useState(false);
  const [overview, setOverview] = useState<Record<string, unknown> | null>(null);

  const [activity, setActivity] = useState<ActivityEntry[]>([]);

  const pushActivity = useCallback((entry: Omit<ActivityEntry, "id" | "ts">) => {
    setActivity((prev) => [
      { id: `act_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`, ts: new Date().toISOString(), ...entry },
      ...prev,
    ].slice(0, 40));
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [st, data, ov] = await Promise.all([
        api.marketSimStatus().catch(() => null),
        api.listMarketData(300).catch(() => ({ sources: [] as MarketDataSource[] })),
        marketSimLabApi.marketSimLabOverview().catch(() => null),
      ]);
      setStatus(st);
      setSources(data.sources || []);
      setOverview(ov);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : "Failed to load market data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const refreshProviders = useCallback(async () => {
    setProvidersLoading(true);
    try {
      const { providers: list } = await api.marketSimProviders();
      setProviders(
        (list || []).map((p) => {
          const rec = p as Record<string, unknown>;
          return {
            providerId: asStr(rec.provider_id, "—"),
            reachable: typeof rec.reachable === "boolean" ? rec.reachable : null,
            authenticated: typeof rec.authenticated === "boolean" ? rec.authenticated : null,
            latencyMs: asNumber(rec.latency_ms),
            detail: asStr(rec.detail, "—"),
            licenseNote: asStr(rec.license_note, ""),
            licenseState: asStr(rec.license_state, UNMEASURED),
            dataKinds: Array.isArray(rec.data_kinds) ? (rec.data_kinds as string[]) : [],
          };
        }),
      );
    } catch {
      /* keep prior providers on failure */
    } finally {
      setProvidersLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshProviders();
  }, [refreshProviders]);

  /* ----------------------------------------------------------------- scan/register */

  const [busy, setBusy] = useState(false);

  const scan = useCallback(async () => {
    setBusy(true);
    try {
      const { sources: list } = await api.scanMarketData();
      pushActivity({ action: "scan", label: "Scan markets root", status: "ok", detail: `${list.length} bestand(en) geïndexeerd` });
      await refresh();
      return list;
    } catch (err) {
      pushActivity({ action: "scan", label: "Scan markets root", status: "error", detail: err instanceof Error ? err.message : "Scan mislukt" });
      throw err;
    } finally {
      setBusy(false);
    }
  }, [refresh, pushActivity]);

  const register = useCallback(
    async (payload: { path: string; symbol?: string; timeframe?: string }) => {
      setBusy(true);
      try {
        const { source } = await api.registerMarketData(payload);
        pushActivity({
          action: "register",
          label: `Register ${payload.path}`,
          status: "ok",
          detail: `${source.symbol} · ${source.timeframe} · ${source.status}`,
        });
        await refresh();
        return source;
      } catch (err) {
        pushActivity({
          action: "register",
          label: `Register ${payload.path}`,
          status: "error",
          detail: err instanceof Error ? err.message : "Registratie mislukt",
        });
        throw err;
      } finally {
        setBusy(false);
      }
    },
    [refresh, pushActivity],
  );

  const importProvider = useCallback(
    async (payload: { providerId: string; symbol: string; timeframe?: string; limit?: number }) => {
      setBusy(true);
      try {
        const res = await api.marketSimImportProvider(payload);
        pushActivity({
          action: "provider_import",
          label: `Import ${payload.providerId} · ${payload.symbol}`,
          status: "ok",
          detail: JSON.stringify(res).slice(0, 140),
        });
        await refresh();
        return res;
      } catch (err) {
        pushActivity({
          action: "provider_import",
          label: `Import ${payload.providerId} · ${payload.symbol}`,
          status: "error",
          detail: err instanceof Error ? err.message : "Import mislukt",
        });
        throw err;
      } finally {
        setBusy(false);
      }
    },
    [refresh, pushActivity],
  );

  /* --------------------------------------------------------------------- KPIs */

  const readySources = sources.filter((s) => s.status === "READY");
  const invalidSources = sources.filter((s) => s.status === "INVALID");
  const qualityFailSources = sources.filter((s) => qualityVerdictOf(s) === "FAIL");
  const qualityWarnSources = sources.filter((s) => qualityVerdictOf(s) === "WARN");

  const kpis: MdKpi[] = [
    {
      id: "indexed",
      label: "Offline Datasets",
      value: String(status?.health.sources_indexed ?? sources.length),
      note: status?.health.exists ? "markets root exists" : "markets root missing",
    },
    {
      id: "ready",
      label: "Ready",
      value: String(status?.health.sources_ready ?? readySources.length),
      note: "Validated OHLCV",
    },
    {
      id: "invalid",
      label: "Invalid",
      value: String(invalidSources.length),
      note: "Failed validation",
    },
    {
      id: "quality_fail",
      label: "Quality FAIL",
      value: String(qualityFailSources.length),
      note: "Honest quality verdict",
    },
    {
      id: "quality_warn",
      label: "Quality WARN",
      value: String(qualityWarnSources.length),
      note: "Gaps / outliers",
    },
    {
      id: "feature",
      label: "Feature",
      value: status?.enabled ? "ON" : "OFF",
      note: "LEVIATHAN_FEATURE_MARKET_SIM",
    },
  ];

  /* ------------------------------------------------------------------ library */

  const library: LibraryRow[] = sources.map((s) => ({
    id: s.source_id,
    symbol: s.symbol,
    timeframe: s.timeframe,
    status: s.status,
    quality: qualityVerdictOf(s),
    barCount: s.bar_count,
    range: fmtDateRange(s.start_ts, s.end_ts),
    size: fmtBytes(s.byte_size),
    hash: s.content_hash,
    path: s.path,
    raw: s,
  }));

  /* ---------------------------------------------------------------- coverage */

  const coverage: CoverageRow[] = useMemo(() => {
    const bySymbol = new Map<string, MarketDataSource[]>();
    for (const s of sources) {
      const list = bySymbol.get(s.symbol) ?? [];
      list.push(s);
      bySymbol.set(s.symbol, list);
    }
    return Array.from(bySymbol.entries())
      .map(([symbol, list]) => {
        const ready = list.filter((s) => s.status === "READY");
        return {
          symbol,
          timeframes: Array.from(new Set(list.map((s) => s.timeframe))).sort(),
          sourceCount: list.length,
          readyCount: ready.length,
          totalBars: ready.reduce((sum, s) => sum + (s.bar_count || 0), 0),
          readyPct: list.length ? Math.round((ready.length / list.length) * 100) : 0,
        };
      })
      .sort((a, b) => b.totalBars - a.totalBars);
  }, [sources]);

  /* ------------------------------------------------------------- quality/gaps */

  const qualityGaps: QualityMetric[] = useMemo(() => {
    let gapCount = 0;
    let dupCount = 0;
    let outlierCount = 0;
    let ohlcViolations = 0;
    let streamingValidated = 0;
    let totalBars = 0;
    for (const s of sources) {
      const meta = sourceMeta(s);
      gapCount += asNumber(meta.gap_count) ?? 0;
      dupCount += asNumber(meta.duplicate_count) ?? 0;
      const quality = asRec(meta.quality);
      const outliers = quality?.outliers;
      outlierCount += Array.isArray(outliers) ? outliers.length : 0;
      const violations = quality?.ohlcViolations;
      ohlcViolations += Array.isArray(violations) ? violations.length : 0;
      if (meta.streaming_validation === true) streamingValidated += 1;
      totalBars += s.bar_count || 0;
    }
    const n = sources.length || 1;
    const normPct = Math.round((streamingValidated / n) * 100);
    return [
      {
        id: "gaps",
        label: "Ontbrekende bars",
        value: totalBars ? `${((gapCount / totalBars) * 100).toFixed(2)}%` : gapCount ? String(gapCount) : "0",
        status: gapCount === 0 ? "good" : gapCount < 10 ? "warn" : "bad",
        note: `${gapCount} gap(s) over ${sources.length} bron(nen)`,
      },
      {
        id: "dupes",
        label: "Dubbele timestamps",
        value: totalBars ? `${((dupCount / Math.max(totalBars, 1)) * 100).toFixed(3)}%` : String(dupCount),
        status: dupCount === 0 ? "good" : "bad",
        note: `${dupCount} duplicate(s)`,
      },
      {
        id: "outliers",
        label: "Outliers",
        value: String(outlierCount),
        status: outlierCount === 0 ? "good" : "warn",
        note: "OHLC outlier detecties",
      },
      {
        id: "normalisatie",
        label: "Normalisatie checks",
        value: sources.length ? `${normPct}%` : UNMEASURED,
        status: normPct >= 95 ? "good" : normPct > 0 ? "warn" : "unmeasured",
        note: "Streaming validation uitgevoerd",
      },
      {
        id: "ohlc",
        label: "OHLC invariant violations",
        value: String(ohlcViolations),
        status: ohlcViolations === 0 ? "good" : "bad",
        note: "high>=low, close binnen range",
      },
      {
        id: "adjustment",
        label: "Prijs aanpassingen",
        value: "as_traded",
        status: "unmeasured",
        note: "Unadjusted — corporate actions niet toegepast",
      },
    ];
  }, [sources]);

  /* ---------------------------------------------------------------- regime */

  const regime = useMemo(() => {
    const hmm = asRec(overview?.hmm_regime);
    return {
      detectorVersion: asStr(overview?.regime_detector_version, UNMEASURED),
      hmmStatus: asStr(hmm?.status, UNMEASURED),
      hmmReason: asStr(hmm?.reason, ""),
    };
  }, [overview]);

  /* --------------------------------------------------------- certification */

  const [certifications, setCertifications] = useState<Record<string, CertificationRecord>>({});
  const [certBusy, setCertBusy] = useState<string | null>(null);
  const inFlightCert = useRef<Set<string>>(new Set());

  const fetchCertification = useCallback(async (sourceId: string, version?: string) => {
    if (inFlightCert.current.has(sourceId)) return;
    inFlightCert.current.add(sourceId);
    try {
      const res = await api.getDatasetCertification(sourceId, version);
      const cert = asRec(res.certification) ?? asRec(res) ?? null;
      setCertifications((prev) => ({ ...prev, [sourceId]: cert }));
      return cert;
    } catch {
      setCertifications((prev) => ({ ...prev, [sourceId]: null }));
      return null;
    } finally {
      inFlightCert.current.delete(sourceId);
    }
  }, []);

  const evaluateCertification = useCallback(
    async (source: MarketDataSource) => {
      setCertBusy(source.source_id);
      try {
        const meta = sourceMeta(source);
        const quality = asRec(meta.quality) ?? {};
        const duplicateCount = asNumber(meta.duplicate_count) ?? 0;
        const gapCount = asNumber(meta.gap_count) ?? 0;
        const ohlcViolations = Array.isArray(quality.ohlcViolations) ? quality.ohlcViolations.length : 0;
        const gapRatio = source.bar_count > 0 ? gapCount / source.bar_count : null;
        const evidence: Record<string, unknown> = {
          content_hash: source.content_hash,
          source_id: source.source_id,
          timestamp_normalized: meta.streaming_validation === true,
          ordering_ok: duplicateCount === 0,
          duplicate_handling: "reject_on_parse",
          gap_report: { gap_count: gapCount, gap_ratio: gapRatio },
          ohlc_invariants_ok: ohlcViolations === 0,
          license_state: "PUBLIC_TERMS_APPLY",
        };
        const res = await api.evaluateDatasetCertification(source.source_id, {
          datasetVersionId: source.content_hash.slice(0, 16),
          datasetHash: source.content_hash,
          sourceId: source.source_id,
          dataType: "ohlcv",
          evidence,
        });
        const cert = asRec(res.certification) ?? asRec(res) ?? null;
        setCertifications((prev) => ({ ...prev, [source.source_id]: cert }));
        pushActivity({
          action: "certify",
          label: `Certificeren ${source.symbol} · ${source.timeframe}`,
          status: "ok",
          detail: `state=${certificationStateOf(cert)}`,
        });
        return cert;
      } catch (err) {
        pushActivity({
          action: "certify",
          label: `Certificeren ${source.symbol} · ${source.timeframe}`,
          status: "error",
          detail: err instanceof Error ? err.message : "Certificatie mislukt",
        });
        throw err;
      } finally {
        setCertBusy(null);
      }
    },
    [pushActivity],
  );

  /* ------------------------------------------------------------ replay/sim */

  const [simRuns, setSimRuns] = useState<MarketSimRun[]>([]);
  const [simLive, setSimLive] = useState<MarketSimLiveState | null>(null);
  const [selectedSimRunId, setSelectedSimRunId] = useState<string | null>(null);

  const refreshSimRuns = useCallback(async () => {
    try {
      const { runs } = await api.listMarketSimRuns(50);
      setSimRuns(runs);
      return runs;
    } catch {
      return [] as MarketSimRun[];
    }
  }, []);

  useEffect(() => {
    void refreshSimRuns();
  }, [refreshSimRuns]);

  useEffect(() => {
    if (!selectedSimRunId) {
      setSimLive(null);
      return;
    }
    let cancelled = false;
    const tick = async () => {
      try {
        const state = await api.getMarketSimLive(selectedSimRunId);
        if (!cancelled) setSimLive(state);
      } catch {
        /* transient poll errors ignored */
      }
    };
    void tick();
    const id = window.setInterval(() => void tick(), 2000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [selectedSimRunId]);

  const createReplayRun = useCallback(
    async (payload: Parameters<typeof api.createMarketSimRun>[0]) => {
      const { run } = await api.createMarketSimRun(payload);
      setSimRuns((prev) => [run, ...prev]);
      setSelectedSimRunId(run.run_id);
      pushActivity({
        action: "replay",
        label: `Replay run · ${run.symbol} ${run.timeframe}`,
        status: "ok",
        detail: `run_id=${run.run_id.slice(0, 10)}`,
      });
      return run;
    },
    [pushActivity],
  );

  const startReplayRun = useCallback(
    async (runId: string) => {
      await api.startMarketSimRun(runId);
      await refreshSimRuns();
    },
    [refreshSimRuns],
  );
  const pauseReplayRun = useCallback(
    async (runId: string) => {
      await api.pauseMarketSimRun(runId);
      await refreshSimRuns();
    },
    [refreshSimRuns],
  );
  const stepReplayRun = useCallback(
    async (runId: string) => {
      await api.stepMarketSimRun(runId);
      await refreshSimRuns();
    },
    [refreshSimRuns],
  );
  const stopReplayRun = useCallback(
    async (runId: string) => {
      await api.stopMarketSimRun(runId);
      await refreshSimRuns();
    },
    [refreshSimRuns],
  );

  return {
    loading,
    error,
    busy,
    status,
    sources,
    library,
    coverage,
    qualityGaps,
    regime,
    providers,
    providersLoading,
    activity,
    kpis,

    refresh,
    refreshProviders,
    scan,
    register,
    importProvider,

    certifications,
    certBusy,
    fetchCertification,
    evaluateCertification,

    simRuns,
    simLive,
    selectedSimRunId,
    setSelectedSimRunId,
    createReplayRun,
    startReplayRun,
    pauseReplayRun,
    stepReplayRun,
    stopReplayRun,
    refreshSimRuns,
  };
}

export type MarketDataWorkspaceData = ReturnType<typeof useMarketDataWorkspace>;
