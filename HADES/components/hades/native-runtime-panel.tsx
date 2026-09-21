"use client";

import { useCallback, useEffect, useState } from "react";
import { Activity, Loader2, RefreshCcw, RotateCcw } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Panel, StatusBadge } from "@/components/hades/ui";
import { NativeRuntimeStatus, hadesApi } from "@/lib/hades-api";

/**
 * Truthful native companion status. Never invents token/s or GPU metrics.
 * Native supervision is process/resource control — not an OS sandbox.
 */
export function NativeRuntimePanel() {
  const [status, setStatus] = useState<NativeRuntimeStatus | null>(null);
  const [metrics, setMetrics] = useState<Record<string, unknown> | null>(null);
  const [benchmark, setBenchmark] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const next = await hadesApi.nativeStatus();
      setStatus(next);
      if (next.connected) {
        try {
          const m = await hadesApi.nativeMetrics();
          setMetrics(m.metrics);
        } catch {
          setMetrics(null);
        }
      } else {
        setMetrics(null);
      }
    } catch (reason) {
      setStatus(null);
      toast.error(reason instanceof Error ? reason.message : "Native status onbereikbaar.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const restart = async () => {
    setBusy(true);
    try {
      const next = await hadesApi.nativeRestart();
      setStatus(next);
      if (next.connected) toast.success("Native runtime herstart.");
      else toast.error("Native runtime niet verbonden na herstart.");
      await load();
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Herstarten mislukt.");
    } finally {
      setBusy(false);
    }
  };

  const runBenchmark = async () => {
    setBusy(true);
    try {
      const result = await hadesApi.nativeBenchmark();
      setBenchmark(result.result);
      if (!result.available) {
        toast.message(result.note || "Native runtime niet beschikbaar voor benchmark.");
      } else {
        const row = (result.result || {}) as Record<string, unknown>;
        const hasTiming =
          typeof row.python_process_echo_ms === "number"
          || typeof row.native_process_echo_ms === "number";
        if (hasTiming) {
          toast.success("Native micro-benchmark afgerond.");
        } else {
          toast.message("Native runtime beschikbaar, maar geen echo-timings gemeten.");
        }
      }
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Benchmark mislukt.");
    } finally {
      setBusy(false);
    }
  };

  const tone = !status
    ? "danger"
    : status.connected
      ? "success"
      : status.available
        ? "warning"
        : "neutral";

  return (
    <Panel
      title="Native supervised runtime"
      actions={
        <StatusBadge tone={tone}>
          {!status ? "Offline" : status.connected ? "Verbonden" : status.available ? "Beschikbaar" : "Afwezig"}
        </StatusBadge>
      }
    >
      <p className="panel-copy">
        Optionele C++20 companion voor process/service-supervisie en snelle filesystem-operaties.
        Geen OS-sandbox: policy blijft application-level. Python-fallback blijft actief wanneer native uitstaat of ontbreekt.
      </p>
      {loading ? (
        <div className="page-state">
          <Loader2 className="spin" /> Native status laden…
        </div>
      ) : (
        <dl className="detail-list spaced">
          <div>
            <dt>Modus</dt>
            <dd>{status?.mode ?? "—"}</dd>
          </div>
          <div>
            <dt>Binary</dt>
            <dd className="break-path">{status?.executable || "Niet gevonden (runtime/native/)"}</dd>
          </div>
          <div>
            <dt>Versie</dt>
            <dd>{status?.version || "—"}</dd>
          </div>
          <div>
            <dt>Protocol</dt>
            <dd>{status?.protocol_version ?? "—"}</dd>
          </div>
          <div>
            <dt>Uptime</dt>
            <dd>{status?.uptime_ms != null ? `${Math.round(status.uptime_ms / 1000)} s` : "—"}</dd>
          </div>
          <div>
            <dt>Fallback</dt>
            <dd>{status?.fallback_active ? "Actief (Python)" : "Native pad"}</dd>
          </div>
          <div>
            <dt>Capabilities</dt>
            <dd>{status?.capabilities?.length ? status.capabilities.join(", ") : "—"}</dd>
          </div>
          {status?.last_error ? (
            <div>
              <dt>Laatste fout</dt>
              <dd>{status.last_error}</dd>
            </div>
          ) : null}
          {metrics ? (
            <div>
              <dt>Metrics</dt>
              <dd>
                <code>{JSON.stringify(metrics)}</code>
              </dd>
            </div>
          ) : null}
          {benchmark ? (
            <div>
              <dt>Laatste benchmark</dt>
              <dd>
                <code>{JSON.stringify(benchmark)}</code>
              </dd>
            </div>
          ) : null}
        </dl>
      )}
      <div className="button-row" style={{ marginTop: "0.75rem", flexWrap: "wrap", gap: 8 }}>
        <Button variant="outline" onClick={() => void load()} disabled={loading || busy}>
          {loading ? <Loader2 className="spin" /> : <RefreshCcw />} Vernieuwen
        </Button>
        <Button variant="outline" onClick={() => void restart()} disabled={busy}>
          {busy ? <Loader2 className="spin" /> : <RotateCcw />} Runtime herstarten
        </Button>
        <Button variant="outline" onClick={() => void runBenchmark()} disabled={busy}>
          {busy ? <Loader2 className="spin" /> : <Activity />} Micro-benchmark
        </Button>
      </div>
    </Panel>
  );
}
