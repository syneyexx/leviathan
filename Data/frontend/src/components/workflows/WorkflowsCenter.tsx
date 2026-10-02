import { Badge, Button, EmptyState, ErrorState, LoadingState } from "../ui";
import type { WorkflowDefinition, WorkflowExecution, WorkflowPalette } from "../../types/api";
import type { CenterTab, EditorDraft } from "../../pages/workflows/useWorkflowsWorkspace";
import {
  executionStateLabelNl,
  formatDurationMs,
  formatRelativeNl,
  statusLabelNl,
} from "../../pages/workflows/useWorkflowsWorkspace";
import { WorkflowsCanvas } from "./WorkflowsCanvas";

type Props = {
  selected: WorkflowDefinition | null;
  draft: EditorDraft | null;
  dirty: boolean;
  busy?: boolean;
  loading?: boolean;
  centerTab: CenterTab;
  onCenterTab: (t: CenterTab) => void;
  palette: WorkflowPalette | null;
  executions: WorkflowExecution[];
  executionsError: string | null;
  logs: Array<Record<string, unknown>>;
  logsError: string | null;
  nowMs: number;
  onSave: () => void;
  onRun: () => void;
  onResumeExecution?: (executionId: string) => void;
  onUpdateDraft: (patch: Partial<EditorDraft>) => void;
  onGraphChange: EditorDraft extends never
    ? never
    : (graph: EditorDraft["graph"], layout: EditorDraft["layout"]) => void;
};

export function WorkflowsCenter({
  selected,
  draft,
  dirty,
  busy,
  loading,
  centerTab,
  onCenterTab,
  palette,
  executions,
  executionsError,
  logs,
  logsError,
  nowMs,
  onSave,
  onRun,
  onResumeExecution,
  onUpdateDraft,
  onGraphChange,
}: Props) {
  if (!selected || !draft) {
    return (
      <article className="lv-v2-panel lv-v2-wf-center">
        <EmptyState title="Geen workflow geselecteerd" detail="Kies een workflow uit de bibliotheek." />
      </article>
    );
  }

  return (
    <article className="lv-v2-panel lv-v2-wf-center" aria-label="Workflow editor">
      <div className="lv-v2-wf-center__head">
        <div className="lv-v2-wf-center__title">
          <h3>{draft.name || selected.name}</h3>
          <Badge tone={String(draft.status).toUpperCase() === "ACTIVE" ? "success" : "danger"}>
            {statusLabelNl(draft.status)}
          </Badge>
          {dirty ? <span className="lv-v2-wf-dirty">Niet opgeslagen</span> : null}
        </div>
        <div className="lv-v2-wf-center__actions">
          <Button variant="secondary" size="sm" onClick={onSave} disabled={busy || !dirty}>
            Opslaan
          </Button>
          <Button variant="primary" size="sm" onClick={onRun} disabled={busy}>
            Uitvoeren
          </Button>
        </div>
      </div>

      <div className="lv-v2-wf-tabs" role="tablist" aria-label="Editor tabs">
        {(
          [
            ["canvas", "Canvas"],
            ["config", "Configuratie"],
            ["executions", "Executies"],
            ["logs", "Logs"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={centerTab === id}
            className={centerTab === id ? "is-active" : ""}
            onClick={() => onCenterTab(id)}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="lv-v2-wf-center__body">
        {centerTab === "canvas" ? (
          <WorkflowsCanvas
            graph={draft.graph}
            layout={draft.layout}
            palette={palette}
            onChange={onGraphChange}
          />
        ) : null}

        {centerTab === "config" ? (
          <div className="lv-v2-wf-form">
            <label>
              Naam
              <input
                value={draft.name}
                onChange={(e) => onUpdateDraft({ name: e.target.value })}
              />
            </label>
            <label>
              Beschrijving
              <textarea
                rows={3}
                value={draft.description}
                onChange={(e) => onUpdateDraft({ description: e.target.value })}
              />
            </label>
            <label>
              Categorie
              <input
                value={draft.category}
                onChange={(e) => onUpdateDraft({ category: e.target.value })}
              />
            </label>
            <label>
              Status
              <select
                value={draft.status}
                onChange={(e) => onUpdateDraft({ status: e.target.value })}
              >
                <option value="ACTIVE">Actief</option>
                <option value="INACTIVE">Inactief</option>
                <option value="DRAFT">Concept</option>
                <option value="TEMPLATE">Template</option>
              </select>
            </label>
          </div>
        ) : null}

        {centerTab === "executions" ? (
          <div className="lv-v2-wf-exec-list">
            {executionsError ? <ErrorState title="Executies" detail={executionsError} /> : null}
            {loading && executions.length === 0 ? <LoadingState label="Executies laden…" /> : null}
            {!executionsError && executions.length === 0 && !loading ? (
              <EmptyState title="Geen executies" detail="Voer de workflow uit om resultaten te zien." />
            ) : null}
            {executions.map((ex) => (
              <div key={ex.execution_id} className="lv-v2-wf-exec-row">
                <span className={`lv-v2-wf-dot is-${String(ex.state).toLowerCase()}`} />
                <span className="lv-v2-wf-exec-row__state">{executionStateLabelNl(ex.state)}</span>
                <time dateTime={ex.started_at ?? ex.created_at}>
                  {formatRelativeNl(ex.started_at ?? ex.created_at, nowMs)}
                </time>
                <span>{formatDurationMs(ex.duration_ms)}</span>
                {String(ex.state).toUpperCase() === "WAITING_APPROVAL" && onResumeExecution ? (
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={busy}
                    onClick={() => onResumeExecution(ex.execution_id)}
                  >
                    Hervatten
                  </Button>
                ) : null}
              </div>
            ))}
          </div>
        ) : null}

        {centerTab === "logs" ? (
          <div className="lv-v2-wf-logs">
            {logsError ? <ErrorState title="Logs" detail={logsError} /> : null}
            {!logsError && logs.length === 0 ? (
              <EmptyState title="Geen logs" detail="Nog geen logregels voor deze workflow." />
            ) : null}
            {logs.map((line, i) => (
              <div key={i} className="lv-v2-wf-log-line">
                <time>{String(line.ts ?? line.timestamp ?? "")}</time>
                <span className={`lv-v2-wf-log-level is-${String(line.level || "info").toLowerCase()}`}>
                  {String(line.level || "INFO")}
                </span>
                <span>{String(line.message ?? line.msg ?? JSON.stringify(line))}</span>
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </article>
  );
}
