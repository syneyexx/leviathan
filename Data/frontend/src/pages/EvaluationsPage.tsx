import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import { Button, EmptyState, ErrorState, LoadingState } from "../components/ui";
import { AppShell } from "../layouts/AppShell";
import { useAppToast } from "../state/useAppToast";

type EvaluationReportRow = {
  id?: string;
  report_id?: string;
  suite_id?: string;
  suiteId?: string;
  status?: string;
  created_at?: string;
  createdAt?: string;
  summary?: string;
  [key: string]: unknown;
};

const SUITE_RUNNERS: Array<{ id: string; path: string; label: string }> = [
  { id: "neuro", path: "neuro", label: "Neuro evaluation" },
  { id: "foundation", path: "foundation", label: "Foundation" },
  { id: "serving", path: "serving", label: "Serving conformance" },
  { id: "assistant", path: "assistant", label: "Assistant benchmark" },
  { id: "regression", path: "regression", label: "Regression" },
];

function reportId(row: EvaluationReportRow): string {
  return String(row.id || row.report_id || "");
}

function reportSuite(row: EvaluationReportRow): string {
  return String(row.suite_id || row.suiteId || "—");
}

function reportWhen(row: EvaluationReportRow): string {
  const raw = row.created_at || row.createdAt;
  if (!raw || typeof raw !== "string") return "UNMEASURED";
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return raw;
  return d.toLocaleString("nl-NL");
}

/**
 * Minimal Hades AI / Evaluations V2 surface over real /api/evaluation/* endpoints.
 */
export function EvaluationsPage() {
  const toast = useAppToast();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reports, setReports] = useState<EvaluationReportRow[]>([]);
  const [running, setRunning] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.listEvaluationReports(50);
      const rows = Array.isArray(res.reports) ? (res.reports as EvaluationReportRow[]) : [];
      setReports(rows);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Kon evaluation reports niet laden");
      setReports([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function runSuite(path: string, label: string) {
    setRunning(path);
    try {
      if (path === "neuro") {
        await api.neuroEvaluation();
      } else {
        await api.runEvaluationSuite(path);
      }
      toast(`${label} gequeued`);
      await refresh();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : `${label} mislukt`);
    } finally {
      setRunning(null);
    }
  }

  return (
    <AppShell
      variant="v2"
      v2Title="Hades AI / Evaluations"
      v2Subtitle="Evaluation reports en suite runners — backend-backed, geen mock scores."
      v2Refreshing={loading}
      onV2Refresh={() => {
        void refresh();
      }}
    >
      <main className="lv-v2-page">
        <section className="lv-v2-panel" aria-labelledby="eval-run-title">
          <div className="lv-v2-panel__head">
            <h2 className="lv-v2-panel__title" id="eval-run-title">
              Suite runners
            </h2>
            <span className="lv-v2-panel__meta">POST /api/evaluation/…</span>
          </div>
          <div className="lv-v2-panel__body" style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {SUITE_RUNNERS.map((suite) => (
              <Button
                key={suite.id}
                variant="secondary"
                size="sm"
                loading={running === suite.path}
                disabled={running != null}
                onClick={() => void runSuite(suite.path, suite.label)}
              >
                {suite.label}
              </Button>
            ))}
          </div>
        </section>

        <section className="lv-v2-panel" aria-labelledby="eval-reports-title" style={{ marginTop: 12 }}>
          <div className="lv-v2-panel__head">
            <h2 className="lv-v2-panel__title" id="eval-reports-title">
              Reports
            </h2>
            <span className="lv-v2-panel__meta">GET /api/evaluation/reports</span>
          </div>
          <div className="lv-v2-panel__body">
            {loading ? <LoadingState label="Reports laden…" /> : null}
            {!loading && error ? <ErrorState title="Laden mislukt" detail={error} /> : null}
            {!loading && !error && reports.length === 0 ? (
              <EmptyState
                title="Geen reports"
                detail="Nog geen persisted evaluation reports. Queue een suite hierboven (vereist evaluation worker)."
              />
            ) : null}
            {!loading && !error && reports.length > 0 ? (
              <ul className="lv-v2-list" style={{ listStyle: "none", padding: 0, margin: 0 }}>
                {reports.map((row, index) => {
                  const id = reportId(row) || `row-${index}`;
                  return (
                    <li key={id} className="lv-v2-list-row" style={{ cursor: "default" }}>
                      <span>
                        <strong>{reportSuite(row)}</strong>
                        <span className="lv-v2-muted" style={{ display: "block", fontSize: 12 }}>
                          {id !== `row-${index}` ? id : "zonder id"} · {reportWhen(row)}
                          {row.status ? ` · ${String(row.status)}` : ""}
                        </span>
                        {typeof row.summary === "string" && row.summary ? (
                          <span className="lv-v2-muted" style={{ display: "block", fontSize: 12 }}>
                            {row.summary}
                          </span>
                        ) : null}
                      </span>
                    </li>
                  );
                })}
              </ul>
            ) : null}
          </div>
        </section>
      </main>
    </AppShell>
  );
}
