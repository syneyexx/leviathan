import { useState } from "react";
import { Button, Dialog, Panel } from "../ui";
import type { MemoryWorkspace } from "../../hooks/useMemoryWorkspace";
import type { MemoryKind } from "../../types/api";

export function MemoryDialogs({ ws }: { ws: MemoryWorkspace }) {
  const [draftContent, setDraftContent] = useState("");
  const [draftKind, setDraftKind] = useState<MemoryKind>("NOTE");
  const [draftTags, setDraftTags] = useState("");
  const [draftScope, setDraftScope] = useState<"GLOBAL" | "PROJECT" | "CONVERSATION">("GLOBAL");
  const [draftProject, setDraftProject] = useState("");
  const [correctContent, setCorrectContent] = useState("");
  const [convId, setConvId] = useState("");
  const [convContent, setConvContent] = useState("");
  const [convFromAssistant, setConvFromAssistant] = useState(false);

  return (
    <>
      <Dialog
        open={ws.createOpen}
        title="Nieuwe notitie"
        description="Maak een gecontroleerde Memory. Model-output is geen automatische FACT."
        confirmLabel="Opslaan"
        busy={ws.busy}
        onClose={() => ws.setCreateOpen(false)}
        onConfirm={() => {
          void ws.createNote({
            content: draftContent,
            kind: draftKind,
            tags: draftTags
              .split(",")
              .map((t) => t.trim())
              .filter(Boolean),
            scope: draftScope,
            project_id: draftScope === "PROJECT" ? draftProject || null : null,
            source: "manual",
            trust: "explicit",
          });
        }}
      >
        <div className="lv-v2-memory-form">
          <label>
            Inhoud
            <textarea
              className="lv-v2-input" 
              rows={5}
              value={draftContent}
              onChange={(e) => setDraftContent(e.target.value)}
            />
          </label>
          <label>
            Kind
            <select
              className="lv-v2-select"
              value={draftKind}
              onChange={(e) => setDraftKind(e.target.value as MemoryKind)}
            >
              {["NOTE", "FACT", "PREFERENCE", "EPISODIC", "DECISION", "PROCEDURE", "SUMMARY", "PROJECT"].map(
                (k) => (
                  <option key={k} value={k}>
                    {k}
                  </option>
                ),
              )}
            </select>
          </label>
          <label>
            Scope
            <select
              className="lv-v2-select"
              value={draftScope}
              onChange={(e) => setDraftScope(e.target.value as typeof draftScope)}
            >
              <option value="GLOBAL">GLOBAL</option>
              <option value="PROJECT">PROJECT</option>
            </select>
          </label>
          {draftScope === "PROJECT" ? (
            <label>
              Project ID
              <input
                className="lv-v2-input" 
                value={draftProject}
                onChange={(e) => setDraftProject(e.target.value)}
              />
            </label>
          ) : null}
          <label>
            Tags (comma)
            <input
              className="lv-v2-input" 
              value={draftTags}
              onChange={(e) => setDraftTags(e.target.value)}
              placeholder="pinned, topic"
            />
          </label>
        </div>
      </Dialog>

      <Dialog
        open={ws.correctOpen && Boolean(ws.detail)}
        title="Memory corrigeren"
        description="Maakt een CORRECTION die de oude record supersedes — content wordt niet in-place gemuteerd."
        confirmLabel="Corrigeer"
        busy={ws.busy}
        onClose={() => ws.setCorrectOpen(false)}
        onConfirm={() => {
          if (ws.detail) void ws.correct(ws.detail.memory_id, correctContent);
        }}
      >
        <textarea
          className="lv-v2-input" 
          rows={5}
          value={correctContent}
          onChange={(e) => setCorrectContent(e.target.value)}
          placeholder="Nieuwe inhoud"
        />
      </Dialog>

      <Dialog
        open={ws.conversationOpen}
        title="Van gesprek opslaan"
        description="Selecteer expliciet content. Assistant-output wordt niet als FACT opgeslagen."
        confirmLabel="Opslaan"
        busy={ws.busy}
        onClose={() => ws.setConversationOpen(false)}
        onConfirm={() => {
          void ws.saveFromConversation({
            conversation_id: convId,
            content: convContent,
            kind: convFromAssistant ? "EPISODIC" : "NOTE",
            from_assistant: convFromAssistant,
          });
        }}
      >
        <div className="lv-v2-memory-form">
          <label>
            Conversatie
            <select
              className="lv-v2-select"
              value={convId}
              onChange={(e) => setConvId(e.target.value)}
            >
              <option value="">Kies…</option>
              {ws.conversations.map((c) => (
                <option key={c.id} value={c.id}>
                  {(c.title || c.id || "conversation").slice(0, 60)}
                </option>
              ))}
            </select>
          </label>
          <label>
            Content
            <textarea
              className="lv-v2-input" 
              rows={4}
              value={convContent}
              onChange={(e) => setConvContent(e.target.value)}
            />
          </label>
          <label className="lv-v2-check">
            <input
              type="checkbox"
              checked={convFromAssistant}
              onChange={(e) => setConvFromAssistant(e.target.checked)}
            />
            Afkomstig van assistant (trust=derived, nooit FACT)
          </label>
        </div>
      </Dialog>

      <Dialog
        open={ws.processingSettingsOpen}
        title="Verwerkingsinstellingen"
        description="Canonical Settings Control Plane — geen localStorage."
        confirmLabel="Sluiten"
        onClose={() => ws.setProcessingSettingsOpen(false)}
        onConfirm={() => ws.setProcessingSettingsOpen(false)}
      >
        <p className="lv-v2-muted">
          Wijzigingen via de Automatische Verwerking switches worden direct naar Settings
          geschreven (`memory.processing.*`).
        </p>
        {ws.processing ? (
          <pre className="lv-v2-memory-settings-pre">{JSON.stringify(ws.processing, null, 2)}</pre>
        ) : null}
      </Dialog>

      {ws.detailOpen && ws.detail ? (
        <aside className="lv-v2-memory-drawer" role="dialog" aria-label="Memory detail">
          <div className="lv-v2-memory-drawer__head">
            <h3>Memory detail</h3>
            <Button variant="ghost" size="sm" onClick={() => ws.setDetailOpen(false)}>
              Sluiten
            </Button>
          </div>
          <Panel title={ws.detail.kind} meta={ws.detail.status}>
            <p className="lv-v2-memory-drawer__content">{ws.detail.content}</p>
            <dl className="lv-v2-memory-kv">
              <div>
                <dt>ID</dt>
                <dd>{ws.detail.memory_id}</dd>
              </div>
              <div>
                <dt>Scope</dt>
                <dd>{ws.detail.scope}</dd>
              </div>
              <div>
                <dt>Trust</dt>
                <dd>{ws.detail.trust}</dd>
              </div>
              <div>
                <dt>Source</dt>
                <dd>{ws.detail.source}</dd>
              </div>
              <div>
                <dt>Tags</dt>
                <dd>{(ws.detail.tags || []).join(", ") || "—"}</dd>
              </div>
              <div>
                <dt>Priority</dt>
                <dd>{ws.detail.priority ?? "—"}</dd>
              </div>
              <div>
                <dt>Actor</dt>
                <dd>{ws.detail.actor || "—"}</dd>
              </div>
              <div>
                <dt>Supersedes</dt>
                <dd>{ws.detail.supersedes_id || "—"}</dd>
              </div>
              <div>
                <dt>Semantic</dt>
                <dd>
                  {ws.detail.semantic_index
                    ? JSON.stringify({
                        provider: (ws.detail.semantic_index as { provider_id?: string }).provider_id,
                        stale: (ws.detail.semantic_index as { stale?: boolean }).stale,
                      })
                    : "not indexed"}
                </dd>
              </div>
            </dl>
            <div className="lv-v2-memory-drawer__actions">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => void ws.togglePin(ws.detail!.memory_id, Boolean(ws.detail!.pinned))}
              >
                {ws.detail.pinned ? "Unpin" : "Pin"}
              </Button>
              <Button variant="secondary" size="sm" onClick={() => ws.setCorrectOpen(true)}>
                Correct
              </Button>
              {ws.detail.status === "ARCHIVED" ? (
                <Button variant="secondary" size="sm" onClick={() => void ws.restore(ws.detail!.memory_id)}>
                  Restore
                </Button>
              ) : (
                <Button variant="secondary" size="sm" onClick={() => void ws.archive(ws.detail!.memory_id)}>
                  Archive
                </Button>
              )}
              <Button variant="ghost" size="sm" onClick={() => void ws.revoke(ws.detail!.memory_id)}>
                Revoke
              </Button>
              <a
                className="lv-v2-button lv-v2-button--secondary lv-v2-button--sm"
                href={`/brain?types=memory&focus=${encodeURIComponent(ws.detail.memory_id)}`}
              >
                Brain
              </a>
            </div>
          </Panel>
        </aside>
      ) : null}
    </>
  );
}
