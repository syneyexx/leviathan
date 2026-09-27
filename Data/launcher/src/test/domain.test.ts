import { describe, expect, it } from "vitest";
import { controlGates } from "../domain/controls";
import { mapServices, toneFor } from "../domain/health";
import { mapIngestion } from "../domain/ingestion";
import { filterLogs, mapEvent } from "../domain/logs";
import { mapNative, nativeIsHealthy } from "../domain/native";
import { metricCards, readPerformance, emptyHistories } from "../domain/telemetry";
import { mapWorker } from "../domain/workers";
import { stoppedSnapshot } from "../domain/host";
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
