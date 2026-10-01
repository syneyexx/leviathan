/**
 * Console V2 workspace — ObservabilityHub + product-truth projections.
 * Visual fixture is TEST-ONLY behind window.__LV_V2_VISUAL_FIXTURE__ === 'console'.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../../api/client";
import { useLiveEvents } from "../../hooks/useLiveEvents";
import { useSystemTelemetry } from "../../hooks/useSystemTelemetry";
import {
  consoleOverviewFixture,
  isConsoleVisualFixtureActive,
  liveEventsFixture,
} from "../../mocks/consoleV2VisualFixture";
import type { ConsoleOverviewResponse, RuntimeEvent } from "../../types/api";
import { useAppToast } from "../../state/useAppToast";
import {
  compileSafeRegex,
  CONSOLE_TIME_RANGES,
  eventMatchesQuickFilter,
  eventSearchHaystack,
  hoursForRange,
  normalizeSeverity,
  type ConsoleQuickFilter,
  type ConsoleSeverityChip,
  type ConsoleTimeRange,
} from "./consoleFormat";

const EXPORT_PAGE_LIMIT = 200;
const EXPORT_MAX_PAGES = 10; // hard cap 2000 events

function consoleNowMs(): number {
  if (typeof window !== "undefined") {
    const frozen = (window as Window & { __LV_V2_FROZEN_NOW__?: string }).__LV_V2_FROZEN_NOW__;
    if (frozen) {
      const d = new Date(frozen);
      if (!Number.isNaN(d.getTime())) return d.getTime();
    }
  }
  return Date.now();
}

export function useConsoleWorkspace() {
  const toast = useAppToast();
  const fixture = isConsoleVisualFixtureActive();
  const live = useLiveEvents({ enabled: !fixture, bufferSize: 800 });
  const telemetry = useSystemTelemetry({ enabled: !fixture, intervalMs: 4000 });

  const [overview, setOverview] = useState<ConsoleOverviewResponse | null>(
    fixture ? consoleOverviewFixture() : null,
  );
  const [overviewError, setOverviewError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const [loading, setLoading] = useState(!fixture);
  const [refreshing, setRefreshing] = useState(false);

  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [level, setLevel] = useState<string>("");
  const [service, setService] = useState<string>("");
  const [category, setCategory] = useState<string>("");
  const [severityChip, setSeverityChip] = useState<ConsoleSeverityChip>("all");
  const [quickFilter, setQuickFilter] = useState<ConsoleQuickFilter>(null);
  const [timeRange, setTimeRange] = useState<ConsoleTimeRange>("24h");
  const [autoScroll, setAutoScroll] = useState(true);
  const [regexText, setRegexText] = useState("");
  const [focusSequence, setFocusSequence] = useState<number | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [commandsOpen, setCommandsOpen] = useState(false);
  const [resourcesOpen, setResourcesOpen] = useState(false);
  const [command, setCommand] = useState("");
  const [commands, setCommands] = useState<string[]>([]);
  const [cmdBusy, setCmdBusy] = useState(false);
  const [history, setHistory] = useState<
    Array<{ id: string; time: string; command: string; ok: boolean }>
  >([]);
  const [exportBusy, setExportBusy] = useState(false);

  const loadGen = useRef(0);
  const overviewRef = useRef(overview);
  overviewRef.current = overview;

  useEffect(() => {
    const t = window.setTimeout(() => setDebouncedSearch(search.trim()), 220);
    return () => window.clearTimeout(t);
  }, [search]);

  const regexState = useMemo(() => compileSafeRegex(regexText), [regexText]);

  const loadOverview = useCallback(async () => {
    if (fixture) {
      setOverview(consoleOverviewFixture());
      setOverviewError(null);
      setStale(false);
      setLoading(false);
      return;
    }
    const gen = ++loadGen.current;
    try {
      const data = await api.consoleOverview({
        windowHours: hoursForRange(timeRange),
        bucketCount: 24,
        topLimit: 8,
        recentErrorsLimit: 12,
      });
      if (gen !== loadGen.current) return;
      setOverview(data);
      setOverviewError(null);
      setStale(false);
    } catch (err) {
      if (gen !== loadGen.current) return;
      const msg = err instanceof Error ? err.message : "Console overview unavailable";
      setOverviewError(msg);
      setStale(Boolean(overviewRef.current));
      if (!overviewRef.current) setOverview(null);
    } finally {
      if (gen === loadGen.current) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, [fixture, timeRange]);

  useEffect(() => {
    setLoading(true);
    void loadOverview();
  }, [timeRange]); // eslint-disable-line react-hooks/exhaustive-deps -- intentional reload on range

  useEffect(() => {
    if (fixture) return;
    void api.listOperatorCommands().then(
      (data) => {
        if (data.commands?.length) setCommands(data.commands.map((c) => c.name));
      },
      () => undefined,
    );
  }, [fixture]);

  const connection = fixture ? ("open" as const) : live.connection;
  const liveError = fixture ? null : live.error;
  const paused = fixture ? false : live.paused;
  const setPaused = live.setPaused;

  const rawEvents: RuntimeEvent[] = fixture ? liveEventsFixture() : live.events;

  const filteredEvents = useMemo(() => {
    const q = debouncedSearch.toLowerCase();
    const sinceMs = consoleNowMs() - hoursForRange(timeRange) * 3_600_000;
    let rows = rawEvents.filter((e) => e.created_at_ms >= sinceMs);

    if (severityChip !== "all") {
      rows = rows.filter((e) => normalizeSeverity(e.level) === severityChip);
    } else if (level) {
      rows = rows.filter((e) => e.level.toUpperCase() === level.toUpperCase());
    }
    if (service) {
      const s = service.toLowerCase();
      rows = rows.filter(
        (e) =>
          (e.subsystem || "").toLowerCase() === s ||
          (e.source || "").toLowerCase() === s ||
          (e.category || "").toLowerCase() === s,
      );
    }
    if (category) {
      rows = rows.filter((e) => (e.category || "").toLowerCase() === category.toLowerCase());
    }
    if (quickFilter) {
      rows = rows.filter((e) => eventMatchesQuickFilter(e, quickFilter));
    }
    if (q) {
      rows = rows.filter((e) => eventSearchHaystack(e).includes(q));
    }
    if (regexState.re) {
      rows = rows.filter((e) => regexState.re!.test(eventSearchHaystack(e)));
    } else if (regexState.error) {
      // Keep previous non-regex filtering; UI surfaces validation separately.
    }

    // Chronological ascending for live console (oldest → newest).
    return [...rows].sort((a, b) => a.sequence - b.sequence);
  }, [
    category,
    debouncedSearch,
    level,
    quickFilter,
    rawEvents,
    regexState.error,
    regexState.re,
    service,
    severityChip,
    timeRange,
  ]);

  const bufferCounts = useMemo(() => {
    let errors = 0;
    let warnings = 0;
    for (const e of rawEvents) {
      const s = normalizeSeverity(e.level);
      if (s === "error") errors += 1;
      if (s === "warning") warnings += 1;
    }
    return { errors, warnings, total: rawEvents.length };
  }, [rawEvents]);

  const serviceOptions = useMemo(() => {
    const fromStats = overview?.stats.filter_options.subsystems ?? [];
    const fromServices = (overview?.services ?? []).map((s) => s.name);
    return Array.from(new Set([...fromStats, ...fromServices])).filter(Boolean).sort();
  }, [overview]);

  const categoryOptions = useMemo(() => {
    return overview?.stats.filter_options.categories ?? [];
  }, [overview]);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    if (!fixture) await live.refresh();
    await loadOverview();
  }, [fixture, live, loadOverview]);

  const clearView = useCallback(() => {
    if (fixture) {
      toast("Fixture — wissen gesimuleerd");
      return;
    }
    live.clearLocal();
    toast("Console-weergave gewist (serverhistorie behouden)");
  }, [fixture, live, toast]);

  const exportLogs = useCallback(async () => {
    if (exportBusy) return;
    setExportBusy(true);
    try {
      const collected: RuntimeEvent[] = [];
      if (fixture) {
        collected.push(...filteredEvents);
      } else {
        let before: number | undefined;
        for (let page = 0; page < EXPORT_MAX_PAGES; page += 1) {
          const data = await api.listEvents({
            limit: EXPORT_PAGE_LIMIT,
            before,
            level: severityChip === "all" ? level || undefined : severityChip.toUpperCase(),
            category: category || undefined,
            subsystem: service || undefined,
            q: debouncedSearch || undefined,
            since_ms: consoleNowMs() - hoursForRange(timeRange) * 3_600_000,
          });
          if (!data.events.length) break;
          collected.push(...data.events);
          const minSeq = Math.min(...data.events.map((e) => e.sequence));
          before = minSeq;
          if (data.events.length < EXPORT_PAGE_LIMIT) break;
        }
        // Union with currently filtered client buffer for live-only rows.
        const bySeq = new Map<number, RuntimeEvent>();
        for (const e of collected) bySeq.set(e.sequence, e);
        for (const e of filteredEvents) bySeq.set(e.sequence, e);
        collected.length = 0;
        collected.push(...Array.from(bySeq.values()).sort((a, b) => a.sequence - b.sequence));
      }

      const payload = JSON.stringify(
        collected.map((e) => ({
          sequence: e.sequence,
          created_at_ms: e.created_at_ms,
          level: e.level,
          category: e.category,
          subsystem: e.subsystem,
          name: e.name,
          message: e.message,
          source: e.source,
          correlation_id: e.correlation_id,
          duration_ms: e.duration_ms,
          // Never include raw payload blobs in export downloads from the console UI.
        })),
        null,
        2,
      );
      const blob = new Blob([payload], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `leviathan-console-${Date.now()}.json`;
      a.click();
      URL.revokeObjectURL(url);
      toast(`Geëxporteerd: ${collected.length} events (begrensd)`);
    } catch (err) {
      toast(err instanceof Error ? err.message : "Export mislukt");
    } finally {
      setExportBusy(false);
    }
  }, [
    category,
    debouncedSearch,
    exportBusy,
    filteredEvents,
    fixture,
    level,
    service,
    severityChip,
    timeRange,
    toast,
  ]);

  const runCommand = useCallback(
    async (raw?: string) => {
      const text = (raw ?? command).trim();
      if (!text) {
        toast("Voer een operator-commando in");
        return;
      }
      if (fixture) {
        toast("Fixture — commando niet uitgevoerd");
        return;
      }
      if (cmdBusy) return;
      setCmdBusy(true);
      const stamp = new Date();
      const time = `${String(stamp.getHours()).padStart(2, "0")}:${String(stamp.getMinutes()).padStart(2, "0")}`;
      setHistory((prev) =>
        [{ id: `h-${Date.now()}`, time, command: text, ok: true }, ...prev].slice(0, 20),
      );
      try {
        const { result } = await api.runOperatorCommand(text);
        setHistory((prev) => prev.map((h, i) => (i === 0 ? { ...h, ok: result.ok } : h)));
        toast(result.ok ? `OK: ${text}` : result.error || `Mislukt: ${text}`);
        void live.refresh();
        setCommand("");
      } catch (err) {
        toast(err instanceof Error ? err.message : "Commando mislukt");
      } finally {
        setCmdBusy(false);
      }
    },
    [cmdBusy, command, fixture, live, toast],
  );

  const applyErrorFocus = useCallback(
    (sequence: number) => {
      setSeverityChip("error");
      setQuickFilter("errors");
      setFocusSequence(sequence);
    },
    [],
  );

  return {
    overview,
    overviewError,
    stale,
    loading,
    refreshing,
    connection,
    liveError,
    paused,
    setPaused,
    events: filteredEvents,
    bufferCounts,
    search,
    setSearch,
    level,
    setLevel,
    service,
    setService,
    category,
    setCategory,
    severityChip,
    setSeverityChip,
    quickFilter,
    setQuickFilter,
    timeRange,
    setTimeRange,
    timeRangeOptions: CONSOLE_TIME_RANGES,
    autoScroll,
    setAutoScroll,
    regexText,
    setRegexText,
    regexError: regexState.error,
    serviceOptions,
    categoryOptions,
    focusSequence,
    setFocusSequence,
    menuOpen,
    setMenuOpen,
    commandsOpen,
    setCommandsOpen,
    resourcesOpen,
    setResourcesOpen,
    command,
    setCommand,
    commands,
    cmdBusy,
    history,
    runCommand,
    exportBusy,
    refresh,
    clearView,
    exportLogs,
    applyErrorFocus,
    telemetrySample: telemetry.sample,
    telemetryError: telemetry.error,
    fixture,
  };
}
