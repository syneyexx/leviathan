import type { ReactNode } from "react";
import type {
  AgentDefinition,
  CapabilityListItem,
  KnowledgeDocument,
  ModelDescriptor,
} from "../../types/api";
import {
  AGENT_KINDS,
  APPROVAL_MODES,
  DATASET_ACCESS_POLICIES,
  MEMORY_POLICIES,
  ORCH_FAILURE_STRATEGIES,
  ORCH_STRATEGIES,
  type AgentEditorDraft,
} from "./helpers";
import { Modal } from "./agentsUi";

function Field({
  label,
  children,
  hint,
}: {
  label: string;
  children: ReactNode;
  hint?: string;
}) {
  return (
    <label className="lv-ag-field">
      <span>{label}</span>
      {children}
      {hint ? <small className="lv-ag-field-hint">{hint}</small> : null}
    </label>
  );
}

export function AgentEditorForm({
  draft,
  setDraft,
  agents,
  models,
  capabilities,
  knowledgeDocs,
  editingId,
}: {
  draft: AgentEditorDraft;
  setDraft: (next: AgentEditorDraft) => void;
  agents: AgentDefinition[];
  models: ModelDescriptor[];
  capabilities: CapabilityListItem[];
  knowledgeDocs: KnowledgeDocument[];
  editingId?: string;
}) {
  const memberCandidates = agents.filter(
    (a) => !a.archived && a.agentId !== editingId,
  );

  function toggleCap(id: string) {
    const has = draft.capabilities.includes(id);
    setDraft({
      ...draft,
      capabilities: has
        ? draft.capabilities.filter((c) => c !== id)
        : [...draft.capabilities, id],
    });
  }

  function toggleMember(id: string) {
    const has = draft.memberAgentIds.includes(id);
    setDraft({
      ...draft,
      memberAgentIds: has
        ? draft.memberAgentIds.filter((m) => m !== id)
        : [...draft.memberAgentIds, id],
    });
  }

  function toggleKnowledge(id: string) {
    const has = draft.knowledgeSources.includes(id);
    setDraft({
      ...draft,
      knowledgeSources: has
        ? draft.knowledgeSources.filter((k) => k !== id)
        : [...draft.knowledgeSources, id],
    });
  }

  return (
    <div className="lv-ag-editor-grid">
      <Field label="Name">
        <input
          type="text"
          value={draft.name}
          onChange={(e) => setDraft({ ...draft, name: e.target.value })}
          required
        />
      </Field>
      <Field label="Kind">
        <select
          value={draft.kind}
          onChange={(e) => setDraft({ ...draft, kind: e.target.value })}
          disabled={Boolean(editingId)}
        >
          {AGENT_KINDS.map((k) => (
            <option key={k} value={k}>
              {k}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Role">
        <input
          type="text"
          value={draft.role}
          onChange={(e) => setDraft({ ...draft, role: e.target.value })}
          placeholder="e.g. Research / Analysis"
        />
      </Field>
      <Field label="Enabled">
        <input
          type="checkbox"
          checked={draft.enabled}
          onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })}
        />
      </Field>
      <Field label="Description" hint="Shown in roster and inspector">
        <textarea
          rows={2}
          value={draft.description}
          onChange={(e) => setDraft({ ...draft, description: e.target.value })}
        />
      </Field>
      <Field
        label="Model"
        hint="Canonical modelRef from registry — empty means inherit/default runtime semantics"
      >
        <select
          value={draft.modelRef}
          onChange={(e) => setDraft({ ...draft, modelRef: e.target.value })}
        >
          <option value="">(inherit / unset)</option>
          {models.map((m) => (
            <option key={m.id} value={m.id}>
              {m.displayName || m.id}
            </option>
          ))}
        </select>
      </Field>
      <Field
        label="System policy"
        hint="Stored on definition; execution still goes through ExecutionGateway"
      >
        <textarea
          rows={2}
          value={draft.systemPolicy}
          onChange={(e) => setDraft({ ...draft, systemPolicy: e.target.value })}
        />
      </Field>
      <Field label="Approval mode">
        <select
          value={draft.approvalMode}
          onChange={(e) => setDraft({ ...draft, approvalMode: e.target.value })}
        >
          {APPROVAL_MODES.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      </Field>
      <Field
        label={`Autonomy (${draft.autonomy})`}
        hint="Config metadata 0–100 — not a guarantee of independent tool execution"
      >
        <input
          type="range"
          min={0}
          max={100}
          value={draft.autonomy}
          onChange={(e) => setDraft({ ...draft, autonomy: Number(e.target.value) })}
        />
      </Field>
      <Field label="Max concurrency">
        <input
          type="number"
          min={1}
          max={32}
          value={draft.maxConcurrency}
          onChange={(e) => setDraft({ ...draft, maxConcurrency: Number(e.target.value) })}
        />
      </Field>
      <Field label="Timeout (s)">
        <input
          type="number"
          min={1}
          placeholder="optional"
          value={draft.timeoutS}
          onChange={(e) => setDraft({ ...draft, timeoutS: e.target.value })}
        />
      </Field>
      <Field label="Max retries">
        <input
          type="number"
          min={0}
          max={10}
          value={draft.maxRetries}
          onChange={(e) => setDraft({ ...draft, maxRetries: Number(e.target.value) })}
        />
      </Field>
      <Field label="Token budget">
        <input
          type="number"
          min={1}
          placeholder="optional"
          value={draft.tokenBudget}
          onChange={(e) => setDraft({ ...draft, tokenBudget: e.target.value })}
        />
      </Field>
      <Field label="Memory policy">
        <select
          value={draft.memoryPolicy}
          onChange={(e) => setDraft({ ...draft, memoryPolicy: e.target.value })}
        >
          {MEMORY_POLICIES.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      </Field>
      <Field
        label="Dataset access"
        hint="Policy field on the agent definition — not a per-dataset assignment list"
      >
        <select
          value={draft.datasetAccess}
          onChange={(e) => setDraft({ ...draft, datasetAccess: e.target.value })}
        >
          {DATASET_ACCESS_POLICIES.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Tags (comma-separated)">
        <input
          type="text"
          value={draft.tags}
          onChange={(e) => setDraft({ ...draft, tags: e.target.value })}
        />
      </Field>

      <div className="lv-ag-editor-block">
        <h3>Capabilities</h3>
        <p className="lv-ag-field-hint">
          Assigned capability IDs only. Saving persists via PATCH/create — runtime still
          executes through the shared ExecutionGateway.
        </p>
        <div className="lv-ag-check-grid">
          {capabilities.length === 0 ? (
            <p className="lv-ag-empty">Capability registry unavailable or empty.</p>
          ) : (
            capabilities.map((c) => {
              const id = typeof c.id === "string" ? c.id : "";
              if (!id) return null;
              const label = typeof c.name === "string" && c.name ? c.name : id;
              return (
                <label key={id} className="lv-ag-check">
                  <input
                    type="checkbox"
                    checked={draft.capabilities.includes(id)}
                    onChange={() => toggleCap(id)}
                  />
                  <span>{label}</span>
                </label>
              );
            })
          )}
        </div>
      </div>

      <div className="lv-ag-editor-block">
        <h3>Knowledge sources</h3>
        <div className="lv-ag-check-grid">
          {knowledgeDocs.length === 0 ? (
            <p className="lv-ag-empty">No knowledge documents loaded.</p>
          ) : (
            knowledgeDocs.map((doc) => (
              <label key={doc.id} className="lv-ag-check">
                <input
                  type="checkbox"
                  checked={draft.knowledgeSources.includes(doc.id)}
                  onChange={() => toggleKnowledge(doc.id)}
                />
                <span>{doc.title || doc.id}</span>
              </label>
            ))
          )}
        </div>
      </div>

      {draft.kind === "orchestrator" ? (
        <div className="lv-ag-editor-block lv-ag-editor-orch">
          <h3>Orchestrator configuration</h3>
          <div className="lv-ag-editor-grid is-dense">
            <Field label="Strategy">
              <select
                value={draft.strategy}
                onChange={(e) => setDraft({ ...draft, strategy: e.target.value })}
              >
                {ORCH_STRATEGIES.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </Field>
            <Field
              label="Failure strategy"
              hint="fail_fast stops on first child failure; continue runs remaining members"
            >
              <select
                value={draft.failureStrategy}
                onChange={(e) => setDraft({ ...draft, failureStrategy: e.target.value })}
              >
                {ORCH_FAILURE_STRATEGIES.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Max delegation depth">
              <input
                type="number"
                min={1}
                max={16}
                value={draft.maxDelegationDepth}
                onChange={(e) =>
                  setDraft({ ...draft, maxDelegationDepth: Number(e.target.value) })
                }
              />
            </Field>
            <Field label="Parallelism limit">
              <input
                type="number"
                min={1}
                max={32}
                value={draft.parallelismLimit}
                onChange={(e) =>
                  setDraft({ ...draft, parallelismLimit: Number(e.target.value) })
                }
              />
            </Field>
            <Field label="Approval escalation">
              <select
                value={draft.approvalEscalation}
                onChange={(e) => setDraft({ ...draft, approvalEscalation: e.target.value })}
              >
                {APPROVAL_MODES.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Verification required">
              <input
                type="checkbox"
                checked={draft.verificationRequired}
                onChange={(e) =>
                  setDraft({ ...draft, verificationRequired: e.target.checked })
                }
              />
            </Field>
            <Field label="Aggregation agent">
              <select
                value={draft.aggregationAgentId}
                onChange={(e) => setDraft({ ...draft, aggregationAgentId: e.target.value })}
              >
                <option value="">(none)</option>
                {memberCandidates.map((a) => (
                  <option key={a.agentId} value={a.agentId}>
                    {a.name} ({a.kind})
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Default model fallback">
              <select
                value={draft.defaultModelFallback}
                onChange={(e) =>
                  setDraft({ ...draft, defaultModelFallback: e.target.value })
                }
              >
                <option value="">(none)</option>
                {models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.displayName || m.id}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <h4>Members</h4>
          <div className="lv-ag-check-grid">
            {memberCandidates.length === 0 ? (
              <p className="lv-ag-empty">No eligible member agents.</p>
            ) : (
              memberCandidates.map((a) => (
                <label key={a.agentId} className="lv-ag-check">
                  <input
                    type="checkbox"
                    checked={draft.memberAgentIds.includes(a.agentId)}
                    onChange={() => toggleMember(a.agentId)}
                  />
                  <span>
                    {a.name}{" "}
                    <em>
                      ({a.kind}
                      {a.kind === "orchestrator" ? " · nested" : ""}
                      {!a.enabled ? " · disabled" : ""})
                    </em>
                  </span>
                </label>
              ))
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}

export function AgentEditorModal({
  mode,
  draft,
  setDraft,
  agents,
  models,
  capabilities,
  knowledgeDocs,
  editingId,
  busy,
  onSave,
  onClose,
}: {
  mode: "create" | "edit";
  draft: AgentEditorDraft;
  setDraft: (next: AgentEditorDraft) => void;
  agents: AgentDefinition[];
  models: ModelDescriptor[];
  capabilities: CapabilityListItem[];
  knowledgeDocs: KnowledgeDocument[];
  editingId?: string;
  busy: boolean;
  onSave: () => void;
  onClose: () => void;
}) {
  return (
    <Modal
      title={mode === "create" ? "Create Agent" : `Edit ${draft.name}`}
      onClose={onClose}
      footer={
        <>
          <span className="lv-ag-field-hint">
            {mode === "edit" ? "Persists via PATCH /api/agents/{id}" : "Persists via POST /api/agents"}
          </span>
          <button type="button" className="lv-ag-btn-gold" disabled={busy} onClick={onSave}>
            {mode === "create" ? "Create" : "Save changes"}
          </button>
        </>
      }
    >
      <AgentEditorForm
        draft={draft}
        setDraft={setDraft}
        agents={agents}
        models={models}
        capabilities={capabilities}
        knowledgeDocs={knowledgeDocs}
        editingId={mode === "edit" ? editingId : undefined}
      />
    </Modal>
  );
}
