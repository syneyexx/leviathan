import { Dialog } from "../ui";
import type { WorkflowRecord } from "../../types/api";
import type { ModalKind } from "../../pages/workflows/useWorkflowsWorkspace";

type Props = {
  modal: ModalKind;
  busy?: boolean;
  createName: string;
  createDesc: string;
  onCreateName: (v: string) => void;
  onCreateDesc: (v: string) => void;
  templates: WorkflowRecord[];
  createFromTemplateId: string | null;
  onCreateFromTemplateId: (id: string | null) => void;
  selectedName?: string;
  onClose: () => void;
  onCreate: () => void;
  onDelete: () => void;
  onDiscardUnsaved: () => void;
  onOpenCreate: () => void;
};

export function WorkflowsModals({
  modal,
  busy,
  createName,
  createDesc,
  onCreateName,
  onCreateDesc,
  templates,
  createFromTemplateId,
  onCreateFromTemplateId,
  selectedName,
  onClose,
  onCreate,
  onDelete,
  onDiscardUnsaved,
  onOpenCreate,
}: Props) {
  return (
    <>
      <Dialog
        open={modal === "create"}
        title="Nieuwe workflow"
        description="Maak een lege workflow of start vanuit een template."
        confirmLabel="Aanmaken"
        cancelLabel="Annuleren"
        busy={busy}
        onClose={onClose}
        onConfirm={onCreate}
      >
        <div className="lv-v2-wf-form">
          <label>
            Naam
            <input value={createName} onChange={(e) => onCreateName(e.target.value)} placeholder="Research Pipeline" />
          </label>
          <label>
            Beschrijving
            <textarea rows={3} value={createDesc} onChange={(e) => onCreateDesc(e.target.value)} />
          </label>
          <label>
            Template (optioneel)
            <select
              value={createFromTemplateId ?? ""}
              onChange={(e) => onCreateFromTemplateId(e.target.value || null)}
            >
              <option value="">Geen template</option>
              {templates.map((t) => (
                <option key={t.workflow_id} value={t.workflow_id}>
                  {t.name}
                </option>
              ))}
            </select>
          </label>
        </div>
      </Dialog>

      <Dialog
        open={modal === "templates"}
        title="Templates"
        description="Kies een template om een nieuwe workflow te starten."
        confirmLabel="Gebruik template"
        cancelLabel="Sluiten"
        busy={busy}
        onClose={onClose}
        onConfirm={() => {
          if (!createFromTemplateId && templates[0]) {
            onCreateFromTemplateId(templates[0].workflow_id);
            onCreateName(`${templates[0].name} (kopie)`);
          }
          onOpenCreate();
        }}
      >
        <ul className="lv-v2-wf-template-list">
          {templates.length === 0 ? <li className="lv-v2-muted">Geen templates beschikbaar</li> : null}
          {templates.map((t) => (
            <li key={t.workflow_id}>
              <button
                type="button"
                className={createFromTemplateId === t.workflow_id ? "is-selected" : ""}
                onClick={() => {
                  onCreateFromTemplateId(t.workflow_id);
                  onCreateName(`${t.name} (kopie)`);
                  onCreateDesc(t.description ?? "");
                }}
              >
                <strong>{t.name}</strong>
                <span>{t.description || t.category || "Template"}</span>
              </button>
            </li>
          ))}
        </ul>
      </Dialog>

      <Dialog
        open={modal === "delete"}
        title="Workflow verwijderen"
        description={`Weet je zeker dat je “${selectedName ?? "deze workflow"}” wilt verwijderen? Dit archiveert de definitie.`}
        confirmLabel="Verwijderen"
        cancelLabel="Annuleren"
        danger
        busy={busy}
        onClose={onClose}
        onConfirm={onDelete}
      />

      <Dialog
        open={modal === "unsaved"}
        title="Niet-opgeslagen wijzigingen"
        description="Je hebt wijzigingen die nog niet zijn opgeslagen. Wil je doorgaan zonder op te slaan?"
        confirmLabel="Wijzigingen verwerpen"
        cancelLabel="Blijven"
        danger
        busy={busy}
        onClose={onClose}
        onConfirm={onDiscardUnsaved}
      />
    </>
  );
}
