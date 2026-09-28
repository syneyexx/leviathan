import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { controlGates } from "../domain/controls";
import { countHealthy, mapServices } from "../domain/health";
import { isHostSnapshot, optimisticCommand, stoppedSnapshot } from "../domain/host";
import { ingestionActive, mapIngestion } from "../domain/ingestion";
import { mapEvent } from "../domain/logs";
import { mapNative } from "../domain/native";
import {
  loadingProjection,
  liveProjection,
  markTransportError,
  type ReadProjection,
} from "../domain/projection";
import { emptyHistories, metricCards, readPerformance, type MetricHistories } from "../domain/telemetry";
import { mapWorkers } from "../domain/workers";
import { getJson, invokeHost, tauriAvailable } from "../lib/api";
import { commandFailureMessage } from "../lib/errors";
import { formatUptime } from "../lib/format";
import { appendUnique } from "../lib/ringBuffer";
import { nextSseDelay, parseSseId } from "../lib/sse";
import { pushSample } from "../lib/timeSeries";
import { traceUi } from "../lib/trace";
import type { LogRowModel } from "../types/backend";
import type { BridgeState, CommandError, ConsoleLine, HostSnapshot } from "../types/host";

function withTimeout<T>(promise: Promise<T>, ms: number, label: string): Promise<T> {
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => reject(new Error(`${label} timed out after ${ms}ms`)), ms);
    promise.then(resolve, reject).finally(() => window.clearTimeout(timer));
  });
}

type JsonMap = Record<string, unknown>;

export function useOperator() {
  const [host, setHost] = useState<HostSnapshot>(stoppedSnapshot());
  const [bridge, setBridge] = useState<BridgeState>(tauriAvailable() ? "CONNECTING" : "FAILED");
  const [bridgeError, setBridgeError] = useState<string | null>(
    tauriAvailable() ? null : "Tauri host bridge is missing. __TAURI_INTERNALS__ was not injected. Launch run_leviathan.exe rather than the bare renderer.",
  );
  const [commandError, setCommandError] = useState<CommandError | null>(null);
  const [inflight, setInflight] = useState<string | null>(null);
  const [lines, setLines] = useState<ConsoleLine[]>([]);
  const [paused, setPaused] = useState(false);
  const [logsPaused, setLogsPaused] = useState(false);

  const [liveness, setLiveness] = useState<ReadProjection<JsonMap>>(loadingProjection);
  const [health, setHealth] = useState<ReadProjection<JsonMap>>(loadingProjection);
  const [databases, setDatabases] = useState<ReadProjection<Array<JsonMap>>>(loadingProjection);
  const [dashboard, setDashboard] = useState<ReadProjection<JsonMap>>(loadingProjection);
  const [nativePayload, setNativePayload] = useState<ReadProjection<JsonMap>>(loadingProjection);
  const [ingestionPayload, setIngestionPayload] = useState<ReadProjection<JsonMap>>(loadingProjection);
  const [performance, setPerformance] = useState<ReadProjection<JsonMap>>(loadingProjection);
  const [modelsStatus, setModelsStatus] = useState<ReadProjection<JsonMap>>(loadingProjection);
  const [queueDepth, setQueueDepth] = useState<number | null>(null);
  const [histories, setHistories] = useState<MetricHistories>(emptyHistories());
  const [logs, setLogs] = useState<LogRowModel[]>([]);
  const [frontendReachable, setFrontendReachable] = useState<boolean | null>(null);
  const [sseTransportError, setSseTransportError] = useState(false);

  const pausedRef = useRef(false);
  pausedRef.current = paused;
  const clearFloor = useRef(0);
  const hostRef = useRef(host);
  hostRef.current = host;
  const bridgeRef = useRef(bridge);
  bridgeRef.current = bridge;
  const inflightRef = useRef<string | null>(null);

  const pushLines = useCallback((incoming: ConsoleLine[]) => {
    if (pausedRef.current) return;
    setLines((current) => appendUnique(current.filter((line) => line.seq >= clearFloor.current), incoming, 20_000));
  }, []);

  const noteFailure = useCallback((action: string, message: string) => {
    const at = new Date().toISOString();
    setCommandError({ action, message, at });
    setLines((current) => appendUnique(current, [{
      seq: (current[current.length - 1]?.seq ?? clearFloor.current) + 1,
      at,
      source: "host",
      level: "error",
      stream: "system",
      text: `${action}: ${message}`,
    }], 20_000));
  }, []);

  const resetBackendProjections = useCallback(() => {
    setLiveness(loadingProjection());
    setHealth(loadingProjection());
    setDatabases(loadingProjection());
    setDashboard(loadingProjection());
    setNativePayload(loadingProjection());
    setIngestionPayload(loadingProjection());
    setPerformance(loadingProjection());
    setModelsStatus(loadingProjection());
    setQueueDepth(null);
    setFrontendReachable(null);
    setSseTransportError(false);
  }, []);

  useEffect(() => {
    let stop = false;
    const available = tauriAvailable();
    traceUi("TAURI_AVAILABLE", String(available));
    if (!available) {
      setBridge("FAILED");
      setBridgeError("Tauri host bridge is missing. __TAURI_INTERNALS__ was not injected. Launch run_leviathan.exe rather than the bare renderer.");
      return;
    }
    setBridge("CONNECTING");
    void invokeHost<unknown>("host_snapshot").then((snap) => {
      if (stop) return;
      if (!isHostSnapshot(snap)) {
        setBridge("FAILED");
        setBridgeError("host_snapshot returned an unusable payload.");
        return;
      }
      setHost(snap);
      setBridge("READY");
      traceUi("HOST_STATE", snap.state);
    }).catch((error: unknown) => {
      if (stop) return;
      setBridge("FAILED");
      setBridgeError(`HOST BRIDGE FAILURE: ${commandFailureMessage(error)}`);
    });
    let unlistenState: (() => void) | undefined;
    let unlistenConsole: (() => void) | undefined;
    void import("@tauri-apps/api/event").then(async (mod) => {
      try {
        unlistenState = await mod.listen<HostSnapshot>("host://state", (event) => {
          if (!stop && isHostSnapshot(event.payload)) setHost(event.payload);
        });
        unlistenConsole = await mod.listen<ConsoleLine[]>("host://console", (event) => {
          if (!stop) pushLines(event.payload);
        });
      } catch (error) {
        if (!stop) {
          setBridge("FAILED");
          setBridgeError(`HOST BRIDGE FAILURE: event channel: ${commandFailureMessage(error)}`);
        }
      }
    }).catch((error: unknown) => {
      if (!stop) {
        setBridge("FAILED");
        setBridgeError(`HOST BRIDGE FAILURE: ${commandFailureMessage(error)}`);
      }
    });
    return () => {
      stop = true;
      unlistenState?.();
      unlistenConsole?.();
    };
  }, [pushLines]);

  const apiBase = host.apiBase;
  const live = host.state === "RUNNING" || host.state === "DEGRADED" || host.state === "STARTING" || host.state === "ATTACHED_EXTERNAL";
  const livenessIndependent =
    host.state === "RUNNING" || host.state === "DEGRADED" || host.state === "ATTACHED_EXTERNAL";

  useEffect(() => {
    if (!apiBase || !live) {
      resetBackendProjections();
      return;
    }
  }, [apiBase, live, resetBackendProjections]);

  // Independent liveness monitor — only while RUNNING/DEGRADED/ATTACHED.
  // During PREFLIGHT/STARTING the native Rust host controller owns readiness;
  // do not race it with burst HTTP polls on every host.state transition.
  const hostStateRef = useRef(host.state);
  hostStateRef.current = host.state;
  useEffect(() => {
    if (!apiBase || !livenessIndependent) {
      // Trust host bridge during STARTING/PREFLIGHT — no immediate tick burst.
      return;
    }
    const controller = new AbortController();
    let timer = 0;
    let stopped = false;
    const tick = async () => {
      if (stopped) return;
      // Re-check state without recreating the effect on every transition.
      const state = hostStateRef.current;
      if (state !== "RUNNING" && state !== "DEGRADED" && state !== "ATTACHED_EXTERNAL") {
        return;
      }
      const hidden = document.hidden;
      try {
        const body = await getJson<JsonMap>(apiBase, "/api/host/liveness", controller.signal);
        setLiveness(liveProjection(body));
        setFrontendReachable(body.ok === true);
      } catch (error) {
        if (!controller.signal.aborted) {
          setLiveness((prev) => markTransportError(prev, error));
          setFrontendReachable(false);
        }
      }
      // Slow independent monitor once RUNNING — host-core already probes at 400ms.
      const delay = hidden ? 15_000 : 5_000;
      timer = window.setTimeout(() => void tick(), delay);
    };
    // Defer first tick slightly so STARTING→RUNNING does not immediately
    // pile onto the host controller's own liveness probe.
    timer = window.setTimeout(() => void tick(), 750);
    return () => {
      stopped = true;
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [apiBase, livenessIndependent]);

  // Slower /api/health — optional enrichment (jobs queue, llm fallback).
  useEffect(() => {
    if (!apiBase || !live) return;
    const controller = new AbortController();
    let timer = 0;
    const tick = async () => {
      try {
        const body = await getJson<JsonMap>(apiBase, "/api/health", controller.signal);
        setHealth(liveProjection(body));
        const jobs = body.jobs as Record<string, unknown> | undefined;
        if (typeof jobs?.queued === "number") setQueueDepth(jobs.queued);
      } catch (error) {
        if (!controller.signal.aborted) {
          setHealth((prev) => markTransportError(prev, error));
        }
      }
      timer = window.setTimeout(() => void tick(), document.hidden ? 20_000 : 10_000);
    };
    void tick();
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [apiBase, live]);

  // Model runtime card — /api/models/status.
  useEffect(() => {
    if (!apiBase || !live) return;
    const controller = new AbortController();
    let timer = 0;
    const tick = async () => {
      try {
        const body = await getJson<JsonMap>(apiBase, "/api/models/status", controller.signal);
        setModelsStatus(liveProjection(body));
      } catch (error) {
        if (!controller.signal.aborted) {
          setModelsStatus((prev) => markTransportError(prev, error));
        }
      }
      timer = window.setTimeout(() => void tick(), document.hidden ? 20_000 : 5_000);
    };
    void tick();
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [apiBase, live]);

  useEffect(() => {
    if (!apiBase || !live) return;
    const controller = new AbortController();
    let timer = 0;
    const tick = async () => {
      try {
        const body = await getJson<JsonMap>(apiBase, "/api/workers/dashboard", controller.signal);
        setDashboard(liveProjection(body));
        const summary = body.summary as Record<string, unknown> | undefined;
        if (typeof summary?.queue_depth === "number") setQueueDepth(summary.queue_depth);
      } catch (error) {
        if (!controller.signal.aborted) {
          setDashboard((prev) => markTransportError(prev, error));
        }
      }
      timer = window.setTimeout(() => void tick(), document.hidden ? 12_000 : 2_000);
    };
    void tick();
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [apiBase, live]);

  useEffect(() => {
    if (!apiBase || !live) return;
    const controller = new AbortController();
    let timer = 0;
    const tick = async () => {
      try {
        const body = await getJson<JsonMap>(apiBase, "/api/performance/snapshot", controller.signal);
        setPerformance(liveProjection(body));
        const latest = readPerformance(body);
        setHistories((current) => ({
          queue: pushSample(current.queue, queueDepth),
          tasks: pushSample(current.tasks, latest.tasksPerMin),
          completed: pushSample(current.completed, latest.completed),
          cpu: pushSample(current.cpu, latest.cpu),
          memory: pushSample(current.memory, latest.memory),
          disk: pushSample(current.disk, latest.disk),
          native: pushSample(current.native, latest.nativeOps),
          docs: pushSample(current.docs, latest.docs),
          network: pushSample(current.network, latest.network),
        }));
      } catch (error) {
        if (!controller.signal.aborted) {
          setPerformance((prev) => markTransportError(prev, error));
        }
      }
      timer = window.setTimeout(() => void tick(), document.hidden ? 12_000 : 2_000);
    };
    void tick();
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [apiBase, live, queueDepth]);

  const ingestionActiveRef = useRef(false);
  useEffect(() => {
    if (!apiBase || !live) return;
    const controller = new AbortController();
    let timer = 0;
    const tick = async () => {
      try {
        const body = await getJson<JsonMap>(apiBase, "/api/host/source-ingestion", controller.signal);
        setIngestionPayload(liveProjection(body));
        ingestionActiveRef.current = ingestionActive(mapIngestion(body));
      } catch (error) {
        if (!controller.signal.aborted) {
          setIngestionPayload((prev) => markTransportError(prev, error));
        }
      }
      try {
        const native = await getJson<JsonMap>(apiBase, "/api/host/native-operations", controller.signal);
        setNativePayload(liveProjection(native));
      } catch (error) {
        if (!controller.signal.aborted) {
          setNativePayload((prev) => markTransportError(prev, error));
        }
      }
      timer = window.setTimeout(() => void tick(), document.hidden ? 20_000 : ingestionActiveRef.current ? 2_000 : 5_000);
    };
    void tick();
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [apiBase, live]);

  useEffect(() => {
    if (!apiBase || !live) return;
    const controller = new AbortController();
    const readOverview = async () => {
      try {
        const body = await getJson<{ databases?: Array<JsonMap> }>(apiBase, "/api/host/overview", controller.signal);
        setDatabases(liveProjection(body.databases || []));
      } catch (error) {
        if (!controller.signal.aborted) {
          setDatabases((prev) => markTransportError(prev, error));
        }
      }
    };
    const timer = window.setInterval(() => void readOverview(), 20_000);
    void readOverview();
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [apiBase, live]);

  useEffect(() => {
    if (!apiBase || !live || logsPaused) return;
    let cursor = 0;
    let attempt = 0;
    let source: EventSource | null = null;
    let timer = 0;
    let closed = false;
    const connect = () => {
      if (closed) return;
      source = new EventSource(`${apiBase}/api/events/stream?last_event_id=${cursor}`);
      source.addEventListener("event", (event) => {
        attempt = 0;
        setSseTransportError(false);
        const id = parseSseId((event as MessageEvent).lastEventId || null);
        if (id != null) cursor = id;
        try {
          const payload = JSON.parse((event as MessageEvent).data) as Record<string, unknown>;
          setLogs((current) => [...current, mapEvent(payload, current.length)].slice(-500));
        } catch {
          // Ignore malformed SSE payloads.
        }
      });
      source.onerror = () => {
        source?.close();
        attempt += 1;
        if (attempt >= 3) setSseTransportError(true);
        timer = window.setTimeout(connect, nextSseDelay(attempt));
      };
    };
    connect();
    return () => {
      closed = true;
      source?.close();
      window.clearTimeout(timer);
    };
  }, [apiBase, live, logsPaused]);

  const workers = useMemo(() => mapWorkers(dashboard), [dashboard]);
  const native = useMemo(() => mapNative(nativePayload.data), [nativePayload]);
  const ingestionUnavailable = ingestionPayload.state === "TRANSPORT_ERROR" || ingestionPayload.state === "UNAVAILABLE";
  const ingestion = useMemo(
    () => mapIngestion(ingestionPayload.data, ingestionUnavailable && ingestionPayload.data == null),
    [ingestionPayload, ingestionUnavailable],
  );
  const supervisor =
    (dashboard.data?.supervisor as Record<string, unknown> | undefined)?.health as string | undefined
    || host.supervisorHealth;
  const services = useMemo(
    () => mapServices({
      host,
      liveness,
      health,
      modelsStatus,
      databases,
      dashboard,
      nativeStatus: native.status === "UNMEASURED" && transportNative(nativePayload) ? null : native.status,
      nativeDetail: native.detail,
      nativeProjection: nativePayload,
      supervisor: supervisor ?? null,
      queueDepth,
      queueProjection: health.state !== "LOADING" ? health : dashboard,
      pythonVersion: host.pythonVersion || host.preflight.pythonVersion,
    }),
    [host, liveness, health, modelsStatus, databases, dashboard, native, nativePayload, supervisor, queueDepth],
  );
  const metrics = useMemo(
    () => metricCards(histories, readPerformance(performance.data), queueDepth),
    [histories, performance, queueDepth],
  );

  const model = {
    host,
    services,
    workers: workers.rows,
    workerSummary: workers.summary,
    metrics,
    logs,
    ingestion,
    native,
    uptime: formatUptime(host.startedAt),
    servicesOnline: countHealthy(services),
    queue: queueDepth == null
      ? (health.state === "TRANSPORT_ERROR" || dashboard.state === "TRANSPORT_ERROR" ? "TRANSPORT ERROR" : "UNMEASURED")
      : String(queueDepth),
    systemReadiness: host.systemReadiness ?? "UNMEASURED",
    sseTransportError,
  };

  const run = useCallback(async (command: string, args?: Record<string, unknown>) => {
    const available = tauriAvailable();
    traceUi("TAURI_AVAILABLE", String(available));
    if (command === "host_start") traceUi("UI_START_CLICK", "host_start");
    traceUi("INVOKE_BEGIN", command);
    if (!available || bridgeRef.current !== "READY") {
      const message = !available
        ? "HOST BRIDGE FAILURE: Tauri IPC is not injected. Launch run_leviathan.exe."
        : `HOST BRIDGE FAILURE: bridge is ${bridgeRef.current}. ${bridgeError || "host_snapshot was not received."}`;
      traceUi("INVOKE_ERROR", `${command}: ${message}`);
      noteFailure(command, message);
      return;
    }
    if (inflightRef.current) {
      const message = `${inflightRef.current} is still running. Wait for it to finish.`;
      traceUi("INVOKE_ERROR", `${command}: ${message}`);
      noteFailure(command, message);
      return;
    }
    inflightRef.current = command;
    setInflight(command);
    const optimistic = optimisticCommand(hostRef.current, command);
    if (optimistic) {
      setHost(optimistic);
      traceUi("HOST_STATE", optimistic.state);
    }
    try {
      const timeout = command === "host_start" || command === "host_restart" ? 120_000 : 30_000;
      const result = await withTimeout(invokeHost<unknown>(command, args), timeout, command);
      if (isHostSnapshot(result)) {
        setHost(result);
        traceUi("HOST_STATE", result.state);
      }
      traceUi("INVOKE_SUCCESS", command);
    } catch (error) {
      const message = commandFailureMessage(error);
      traceUi("INVOKE_ERROR", `${command}: ${message}`);
      noteFailure(command, message);
      try {
        const snap = await invokeHost<unknown>("host_snapshot");
        if (isHostSnapshot(snap)) setHost(snap);
      } catch (reconcile) {
        setBridge("FAILED");
        setBridgeError(`HOST BRIDGE FAILURE: ${commandFailureMessage(reconcile)}`);
      }
    } finally {
      inflightRef.current = null;
      setInflight(null);
    }
  }, [bridgeError, noteFailure]);

  return {
    model,
    lines,
    paused,
    logsPaused,
    bridge,
    bridgeError,
    commandError,
    inflight,
    clearCommandError: () => setCommandError(null),
    gates: controlGates(model.host, frontendReachable, bridge),
    actions: {
      start: () => void run("host_start", { safeMode: host.safeModeArmed }),
      stop: () => void run("host_stop"),
      restart: () => void run("host_restart", { safeMode: host.safeModeArmed }),
      safe: () => void run("host_preferences_set", { preferences: { safeMode: !host.safeModeArmed, autoScroll: true, paused: false } }),
      frontend: () => void run("host_open", { target: "frontend" }),
      config: () => void run("host_open", { target: "config" }),
      logs: () => void run("host_open", { target: "logs" }),
      emergency: () => void run("host_emergency"),
      confirmClose: () => void run("host_confirm_close", { stopOwned: true }),
      clearConsole: () => {
        clearFloor.current = (lines[lines.length - 1]?.seq ?? 0) + 1;
        setLines([]);
      },
      togglePause: () => setPaused((value) => !value),
      toggleLogPause: () => setLogsPaused((value) => !value),
    },
  };
}

function transportNative(projection: ReadProjection<JsonMap>): boolean {
  return projection.state === "TRANSPORT_ERROR" || projection.state === "STALE" || projection.state === "UNAVAILABLE";
}
