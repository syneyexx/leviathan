import { Check, ExternalLink, FileText, Network, Pin, Plus, Sparkles, Tag, Trash2, ZoomIn } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { BrainNodeIcon } from "./brain-node-icon";
import { KIND_LABELS, RELATION_OPTIONS } from "./brain-graph-adapter";
import type { GraphLink, GraphNode } from "./brain-graph-adapter";

type DetailsTab = "overview" | "relations" | "metadata";

type BrainInspectorProps = {
  selectedNode: GraphNode | undefined;
  selectedLinks: GraphLink[];
  relatedNodes: GraphNode[];
  totalLinks: number;
  zoom: number;
  detailsTab: DetailsTab;
  editing: boolean;
  draftLabel: string;
  draftDescription: string;
  busy?: boolean;
  relationTargetId: string;
  relationType: string;
  relationCandidates: GraphNode[];
  onSelectNode: (id: string) => void;
  onDetailsTab: (tab: DetailsTab) => void;
  onRelationTargetId: (id: string) => void;
  onRelationType: (value: string) => void;
  onAddRelation: () => void;
  onUpdateRelation: (link: GraphLink, nextRelation: string) => void;
  onDeleteRelation: (link: GraphLink) => void;
  onTogglePin: () => void;
  onStartEditing: () => void;
  onCancelEditing: () => void;
  onSaveEditing: () => void;
  onDraftLabel: (value: string) => void;
  onDraftDescription: (value: string) => void;
  onDelete?: () => void;
  onOpenTarget?: () => void;
};

export function BrainInspector({
  selectedNode,
  selectedLinks,
  relatedNodes,
  totalLinks,
  zoom,
  detailsTab,
  editing,
  draftLabel,
  draftDescription,
  busy = false,
  relationTargetId,
  relationType,
  relationCandidates,
  onSelectNode,
  onDetailsTab,
  onRelationTargetId,
  onRelationType,
  onAddRelation,
  onUpdateRelation,
  onDeleteRelation,
  onTogglePin,
  onStartEditing,
  onCancelEditing,
  onSaveEditing,
  onDraftLabel,
  onDraftDescription,
  onDelete,
  onOpenTarget,
}: BrainInspectorProps) {
  const contentEditable = Boolean(selectedNode?.contentEditable);
  const layoutMovable = Boolean(selectedNode?.layoutMovable);
  return (
    <aside className="b2-inspector">
      <section className="b2-card b2-node-summary">
        <div className="b2-card-title">
          <h2>{selectedNode?.label ?? "HADES"}</h2>
          <span className={`b2-kind-badge kind-${selectedNode?.kind ?? "core"}`}>
            {selectedNode ? KIND_LABELS[selectedNode.kind] : "Kern"}
          </span>
        </div>
        {selectedNode ? (
          <>
            <div className="b2-summary-hero">
              <span className={`b2-summary-icon kind-${selectedNode.kind}`}>
                <BrainNodeIcon kind={selectedNode.icon} />
              </span>
              <div>
                <strong>{selectedNode.label}</strong>
                <span>
                  {selectedNode.id === "core_hades"
                    ? "Centrale orchestratie node"
                    : `${KIND_LABELS[selectedNode.kind]} node`}
                </span>
                <small>Bijgewerkt op {selectedNode.updatedAt}</small>
              </div>
            </div>
            {editing ? (
              <div className="b2-edit-fields">
                <Input value={draftLabel} onChange={(event) => onDraftLabel(event.target.value)} aria-label="Node naam" disabled={busy} />
                <textarea
                  value={draftDescription}
                  onChange={(event) => onDraftDescription(event.target.value)}
                  aria-label="Node beschrijving"
                  disabled={busy}
                />
                <div>
                  <Button variant="outline" onClick={onCancelEditing} disabled={busy}>
                    Annuleren
                  </Button>
                  <Button onClick={onSaveEditing} disabled={busy}>
                    Opslaan
                  </Button>
                </div>
              </div>
            ) : (
              <p>{selectedNode.description}</p>
            )}
            <div className="b2-tabs" role="tablist" aria-label="Node details">
              <button type="button" role="tab" aria-selected={detailsTab === "overview"} className={detailsTab === "overview" ? "active" : ""} onClick={() => onDetailsTab("overview")}>
                Overzicht
              </button>
              <button type="button" role="tab" aria-selected={detailsTab === "relations"} className={detailsTab === "relations" ? "active" : ""} onClick={() => onDetailsTab("relations")}>
                Relaties
              </button>
              <button type="button" role="tab" aria-selected={detailsTab === "metadata"} className={detailsTab === "metadata" ? "active" : ""} onClick={() => onDetailsTab("metadata")}>
                Metadata
              </button>
            </div>
            {detailsTab === "overview" ? (
              <dl className="b2-stats">
                <div>
                  <dt>Directe relaties</dt>
                  <dd>{selectedLinks.length}</dd>
                </div>
                <div>
                  <dt>Totaal relaties</dt>
                  <dd>{totalLinks}</dd>
                </div>
                <div>
                  <dt>Tags</dt>
                  <dd>{selectedNode.tags.length}</dd>
                </div>
                <div>
                  <dt>Type</dt>
                  <dd>{selectedNode.source}</dd>
                </div>
              </dl>
            ) : null}
            {detailsTab === "relations" ? (
              <div className="b2-tab-copy">{selectedLinks.length} directe koppelingen. Kies doel én type vóór nieuwe relatie.</div>
            ) : null}
            {detailsTab === "metadata" ? (
              <div className="b2-tab-copy">
                Node ID: <code>{selectedNode.id}</code>
                <br />
                Bron: {selectedNode.source}
                <br />
                Cluster: {selectedNode.cluster}
                <br />
                Inhoud bewerkbaar: {contentEditable ? "ja" : "nee"}
                <br />
                Layout verplaatsbaar: {layoutMovable ? "ja" : "nee"}
                <br />
                Vastgezet: {selectedNode.pinned ? "ja" : "nee"}
              </div>
            ) : null}
          </>
        ) : null}
      </section>

      <section className="b2-card b2-relations-card">
        <div className="b2-section-heading">
          <h3>Gerelateerde nodes ({relatedNodes.length})</h3>
        </div>
        <div className="b2-relation-create" aria-label="Nieuwe relatie">
          <Select value={relationTargetId || (relationCandidates[0]?.id ?? "")} onValueChange={onRelationTargetId}>
            <SelectTrigger aria-label="Doelnode">
              <SelectValue placeholder="Kies doelnode" />
            </SelectTrigger>
            <SelectContent>
              {relationCandidates.map((node) => (
                <SelectItem key={node.id} value={node.id}>
                  {node.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={relationType} onValueChange={onRelationType}>
            <SelectTrigger aria-label="Relatietype">
              <SelectValue placeholder="Relatietype" />
            </SelectTrigger>
            <SelectContent>
              {RELATION_OPTIONS.map((option) => (
                <SelectItem key={option} value={option}>
                  {option}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button variant="outline" size="icon" onClick={onAddRelation} aria-label="Relatie toevoegen" disabled={busy || !relationCandidates.length}>
            <Plus />
          </Button>
        </div>
        <div className="b2-related-list">
          {selectedLinks.map((link) => {
            const otherId = link.source === selectedNode?.id ? link.target : link.source;
            const node = relatedNodes.find((item) => item.id === otherId);
            if (!node) return null;
            return (
              <div key={link.id} className="b2-relation-row">
                <button type="button" onClick={() => onSelectNode(node.id)}>
                  <span className={`b2-related-icon kind-${node.kind}`}>
                    <BrainNodeIcon kind={node.icon} />
                  </span>
                  <span>
                    <strong>{node.label}</strong>
                    <small>{KIND_LABELS[node.kind]}</small>
                  </span>
                </button>
                <Select value={link.relation} onValueChange={(value) => onUpdateRelation(link, value)} disabled={busy}>
                  <SelectTrigger aria-label={`Relatie naar ${node.label}`}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {[link.relation, ...RELATION_OPTIONS.filter((option) => option !== link.relation)].map((option) => (
                      <SelectItem key={option} value={option}>
                        {option}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button variant="outline" size="icon" aria-label="Relatie verwijderen" onClick={() => onDeleteRelation(link)} disabled={busy}>
                  <Trash2 />
                </Button>
              </div>
            );
          })}
          {!relatedNodes.length ? <p className="b2-empty">Nog geen relaties voor deze node.</p> : null}
        </div>
      </section>

      <section className="b2-card b2-properties-card">
        <div className="b2-section-heading">
          <h3>Eigenschappen</h3>
          <div className="b2-property-actions">
            {selectedNode?.openHref ? (
              <Button variant="outline" onClick={onOpenTarget} disabled={busy}>
                <ExternalLink />
                Openen
              </Button>
            ) : null}
            {layoutMovable ? (
              <Button variant="outline" onClick={onTogglePin} disabled={busy} aria-label={selectedNode?.pinned ? "Losmaken" : "Vastzetten"}>
                <Pin />
                {selectedNode?.pinned ? "Losmaken" : "Vastzetten"}
              </Button>
            ) : null}
            {contentEditable ? (
              <>
                <Button variant="outline" onClick={editing ? onSaveEditing : onStartEditing} disabled={busy}>
                  {editing ? "Opslaan" : "Bewerken"}
                </Button>
                <Button variant="outline" onClick={onDelete} disabled={busy || editing} aria-label="Node verwijderen">
                  <Trash2 />
                </Button>
              </>
            ) : null}
          </div>
        </div>
        {selectedNode ? (
          <div className="b2-properties">
            <span>
              <Tag />
              <strong>Type</strong>
              <em className={`b2-kind-badge kind-${selectedNode.kind}`}>{KIND_LABELS[selectedNode.kind]}</em>
            </span>
            <span>
              <Check />
              <strong>Persistent</strong>
              <em>{selectedNode.persistent ? "Ja" : "Nee"}</em>
            </span>
            <span>
              <ZoomIn />
              <strong>Zoom</strong>
              <em>{Math.round(zoom * 100)}%</em>
            </span>
            <span>
              <Network />
              <strong>Node ID</strong>
              <code>{selectedNode.id}</code>
            </span>
            <span>
              <FileText />
              <strong>Aangemaakt</strong>
              <em>{selectedNode.createdAt}</em>
            </span>
            <span>
              <Sparkles />
              <strong>Laatst gewijzigd</strong>
              <em>{selectedNode.updatedAt}</em>
            </span>
          </div>
        ) : null}
      </section>
    </aside>
  );
}
