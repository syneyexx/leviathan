"use client";

import { useState } from "react";
import { Loader2, RefreshCcw, ShieldCheck } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Panel, StatusBadge, type StatusTone } from "@/components/hades/ui";
import { hadesApi } from "@/lib/hades-api";

type ReleaseReport = {
  overall: string;
  gates: Array<{ id: string; label: string; status: string; detail?: string }>;
  note?: string;
  platform?: string;
  smoke?: Record<string, unknown>;
  what_broke?: Array<{ kind?: string; label?: string } | string>;
  verify_stages?: Array<{ id?: string; label?: string; status?: string; detail?: string }>;
};

function gateTone(status: string): StatusTone {
  if (status === "ok") return "success";
  if (status === "warn") return "warning";
  if (status === "error") return "danger";
  return "neutral";
}

export function ReleaseConfidencePanel({ compact = false }: { compact?: boolean }) {
  const [report, setReport] = useState<ReleaseReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [smokeLoading, setSmokeLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      setReport(await hadesApi.releaseConfidence());
    } catch (reason) {
      setReport(null);
      setError(reason instanceof Error ? reason.message : "Release confidence ophalen mislukt.");
    } finally {
      setLoading(false);
    }
  };

  const runSmoke = async () => {
    if (!window.confirm("Smoke-test kan enkele minuten duren en kan buiten Windows falen. Doorgaan?")) return;
    setSmokeLoading(true);
    setError(null);
    try {
      const result = await hadesApi.releaseConfidenceSmoke(true);
      setReport(result as ReleaseReport);
      toast.message(
        typeof result.smoke === "object" && result.smoke && "ok" in result.smoke && result.smoke.ok
          ? "Smoke geslaagd."
          : "Smoke afgerond — controleer what broke.",
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Smoke-test mislukt.");
    } finally {
      setSmokeLoading(false);
    }
  };

  return (
    <Panel
      title="Release confidence"
      actions={
        <div className="button-row" style={{ flexWrap: "wrap", gap: 8 }}>
          <Button size="sm" variant="outline" onClick={() => void load()} disabled={loading}>
            {loading ? <Loader2 className="spin" /> : <RefreshCcw />}
            Gates
          </Button>
          {!compact ? (
            <Button size="sm" variant="outline" onClick={() => void runSmoke()} disabled={smokeLoading}>
              {smokeLoading ? <Loader2 className="spin" /> : <ShieldCheck />}
              Smoke
            </Button>
          ) : null}
        </div>
      }
    >
      <div className="release-confidence-body">
        <p className="panel-copy">
          {compact
            ? "Lokale release-gates inventaris. Volledige VERIFY draait op Windows."
            : "Inventaris van release gates. Smoke kan lang duren en faalt eerlijk buiten Windows."}
        </p>
        {error ? <div className="inline-error" role="alert">{error}</div> : null}
        {!report && !error ? <p className="empty-copy">Klik Gates om lokale release-inventaris op te halen.</p> : null}
        {report ? (
          <>
            <div className="button-row" style={{ gap: 8, marginBottom: ".5rem" }}>
              <StatusBadge tone={gateTone(report.overall)}>{report.overall}</StatusBadge>
              {report.platform ? <small>Platform: {report.platform}</small> : null}
            </div>
            {report.note ? <p className="panel-copy">{report.note}</p> : null}
            {Array.isArray(report.what_broke) && report.what_broke.length ? (
              <div className="inline-error" role="status" style={{ display: "block", marginBottom: ".75rem" }}>
                <strong>What broke</strong>
                <ul style={{ margin: ".35rem 0 0", paddingLeft: "1.1rem" }}>
                  {report.what_broke.slice(0, 12).map((item, index) => {
                    const kind = typeof item === "string" ? "log" : String(item.kind || "log");
                    const label = typeof item === "string" ? item : String(item.label || "");
                    return (
                      <li key={`${kind}:${label}:${index}`}>
                        <code>{kind}</code> — {label}
                      </li>
                    );
                  })}
                </ul>
              </div>
            ) : null}
            {Array.isArray(report.verify_stages) && report.verify_stages.length ? (
              <div style={{ marginBottom: ".75rem" }}>
                <strong>VERIFY_HADES stages (Windows manueel)</strong>
                <ul className="health-check-list settings-health-list" style={{ marginTop: ".35rem" }}>
                  {report.verify_stages.slice(0, 20).map((stage, index) => (
                    <li key={`${stage.id || stage.label || index}`}>
                      <StatusBadge tone={gateTone(String(stage.status || "manual"))}>{String(stage.status || "manual")}</StatusBadge>
                      <div>
                        <strong>{String(stage.id || `stage-${index + 1}`)}</strong>
                        {stage.label || stage.detail ? <small>{String(stage.label || stage.detail)}</small> : null}
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            <ul className="health-check-list settings-health-list">
              {report.gates.map((gate) => (
                <li key={gate.id}>
                  <StatusBadge tone={gateTone(gate.status)}>{gate.status}</StatusBadge>
                  <div>
                    <strong>{gate.label}</strong>
                    {gate.detail ? <small>{gate.detail}</small> : null}
                  </div>
                </li>
              ))}
            </ul>
            {report.smoke ? (
              <pre className="release-smoke-log">{JSON.stringify(report.smoke, null, 2)}</pre>
            ) : null}
          </>
        ) : null}
      </div>
    </Panel>
  );
}
