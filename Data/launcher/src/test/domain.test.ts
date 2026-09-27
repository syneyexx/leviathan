import { describe, expect, it } from "vitest";
import { controlGates } from "../domain/controls";
import { mapServices, modelStateFrom, toneFor } from "../domain/health";
import { mapIngestion } from "../domain/ingestion";
import { filterLogs, mapEvent } from "../domain/logs";
import { mapNative, nativeIsHealthy } from "../domain/native";
import {
  liveProjection,
  loadingProjection,
  markTransportError,
  classifyFetchError,
} from "../domain/projection";
import { metricCards, readPerformance, emptyHistories } from "../domain/telemetry";
import { mapWorker, mapWorkers } from "../domain/workers";
import { isHostSnapshot, optimisticCommand, stoppedSnapshot } from "../domain/host";
import { appendUnique, pushRing } from "../lib/ringBuffer";
import { pushSample } from "../lib/timeSeries";
import { redactText } from "../lib/redaction";
import { nextSseDelay, parseSseId } from "../lib/sse";

describe("control gates", () => {
  it("disables destructive controls for an external instance", () => {
    const host = { ...stoppedSnapshot(), state: "ATTACHED_EXTERNAL", ownership: "EXTERNAL" as const };
    const gates = controlGates(host, true);
    expect(gates.start.enabled).toBe(false);
    expect(gates.stop.enabled).toBe(false);
    expect(gates.emergency.enabled).toBe(false);
    expect(gates.restart.enabled).toBe(false);
  });

  it("enables start only when stopped and the bridge is ready", () => {
    const stopped = controlGates(stoppedSnapshot(), null, "READY");
    expect(stopped.start.enabled).toBe(true);
    expect(controlGates({ ...stoppedSnapshot(), state: "PREFLIGHT" }, null).start.enabled).toBe(false);
    expect(controlGates({ ...stoppedSnapshot(), state: "STARTING" }, null).start.enabled).toBe(false);
    const running = controlGates({ ...stoppedSnapshot(), state: "RUNNING", ownership: "OWNED", pid: 4 }, null);
    expect(running.start.enabled).toBe(false);
    expect(running.stop.enabled).toBe(true);
    const degraded = controlGates({ ...stoppedSnapshot(), state: "DEGRADED", ownership: "OWNED", pid: 4 }, null);
    expect(degraded.stop.enabled).toBe(true);
    expect(controlGates(stoppedSnapshot(), null, "FAILED").start.enabled).toBe(false);
    expect(controlGates(stoppedSnapshot(), null, "CONNECTING").start.enabled).toBe(false);
  });

  it("marks an immediate preflight state before the invoke returns", () => {
    const next = optimisticCommand(stoppedSnapshot(), "host_start");
    expect(next?.state).toBe("PREFLIGHT");
    expect(isHostSnapshot("http://127.0.0.1/")).toBe(false);
    expect(isHostSnapshot(stoppedSnapshot())).toBe(true);
  });

  it("enables stop only for an owned live process", () => {
    const host = { ...stoppedSnapshot(), state: "RUNNING", ownership: "OWNED" as const, pid: 10 };
    const gates = controlGates(host, false);
    expect(gates.start.enabled).toBe(false);
    expect(gates.stop.enabled).toBe(true);
    expect(gates.emergency.enabled).toBe(true);
    expect(gates.frontend.enabled).toBe(false);
    expect(gates.frontend.reason).toContain("not reachable");
  });
});

describe("null handling", () => {
  it("does not turn a missing worker cpu into zero", () => {
    const row = mapWorker({ worker_id: "pool-1", state: "READY", cpu_percent: null, rss_mb: null });
    expect(row.cpu).toBe("UNMEASURED");
    expect(row.ram).toBe("UNMEASURED");
    expect(row.id).toBe("pool-1");
    expect(row.task).toBe("IDLE/WAITING");
  });

  it("keeps missing metrics null in the history", () => {
    const history = pushSample([1], null, 4);
    expect(history).toEqual([1, null]);
    const cards = metricCards(emptyHistories(), readPerformance(null), null);
    expect(cards.find((card) => card.id === "cpu")?.value).toBe("UNMEASURED");
    expect(cards.find((card) => card.id === "queue")?.value).toBe("UNMEASURED");
  });
});

describe("adapters", () => {
  it("maps worker fabric rows without inventing ids", () => {
    const row = mapWorker({
      worker_id: "research-0",
      state: "BUSY",
      current_work: "classifying",
      pool_id: "research",
      cpu_percent: 12.5,
      rss_mb: 80,
      heartbeat_age_seconds: 2,
    });
    expect(row.id).toBe("research-0");
    expect(row.cpu).toBe("12.5%");
    expect(row.task).toBe("classifying");
  });

  it("does not mark a partial ingestion job complete", () => {
    const model = mapIngestion({
      counts: { queued: 1, processing: 0, completed: 0, failed: 1, unknown: 0 },
      overallProgressPct: null,
      jobs: [{ id: "src", source: "a.pdf", phase: "partial", state: "FAILED", progressPct: null, throughput: null, etaSeconds: null }],
    });
    expect(model.completed).toBe(0);
    expect(model.failed).toBe(1);
    expect(model.jobs[0].throughput).toBe("UNMEASURED");
    expect(model.overallProgressPct).toBeNull();
  });

  it("treats BUILD_MISSING as not healthy", () => {
    const native = mapNative({ probe: { status: "BUILD_MISSING", binaryPath: "/opt/bin", operations: [], detail: "missing" } });
    expect(nativeIsHealthy(native)).toBe(false);
    expect(native.daemon).toBe(false);
    expect(toneFor("BUILD MISSING")).toBe("bad");
    expect(toneFor("UNMEASURED")).toBe("muted");
  });

  it("maps service health from evidence", () => {
    const cards = mapServices({
      host: { ...stoppedSnapshot(), state: "RUNNING", ownership: "OWNED" },
      health: { ok: true, liveness: "alive", llm: { ok: false, status: "unavailable" } },
      databases: [
        { domain: "CONTROL", health: "OK", tableCount: 4 },
        { domain: "KNOWLEDGE", health: "MISSING", tableCount: "UNMEASURED" },
        { domain: "MARKET", health: "BUSY", tableCount: 1 },
      ],
      nativeStatus: "BUILD_MISSING",
      nativeDetail: "binary not found",
      supervisor: "DEGRADED",
      queueDepth: 3,
      pythonVersion: "3.12.3",
    });
    expect(cards.find((card) => card.id === "api")?.tone).toBe("ok");
    expect(cards.find((card) => card.id === "knowledge")?.state).toBe("NOT CONFIGURED");
    expect(cards.find((card) => card.id === "native")?.tone).toBe("bad");
    expect(cards.find((card) => card.id === "model")?.state).not.toBe("HEALTHY");
    expect(cards.find((card) => card.id === "workers")?.state).toBe("DEGRADED");
  });
});

describe("projection and transport truth", () => {
  it("test_transport_error_is_not_unmeasured", () => {
    const failed = markTransportError(loadingProjection<Record<string, unknown>>(), new Error("/api/host/liveness returned 502"));
    const cards = mapServices({
      host: { ...stoppedSnapshot(), state: "RUNNING", ownership: "OWNED", systemReadiness: "READY" },
      liveness: failed,
      health: failed,
      databases: failed as never,
      nativeStatus: null,
      nativeDetail: null,
      nativeProjection: failed,
      supervisor: null,
      queueDepth: null,
      queueProjection: failed,
      pythonVersion: null,
      modelsStatus: failed,
      dashboard: failed,
    });
    expect(cards.find((card) => card.id === "api")?.state).toBe("TRANSPORT ERROR");
    expect(cards.find((card) => card.id === "api")?.state).not.toBe("UNMEASURED");
    expect(toneFor("TRANSPORT ERROR")).toBe("bad");
    expect(mapWorkers(failed).summary).toBe("TRANSPORT ERROR");
  });

  it("test_unmeasured_metric_remains_unmeasured", () => {
    const cards = mapServices({
      host: { ...stoppedSnapshot(), state: "RUNNING", ownership: "OWNED" },
      liveness: liveProjection({ started: true }),
      health: liveProjection({ started: true }),
      databases: liveProjection([]),
      modelsStatus: liveProjection({ status: {} }),
      nativeStatus: null,
      nativeDetail: null,
      supervisor: null,
      queueDepth: null,
      pythonVersion: null,
    });
    expect(cards.find((card) => card.id === "api")?.state).toBe("UNMEASURED");
    expect(cards.find((card) => card.id === "api")?.detail).toContain("missing");
    expect(cards.find((card) => card.id === "model")?.state).toBe("UNMEASURED");
    expect(cards.find((card) => card.id === "queue")?.state).toBe("UNMEASURED");
  });

  it("test_stale_projection_is_marked_stale", () => {
    const live = liveProjection({ ok: true, liveness: "alive" }, 1_000);
    const stale = markTransportError(live, new TypeError("Failed to fetch"), 20_000, 15_000);
    expect(stale.state).toBe("STALE");
    expect(stale.data?.ok).toBe(true);
    expect(toneFor("STALE")).toBe("warn");
    const cards = mapServices({
      host: { ...stoppedSnapshot(), state: "RUNNING", ownership: "OWNED" },
      liveness: stale,
      health: loadingProjection(),
      databases: null,
      nativeStatus: "AVAILABLE",
      nativeDetail: "ok",
      supervisor: "RUNNING",
      queueDepth: 0,
      pythonVersion: "3.12",
    });
    expect(cards.find((card) => card.id === "api")?.state).toBe("STALE");
  });

  it("test_recovered_projection_returns_live", () => {
    const failed = markTransportError(loadingProjection<{ ok: boolean }>(), new Error("down"));
    expect(failed.state).toBe("TRANSPORT_ERROR");
    const recovered = liveProjection({ ok: true, liveness: "alive" });
    expect(recovered.state).toBe("LIVE");
    expect(recovered.errorCode).toBeNull();
    const cards = mapServices({
      host: { ...stoppedSnapshot(), state: "RUNNING", ownership: "OWNED" },
      liveness: recovered,
      health: loadingProjection(),
      databases: null,
      nativeStatus: null,
      nativeDetail: null,
      supervisor: null,
      queueDepth: 0,
      pythonVersion: "3.12",
    });
    expect(cards.find((card) => card.id === "api")?.state).toBe("HEALTHY");
  });

  it("test_model_available_contract", () => {
    expect(modelStateFrom({ available: true, activeModel: "llama" })).toEqual({
      state: "HEALTHY",
      detail: "llama",
    });
    expect(modelStateFrom({ ok: true, model: "mistral" }).state).toBe("HEALTHY");
    expect(modelStateFrom({ reachable: true, status: "ok" }).state).toBe("HEALTHY");
    const cards = mapServices({
      host: { ...stoppedSnapshot(), state: "RUNNING", ownership: "OWNED" },
      liveness: liveProjection({ ok: true }),
      modelsStatus: liveProjection({
        status: { availableModels: 3, gatewayHealth: "healthy", activeModel: "phi" },
      }),
      databases: null,
      nativeStatus: null,
      nativeDetail: null,
      supervisor: null,
      queueDepth: 0,
      pythonVersion: "3.12",
    });
    expect(cards.find((card) => card.id === "model")?.state).toBe("HEALTHY");
    expect(cards.find((card) => card.id === "model")?.detail).toBe("phi");
  });

  it("test_no_model_loaded_is_not_backend_failure", () => {
    const idle = modelStateFrom({ available: true, activeModel: null });
    expect(idle.state).toBe("IDLE");
    expect(idle.detail).toBe("NO MODEL LOADED");
    expect(toneFor(idle.state)).toBe("ok");
    const fromStatus = modelStateFrom({
      status: { availableModels: 2, gatewayHealth: "healthy", activeModel: null, loadedModels: 0 },
    });
    expect(fromStatus.state).toBe("IDLE");
    expect(fromStatus.detail).toBe("NO MODEL LOADED");
    expect(toneFor("TRANSPORT ERROR")).not.toBe("muted");
  });

  it("test_queue_zero_is_measured_zero", () => {
    const cards = mapServices({
      host: { ...stoppedSnapshot(), state: "RUNNING", ownership: "OWNED" },
      liveness: liveProjection({ ok: true, liveness: "alive" }),
      databases: null,
      nativeStatus: null,
      nativeDetail: null,
      supervisor: null,
      queueDepth: 0,
      pythonVersion: "3.12",
    });
    const queue = cards.find((card) => card.id === "queue");
    expect(queue?.state).toBe("HEALTHY");
    expect(queue?.detail).toBe("0 queued");
    expect(queue?.state).not.toBe("UNMEASURED");
  });

  it("test_safe_mode_worker_reason_visible", () => {
    const cards = mapServices({
      host: {
        ...stoppedSnapshot(),
        state: "RUNNING",
        ownership: "OWNED",
        safeModeActive: true,
        systemReadiness: "SAFE_MODE",
      },
      liveness: liveProjection({ ok: true }),
      databases: null,
      nativeStatus: null,
      nativeDetail: null,
      supervisor: null,
      queueDepth: 0,
      pythonVersion: "3.12",
    });
    const workers = cards.find((card) => card.id === "workers");
    expect(workers?.state).toBe("DISABLED BY SAFE MODE");
    expect(toneFor("DISABLED BY SAFE MODE")).toBe("warn");
    expect(mapWorkers({ summary: { running_workers: 0, desired_workers: 0 }, workers: [] }).summary).toBe(
      "DISABLED / NOT CONFIGURED",
    );
  });

  it("classifies fetch errors with status codes", () => {
    expect(classifyFetchError({ status: 503, path: "/api/host/liveness", code: "HTTP_503" })).toEqual({
      code: "HTTP_503",
      detail: "/api/host/liveness returned 503",
    });
    const brief = markTransportError(
      liveProjection({ ok: true }, 10_000),
      new TypeError("Failed to fetch"),
      12_000,
      15_000,
    );
    expect(brief.state).toBe("TRANSPORT_ERROR");
    expect(brief.data?.ok).toBe(true);
  });
});

describe("logs and streams", () => {
  it("filters and redacts structured logs", () => {
    const rows = [
      mapEvent({ sequence: 1, level: "error", subsystem: "native", message: "api_key=abcdef failed", timestamp: "2026-01-01T00:00:00Z" }, 0),
      mapEvent({ sequence: 2, level: "info", subsystem: "http", message: "ok", timestamp: "2026-01-01T00:00:01Z" }, 1),
    ];
    expect(rows[0].message).toContain("[REDACTED]");
    expect(rows[0].message).not.toContain("abcdef");
    expect(filterLogs(rows, "native", "ALL")).toHaveLength(1);
    expect(filterLogs(rows, "", "INFO")).toHaveLength(1);
  });

  it("reconnect delay is bounded and cursor rejects junk", () => {
    expect(nextSseDelay(0)).toBe(500);
    expect(nextSseDelay(20)).toBe(15_000);
    expect(parseSseId("12")).toBe(12);
    expect(parseSseId("nope")).toBeNull();
  });

  it("bounds the ring buffer", () => {
    let items = [{ seq: 1 }, { seq: 2 }];
    items = appendUnique(items, [{ seq: 2 }, { seq: 3 }], 2);
    expect(items.map((item) => item.seq)).toEqual([2, 3]);
    expect(pushRing([1, 2], 3, 2)).toEqual([2, 3]);
  });
});

describe("redaction", () => {
  it("redacts bearer tokens", () => {
    expect(redactText("Authorization: Bearer abcdefghijklmnop")).not.toContain("abcdefghijklmnop");
  });
});
