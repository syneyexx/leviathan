import { CheckCircle2, FlaskConical, Loader2, PlayCircle, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Panel, StatusBadge } from "@/components/hades/ui";
import { traceSummary } from "./helpers";
import type { PracticeResult, PracticeScenario } from "./types";

type AgentPracticePanelProps = {
  scenarios: PracticeScenario[];
  results: Record<string, PracticeResult>;
  loading: boolean;
  running: string | null;
  onRun: (scenarioId: string) => void;
  onRunAll: () => void;
};

export function AgentPracticePanel({
  scenarios,
  results,
  loading,
  running,
  onRun,
  onRunAll,
}: AgentPracticePanelProps) {
  return (
    <Panel
      className="mt-3"
      title="Practice playground"
      eyebrow="Deterministische scenario's A–E"
      actions={
        <Button
          size="sm"
          variant="outline"
          disabled={loading || running !== null || !scenarios.length}
          onClick={onRunAll}
        >
          {running === "all" ? <Loader2 className="spin" /> : <PlayCircle />}
          Run all
        </Button>
      }
    >
      {loading ? (
        <div className="table-empty"><Loader2 className="spin muted-icon" /> Scenario&apos;s laden…</div>
      ) : scenarios.length ? (
        <div className="practice-grid">
          {scenarios.map((scenario) => {
            const result = results[scenario.id];
            const scenarioRunning = running === scenario.id;
            return (
              <div className="practice-card" key={scenario.id}>
                <div className="practice-card-head">
                  <span className="practice-scenario-id">{scenario.id}</span>
                  <StatusBadge tone="neutral">{scenario.kind}</StatusBadge>
                  {result ? (
                    <StatusBadge tone={result.passed ? "success" : "danger"}>
                      {result.passed ? <CheckCircle2 className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}
                      {result.passed ? "Geslaagd" : "Mislukt"}
                    </StatusBadge>
                  ) : null}
                </div>
                <strong className="practice-card-title">{scenario.title}</strong>
                <p className="practice-card-copy">{scenario.description}</p>
                {result ? (
                  <div className="practice-result">
                    {result.notes.length ? (
                      <p className="practice-notes">{result.notes.join(" ")}</p>
                    ) : null}
                    <p className="practice-trace" title={JSON.stringify(result.trace, null, 2)}>
                      <FlaskConical className="h-3 w-3 shrink-0" />
                      {traceSummary(result.trace)}
                    </p>
                  </div>
                ) : null}
                <Button
                  size="sm"
                  variant="outline"
                  className="practice-run-btn"
                  disabled={running !== null}
                  onClick={() => onRun(scenario.id)}
                >
                  {scenarioRunning ? <Loader2 className="spin" /> : <PlayCircle />}
                  Uitvoeren
                </Button>
              </div>
            );
          })}
        </div>
      ) : (
        <p className="empty-copy">Geen practice-scenario&apos;s beschikbaar van de backend.</p>
      )}
    </Panel>
  );
}
