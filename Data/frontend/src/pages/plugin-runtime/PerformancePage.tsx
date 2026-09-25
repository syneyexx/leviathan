import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { pluginRuntimeHeroes } from "../../assets/pluginRuntimeAssets";
import { api } from "../../api/client";
import { useSystemTelemetry } from "../../hooks/useSystemTelemetry";
import { AppShell } from "../../layouts/AppShell";
import { useAppToast } from "../../state/useAppToast";
import type { CognitionComputeSnapshot, PerformanceSnapshot } from "../../types/api";
import { Bar, Panel, Pill, PrHero, Spark, type PillTone } from "./shared";

function statusPillTone(status: string): PillTone {
  const s = status.toLowerCase();
  if (s === "operational" || s === "healthy" || s === "ok") return "ok";
  if (s === "degraded" || s === "belast" || s === "warning" || s === "experimental") return "gold";
  if (s === "fixture" || s === "unconfigured" || s === "unmeasured") return "muted";
  if (s === "failed" || s === "error" || s === "unavailable") return "err";
  return "muted";
}

function statusLabel(status: string): string {
  const s = status.toLowerCase();
  if (s === "operational" || s === "healthy") return "Operational";
  if (s === "degraded") return "Degraded";
  if (s === "experimental") return "Experimental";
  if (s === "fixture") return "Fixture";
  if (s === "unconfigured") return "Unconfigured";
  if (s === "unmeasured") return "Unmeasured";
  if (s === "unavailable" || s === "stopped") return "Unavailable";
  if (s === "failed") return "Failed";
  return status;
}

function IconBtn({
  label,
  onClick,
  children,
  disabled,
}: {
  label: string;
  onClick: () => void;
  children: ReactNode;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      className="lv-pr-icon-btn"
      aria-label={label}
      title={label}
      onClick={onClick}
      disabled={disabled}
    >
      {children}
    </button>
  );
}

function formatMs(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${Math.round(v)} ms`;
}

export function PerformancePage() {
  const toast = useAppToast();
  const { sample, history, error: telemetryError, refresh: refreshTelemetry } = useSystemTelemetry({
    enabled: true,
    intervalMs: 1500,
  });
  const [snap, setSnap] = useState<PerformanceSnapshot | null>(null);
  const [cognitionCompute, setCognitionCompute] = useState<CognitionComputeSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [typeFilter, setTypeFilter] = useState("Alle types");
  const [statusFilter, setStatusFilter] = useState("Alle statussen");

  const load = useCallback(async () => {
    try {
      const [data, computeRes] = await Promise.all([
        api.performanceSnapshot(),
        api.cognitionCompute().catch(() => null),
      ]);
      setSnap(data);
      if (computeRes?.cognition_compute) {
        setCognitionCompute(computeRes.cognition_compute);
      }
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Performance unavailable");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const id = window.setInterval(() => void load(), 3000);
    return () => window.clearInterval(id);
  }, [load]);

  const cpuSpark = useMemo(() => history.map((h) => h.cpuPct ?? 0), [history]);
  const gpuSpark = useMemo(() => history.map((h) => h.gpuPct ?? 0), [history]);

  const kpis = useMemo(() => {
    const cpu = sample?.dashboard.cpuPct;
    const ram = sample?.dashboard.ramPct;
    const gpu = sample?.dashboard.gpuPct;
    const http = snap?.latency?.http;
    const counters = snap?.metrics?.counters ?? {};
    const gauges = snap?.metrics?.gauges ?? {};
    const jobsQueued = typeof gauges.jobs_queued === "number" ? gauges.jobs_queued : null;
    const errCount = typeof counters["http.errors"] === "number" ? counters["http.errors"] : null;
    const reqCount = typeof counters["http.requests"] === "number" ? counters["http.requests"] : null;

    return [
      {
        id: "cpu",
        label: "CPU gebruik",
        value: cpu == null ? "Unavailable" : `${Math.round(cpu)}%`,
        spark: cpuSpark.length > 1 ? cpuSpark : undefined,
        available: cpu != null,
      },
      {
        id: "ram",
        label: "RAM gebruik",
        value: ram == null ? "Unavailable" : `${Math.round(ram)}%`,
        pct: ram ?? undefined,
        sub:
          sample?.memory?.usedBytes != null && sample?.memory?.totalBytes != null
            ? `${(sample.memory.usedBytes / 1e9).toFixed(1)} GB van ${(sample.memory.totalBytes / 1e9).toFixed(1)} GB`
            : undefined,
        available: ram != null,
      },
      {
        id: "gpu",
        label: "GPU / Accelerator",
        value: gpu == null ? "Unavailable" : `${Math.round(gpu)}%`,
        spark: gpu != null && gpuSpark.length > 1 ? gpuSpark : undefined,
        available: gpu != null,
      },
      {
        id: "workers",
        label: "Jobs queued",
        value: jobsQueued == null ? "—" : String(jobsQueued),
        available: jobsQueued != null,
      },
      {
        id: "latency",
        label: "HTTP p95",
        value: http?.p95 == null ? "—" : formatMs(http.p95),
        available: http?.p95 != null,
      },
      {
        id: "throughput",
        label: "HTTP requests",
        value: reqCount == null ? "—" : String(reqCount),
        sub: "since process start",
        available: reqCount != null,
      },
      {
        id: "error",
        label: "HTTP errors",
        value: errCount == null ? "—" : String(errCount),
        warn: (errCount ?? 0) > 0,
        available: errCount != null,
      },
      {
        id: "uptime",
        label: "Uptime",
        value:
          typeof gauges.uptime_seconds === "number"
            ? `${Math.round(gauges.uptime_seconds)} s`
            : "—",
        available: typeof gauges.uptime_seconds === "number",
      },
    ];
  }, [cpuSpark, gpuSpark, sample, snap]);

  const components = useMemo(() => {
    let rows = snap?.components ?? [];
    if (typeFilter !== "Alle types") {
      rows = rows.filter((c) => c.type === typeFilter);
    }
    if (statusFilter !== "Alle statussen") {
      const want = statusFilter.toLowerCase();
      rows = rows.filter((c) => statusLabel(c.status).toLowerCase() === want || c.status.toLowerCase() === want);
    }
    return rows;
  }, [snap, statusFilter, typeFilter]);

  const typeOptions = useMemo(
    () => ["Alle types", ...Array.from(new Set((snap?.components ?? []).map((c) => c.type)))],
    [snap],
  );

  const hotPaths = snap?.hot_paths ?? [];
  const obs = snap?.observability as { subscribers?: number; durable?: boolean; buffered?: number } | undefined;

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Performance Mode"
      searchPlaceholder="Search components..."
      systemItems={["LLM", "Neural", "Memory", "Runtime"]}
      layout="wide"
      pageClass="lv-app--plugin-runtime"
    >
      <main className="lv-main lv-pr-main">
        <PrHero
          title="Performance"
          kicker="Measured system and application performance — unavailable metrics stay unavailable."
          image={pluginRuntimeHeroes.performance}
        />

        <div className="lv-pr-toolbar">
          <div className="lv-pr-toolbar-left">
            <span className="lv-pr-toolbar-meta">
              {loading ? "Loading…" : error ? error : telemetryError ? telemetryError : "Live samples"}
              {obs?.durable ? " · durable events" : ""}
            </span>
          </div>
          <div className="lv-pr-toolbar-right">
            <IconBtn
              label="Refresh"
              onClick={() => {
                void load();
                void refreshTelemetry();
                toast("Refreshed");
              }}
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M19.5 12a7.5 7.5 0 11-2.2-5.3" />
                <path d="M19.5 5v4.5H15" />
              </svg>
            </IconBtn>
          </div>
        </div>

        <section className="lv-pr-kpi-grid" aria-label="Performance KPIs">
          {kpis.map((k) => (
            <article key={k.id} className={`lv-pr-kpi${k.warn ? " is-warn" : ""}`}>
              <div className="lv-pr-kpi-label">{k.label}</div>
              <div className="lv-pr-kpi-value">
                {k.value}
                {"sub" in k && k.sub ? <span className="lv-pr-kpi-unit"> {k.sub}</span> : null}
              </div>
              <div className="lv-pr-kpi-foot">
                <div className="lv-pr-kpi-meta">
                  {!k.available ? <span className="lv-pr-kpi-sub">Not measured</span> : <span />}
                </div>
                {"pct" in k && typeof k.pct === "number" ? (
                  <Bar pct={k.pct} tone="cyan" className="lv-pr-kpi-bar" />
                ) : k.spark && k.spark.length > 1 ? (
                  <Spark points={k.spark} color={k.warn ? "#F87171" : "#00E5FF"} width={56} height={18} />
                ) : null}
              </div>
            </article>
          ))}
        </section>

        <Panel title="Cognition Compute (two-axis)" className="lv-pr-panel">
          {cognitionCompute ? (
            <div className="lv-pr-kpi-grid" aria-label="Cognition compute">
              <article className="lv-pr-kpi">
                <div className="lv-pr-kpi-label">Orchestration mode</div>
                <div className="lv-pr-kpi-value">
                  {cognitionCompute.orchestration?.effective_mode ??
                    cognitionCompute.orchestration?.mode ??
                    "—"}
                </div>
                <div className="lv-pr-kpi-foot">
                  <span className="lv-pr-kpi-sub">
                    requested {cognitionCompute.orchestration?.requested_mode ?? "—"}
                    {cognitionCompute.orchestration?.clamp_reason
                      ? ` · clamp ${cognitionCompute.orchestration.clamp_reason}`
                      : ""}
                  </span>
                </div>
              </article>
              <article className="lv-pr-kpi">
                <div className="lv-pr-kpi-label">Native effort</div>
                <div className="lv-pr-kpi-value">
                  {cognitionCompute.neural?.native_effort ?? "—"}
                </div>
                <div className="lv-pr-kpi-foot">
                  <span className="lv-pr-kpi-sub">
                    {cognitionCompute.neural?.native_effort == null
                      ? "Unmeasured"
                      : cognitionCompute.neural?.inference_path ?? "neural axis"}
                  </span>
                </div>
              </article>
              <article className="lv-pr-kpi">
                <div className="lv-pr-kpi-label">Max reasoning tokens</div>
                <div className="lv-pr-kpi-value">
                  {cognitionCompute.neural?.max_reasoning_tokens ?? "—"}
                </div>
                <div className="lv-pr-kpi-foot">
                  <span className="lv-pr-kpi-sub">
                    {cognitionCompute.neural?.max_reasoning_tokens == null
                      ? "Unmeasured"
                      : cognitionCompute.neural?.reasoning_tokens_status ?? "budget"}
                  </span>
                </div>
              </article>
              <article className="lv-pr-kpi">
                <div className="lv-pr-kpi-label">Candidates / gain</div>
                <div className="lv-pr-kpi-value">
                  {cognitionCompute.neural?.candidate_count ?? "—"}
                  {cognitionCompute.neural?.expected_gain != null
                    ? ` / ${cognitionCompute.neural.expected_gain.toFixed(2)}`
                    : ""}
                </div>
                <div className="lv-pr-kpi-foot">
                  <span className="lv-pr-kpi-sub">
                    {cognitionCompute.neural?.neural_adaptation ?? "no private CoT"}
                  </span>
                </div>
              </article>
            </div>
          ) : (
            <p className="lv-pr-kpi-sub">
              Unmeasured — cognition compute snapshot not yet available. Unknown stays unknown.
            </p>
          )}
        </Panel>

        <Panel title="Inference Efficiency" className="lv-pr-panel">
          {(() => {
            const eff = snap?.inferenceEfficiency;
            const m = eff?.metrics;
            if (!eff || m == null) {
              return (
                <p className="lv-pr-kpi-sub">
                  Unmeasured — no inference-efficiency samples yet. Unknown stays unknown (not 0%).
                </p>
              );
            }
            const tokLookups = m.tokenization?.lookups ?? null;
            const tokHits = m.tokenization?.hits ?? null;
            const tokRate =
              tokLookups != null && tokLookups > 0 && tokHits != null
                ? `${Math.round((tokHits / tokLookups) * 100)}%`
                : "—";
            const ctxHits = m.contextCompile?.hits ?? null;
            const ctxMiss = m.contextCompile?.misses ?? null;
            const ctxTotal =
              ctxHits != null && ctxMiss != null ? ctxHits + ctxMiss : null;
            const ctxRate =
              ctxTotal != null && ctxTotal > 0 && ctxHits != null
                ? `${Math.round((ctxHits / ctxTotal) * 100)}%`
                : "—";
            const exactShare = m.tokenPrecisionShare?.exact ?? null;
            const heurShare = m.tokenPrecisionShare?.heuristic ?? null;
            const cachedIn = m.cachedInputTokensProviderReported;
            const ttft = m.ttftAvgMs;
            return (
              <div className="lv-pr-kpi-grid" aria-label="Inference efficiency">
                <article className="lv-pr-kpi">
                  <div className="lv-pr-kpi-label">Token cache hit rate</div>
                  <div className="lv-pr-kpi-value">{tokRate}</div>
                  <div className="lv-pr-kpi-foot">
                    <span className="lv-pr-kpi-sub">
                      {tokLookups == null ? "Unmeasured" : `${tokHits}/${tokLookups} lookups`}
                    </span>
                  </div>
                </article>
                <article className="lv-pr-kpi">
                  <div className="lv-pr-kpi-label">Context compile reuse</div>
                  <div className="lv-pr-kpi-value">{ctxRate}</div>
                  <div className="lv-pr-kpi-foot">
                    <span className="lv-pr-kpi-sub">
                      {ctxTotal == null ? "Unmeasured" : `${ctxHits} hits / ${ctxMiss} misses`}
                    </span>
                  </div>
                </article>
                <article className="lv-pr-kpi">
                  <div className="lv-pr-kpi-label">Exact vs heuristic counts</div>
                  <div className="lv-pr-kpi-value">
                    {exactShare == null && heurShare == null
                      ? "—"
                      : `${exactShare ?? 0} / ${heurShare ?? 0}`}
                  </div>
                  <div className="lv-pr-kpi-foot">
                    <span className="lv-pr-kpi-sub">exact / heuristic</span>
                  </div>
                </article>
                <article className="lv-pr-kpi">
                  <div className="lv-pr-kpi-label">Provider cached input tokens</div>
                  <div className="lv-pr-kpi-value">
                    {cachedIn == null ? "—" : String(cachedIn)}
                  </div>
                  <div className="lv-pr-kpi-foot">
                    <span className="lv-pr-kpi-sub">
                      {cachedIn == null ? "Not reported" : "PROVIDER_REPORTED"}
                    </span>
                  </div>
                </article>
                <article className="lv-pr-kpi">
                  <div className="lv-pr-kpi-label">TTFT avg</div>
                  <div className="lv-pr-kpi-value">{ttft == null ? "—" : formatMs(ttft)}</div>
                  <div className="lv-pr-kpi-foot">
                    <span className="lv-pr-kpi-sub">
                      {ttft == null ? "Unmeasured" : "MEASURED"}
                    </span>
                  </div>
                </article>
                <article className="lv-pr-kpi">
                  <div className="lv-pr-kpi-label">Context fit failures</div>
                  <div className="lv-pr-kpi-value">{String(m.contextFitFailures ?? 0)}</div>
                  <div className="lv-pr-kpi-foot">
                    <span className="lv-pr-kpi-sub">
                      caches {eff.policy?.cachesEnabled === false ? "OFF" : "ON"}
                      {eff.policy?.semanticEnabled ? " · semantic ON" : " · semantic OFF"}
                    </span>
                  </div>
                </article>
              </div>
            );
          })()}
        </Panel>

        <div className="lv-pr-grid">
          <Panel title="Component health" className="lv-pr-panel">
            <div className="lv-pr-filters">
              <label>
                Type
                <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
                  {typeOptions.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Status
                <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
                  {[
                    "Alle statussen",
                    "Operational",
                    "Degraded",
                    "Experimental",
                    "Fixture",
                    "Unconfigured",
                    "Unmeasured",
                    "Unavailable",
                    "Failed",
                  ].map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="lv-pr-table-wrap">
              <table className="lv-pr-table">
                <thead>
                  <tr>
                    <th>Component</th>
                    <th>Type</th>
                    <th>Status</th>
                    <th>Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {components.length === 0 ? (
                    <tr>
                      <td colSpan={4}>{loading ? "Loading…" : "No component health signals"}</td>
                    </tr>
                  ) : (
                    components.map((c) => (
                      <tr key={c.id}>
                        <td>{c.name}</td>
                        <td>{c.type}</td>
                        <td>
                          <Pill tone={statusPillTone(c.status)}>{statusLabel(c.status)}</Pill>
                        </td>
                        <td>{c.detail || "—"}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </Panel>

          <Panel title="Hot paths (measured)" className="lv-pr-panel">
            <div className="lv-pr-table-wrap">
              <table className="lv-pr-table">
                <thead>
                  <tr>
                    <th>Path</th>
                    <th>Count</th>
                    <th>Avg</th>
                    <th>p95</th>
                    <th>p99</th>
                  </tr>
                </thead>
                <tbody>
                  {hotPaths.length === 0 ? (
                    <tr>
                      <td colSpan={5}>No latency samples yet — traffic will populate this table.</td>
                    </tr>
                  ) : (
                    hotPaths.map((h) => (
                      <tr key={h.name}>
                        <td>{h.name}</td>
                        <td>{h.count}</td>
                        <td>{formatMs(h.avg_ms)}</td>
                        <td>{formatMs(h.p95_ms)}</td>
                        <td>{formatMs(h.p99_ms)}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </Panel>
        </div>

        <Panel title="Latency percentiles" className="lv-pr-panel">
          <div className="lv-pr-table-wrap">
            <table className="lv-pr-table">
              <thead>
                <tr>
                  <th>Track</th>
                  <th>Count</th>
                  <th>p50</th>
                  <th>p95</th>
                  <th>p99</th>
                  <th>Avg</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(snap?.latency ?? {}).map(([name, stats]) => (
                  <tr key={name}>
                    <td>{name}</td>
                    <td>{stats.count}</td>
                    <td>{formatMs(stats.p50)}</td>
                    <td>{formatMs(stats.p95)}</td>
                    <td>{formatMs(stats.p99)}</td>
                    <td>{formatMs(stats.avg)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </main>
    </AppShell>
  );
}
