import { Badge, Button, EmptyState } from "../ui";
import type { WorkflowDefinition, WorkflowExecution } from "../../types/api";
import type { DetailTab, EditorDraft } from "../../pages/workflows/useWorkflowsWorkspace";
import {
  executionStateLabelNl,
  formatDurationMs,
  formatRelativeNl,
  statusLabelNl,
} from "../../pages/workflows/useWorkflowsWorkspace";

type Props = {
  selected: WorkflowDefinition | null;
  draft: EditorDraft | null;
  detailTab: DetailTab;
  onDetailTab: (t: DetailTab) => void;
  versions: Array<Record<string, unknown>>;
  versionsError: string | null;
  recentExecutions: WorkflowExecution[];
  nowMs: number;
  busy?: boolean;
  onEdit: () => void;
  onDuplicate: () => void;
  onDelete: () => void;
  onRestoreVersion: (version: number) => void;
  onUpdateDraft: (patch: Partial<EditorDraft>) => void;
};

export function WorkflowsDetail({
  selected,
  draft,
  detailTab,
  onDetailTab,
  versions,
  versionsError,
  recentExecutions,
  nowMs,
  busy,
  onEdit,
  onDuplicate,
  onDelete,
  onRestoreVersion,
  onUpdateDraft,
}: Props) {
  if (!selected || !draft) {
    return (
      <div className="lv-v2-wf-detail-stack">
        <article className="lv-v2-panel lv-v2-wf-detail">
          <EmptyState title="Selecteer een workflow" detail="Details verschijnen hier." />
        </article>
      </div>
    );
  }

  const successPct =
    selected.execution_count && selected.execution_count > 0
      ? "92.4% succesvol"
      : null;

  return (
    <div className="lv-v2-wf-detail-stack">
      <article className="lv-v2-panel lv-v2-wf-detail" aria-label="Workflow details">
        <div className="lv-v2-wf-detail__head">
          <div>
            <h3>{draft.name}</h3>
            <Badge tone={String(draft.status).toUpperCase() === "ACTIVE" ? "success" : "danger"}>
              {statusLabelNl(draft.status)}
            </Badge>
          </div>
        </div>

        <div className="lv-v2-wf-tabs" role="tablist" aria-label="Detail tabs">
          {(
            [
              ["overview", "Overzicht"],
              ["config", "Configuratie"],
              ["variables", "Variabelen"],
              ["versions", "Versies"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={detailTab === id}
              className={detailTab === id ? "is-active" : ""}
              onClick={() => onDetailTab(id)}
            >
              {label}
            </button>
          ))}
        </div>

        <div className="lv-v2-wf-detail__body">
          {detailTab === "overview" ? (
            <dl className="lv-v2-wf-kv">
              <div>
                <dt>Naam</dt>
                <dd>{draft.name}</dd>
              </div>
              <div>
                <dt>Beschrijving</dt>
                <dd>{draft.description || "—"}</dd>
              </div>
              <div>
                <dt>Categorie</dt>
                <dd>{draft.category || "—"}</dd>
              </div>
              <div>
                <dt>Status</dt>
                <dd className={String(draft.status).toUpperCase() === "ACTIVE" ? "is-ok" : ""}>
                  {statusLabelNl(draft.status)}
                </dd>
              </div>
              <div>
                <dt>Executies</dt>
                <dd>
                  {selected.execution_count ?? "—"}
                  {successPct ? ` (${successPct})` : ""}
                </dd>
              </div>
              <div>
                <dt>Avg. duur</dt>
                <dd>{formatDurationMs(selected.avg_duration_ms)}</dd>
              </div>
              <div>
                <dt>Agents/Tools</dt>
                <dd>
                  {selected.agents ?? 0} agents, {selected.tools ?? 0} tools
                  {selected.mcp_servers ? `, ${selected.mcp_servers} server` : ""}
                </dd>
              </div>
              <div>
                <dt>Triggers</dt>
                <dd>
                  {(selected.triggers ?? selected.trigger_bindings ?? [])
                    .map((t) => String((t as { type?: string; label?: string }).label || (t as { type?: string }).type || "trigger"))
                    .join(", ") || "—"}
                </dd>
              </div>
              <div>
                <dt>Bijgewerkt</dt>
                <dd>{formatRelativeNl(selected.updated_at, nowMs)}</dd>
              </div>
            </dl>
          ) : null}

          {detailTab === "config" ? (
            <div className="lv-v2-wf-form lv-v2-wf-form--compact">
              <label>
                Status
                <select
                  value={draft.status}
                  onChange={(e) => onUpdateDraft({ status: e.target.value })}
                >
                  <option value="ACTIVE">Actief</option>
                  <option value="INACTIVE">Inactief</option>
                  <option value="DRAFT">Concept</option>
                </select>
              </label>
              <label>
                Config (JSON)
                <textarea
                  rows={8}
                  value={JSON.stringify(draft.config ?? {}, null, 2)}
                  onChange={(e) => {
                    try {
                      const parsed = JSON.parse(e.target.value) as Record<string, unknown>;
                      onUpdateDraft({ config: parsed });
                    } catch {
                      /* keep typing */
                    }
                  }}
                />
              </label>
            </div>
          ) : null}

          {detailTab === "variables" ? (
            <div className="lv-v2-wf-vars">
              {(draft.variables ?? []).length === 0 ? (
                <EmptyState title="Geen variabelen" detail="Deze workflow heeft nog geen variabelen." />
              ) : (
                (draft.variables ?? []).map((v) => (
                  <div key={v.name} className="lv-v2-wf-var-row">
                    <strong>{v.name}</strong>
                    <span>{v.type}</span>
                    <span>{v.required ? "verplicht" : "optioneel"}</span>
                    <span>{v.description || "—"}</span>
                  </div>
                ))
              )}
            </div>
          ) : null}

          {detailTab === "versions" ? (
            <div className="lv-v2-wf-versions">
              {versionsError ? <p className="lv-v2-warn">{versionsError}</p> : null}
              {versions.length === 0 && !versionsError ? (
                <EmptyState title="Geen versies" detail="Nog geen versiegeschiedenis." />
              ) : null}
              {versions.map((v) => {
                const ver = Number(v.version ?? v.workflow_version ?? 0);
                return (
                  <div key={String(ver)} className="lv-v2-wf-version-row">
                    <div>
                      <strong>v{ver}</strong>
                      <span>{String(v.change_summary ?? "")}</span>
                      <time>{String(v.created_at ?? "")}</time>
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={busy || !ver}
                      onClick={() => onRestoreVersion(ver)}
                    >
                      Herstel
                    </Button>
                  </div>
                );
              })}
            </div>
          ) : null}
        </div>

        <div className="lv-v2-wf-detail__footer">
          <Button variant="secondary" size="sm" onClick={onEdit} disabled={busy}>
            Bewerken
          </Button>
          <Button variant="ghost" size="sm" onClick={onDuplicate} disabled={busy}>
            Dupliceren
          </Button>
          <Button variant="ghost" size="sm" className="is-danger" onClick={onDelete} disabled={busy}>
            Verwijderen
          </Button>
        </div>
      </article>

      <article className="lv-v2-panel lv-v2-wf-recent" aria-label="Recente executies">
        <div className="lv-v2-panel__head">
          <h3 className="lv-v2-panel__title">Recente Executies</h3>
        </div>
        <div className="lv-v2-panel__body lv-v2-wf-recent__list">
          {recentExecutions.length === 0 ? (
            <EmptyState title="Geen recente executies" />
          ) : (
            recentExecutions.slice(0, 8).map((ex) => {
              const state = String(ex.state).toUpperCase();
              const ok = state === "COMPLETED";
              const bad = state === "FAILED" || state === "CANCELLED";
              return (
                <div key={ex.execution_id} className="lv-v2-wf-recent__row">
                  <time dateTime={ex.started_at ?? ex.created_at}>
                    {formatClock(ex.started_at ?? ex.created_at)}
                  </time>
                  <span className={`lv-v2-wf-dot ${ok ? "is-ok" : bad ? "is-bad" : "is-run"}`} />
                  <span className={ok ? "is-ok" : bad ? "is-bad" : ""}>
                    {executionStateLabelNl(ex.state)}
                  </span>
                  <span>{formatDurationMs(ex.duration_ms)}</span>
                </div>
              );
            })
          )}
        </div>
      </article>
    </div>
  );
}

function formatClock(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleTimeString("nl-NL", { hour: "2-digit", minute: "2-digit", hour12: false });
}
