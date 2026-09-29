import { Link } from "react-router-dom";
import type { BrainOverview } from "../../hooks/useBrainOverview";
import { useKnowledgeActivation } from "../../hooks/useKnowledgeActivation";
import { formatDateTime, prettyTypeLabel } from "../../hooks/useBrainOverview";
import { categoryLabel, categoryForNode } from "../../pages/brain/brain-categories";
import { BrainDnaNetwork } from "../../pages/brain/BrainDnaNetwork";
import { Badge, Button, Panel, ProgressBar } from "../ui";

type Props = {
  overview: BrainOverview;
};

function deepLinkResearch(overview: BrainOverview): string {
  const node = overview.selected;
  if (!node) return "/research";
  if (node.type === "research.project") {
    return `/research?project=${encodeURIComponent(node.id.replace(/^research:project:/, ""))}`;
  }
  return `/research?q=${encodeURIComponent(node.label)}`;
}

function evidenceLink(overview: BrainOverview): string {
  const node = overview.selected;
  if (!node) return "/evidence";
  if (node.type === "evidence" || node.type.startsWith("evidence.")) {
    return `/evidence?evidence=${encodeURIComponent(node.id.replace(/^evidence:/, ""))}`;
  }
  return `/evidence?q=${encodeURIComponent(node.label)}`;
}

export function BrainNetworkSection({ overview }: Props) {
  const {
    nodes,
    edges,
    selectedId,
    setSelectedId,
    selected,
    relatedCount,
    relevancePct,
    linkedMemories,
    linkedMemoriesAvailable,
    evidenceForNode,
    evidenceForNodeAvailable,
    selectedConfidence,
    selectedConfidenceLabel,
    categoryFilter,
    setCategoryFilter,
    graphError,
    graphLoading,
    refresh,
    graphTruth,
  } = overview;

  const { activation, followRequest } = useKnowledgeActivation({ enabled: true });

  const confidenceValue = selectedConfidence ?? (selected ? relevancePct : null);
  const confidenceLabel = selectedConfidenceLabel ?? "Relevantie";
  const description =
    selected && typeof selected.meta?.description === "string"
      ? selected.meta.description
      : selected
        ? "Live projectie-node uit de gezaghebbende Knowledge-, Evidence-, Research- en Memory-stores."
        : "Selecteer een node in het netwerk.";

  const updatedAt =
    selected && typeof selected.meta?.updated_at === "string"
      ? formatDateTime(selected.meta.updated_at)
      : selected?.created_at
        ? formatDateTime(selected.created_at)
        : "—";

  const truncated = Boolean(graphTruth?.bounded_projection);
  const maxNodes = 250;

  return (
    <section className="lv-v2-brain-core" aria-label="Kennisnetwerk">
      <Panel
        className="lv-v2-brain-network-panel"
        title="Kennis Netwerk"
        action={
          <label className="lv-v2-brain-search">
            <span className="lv-v2-sr-only">Zoek in netwerk</span>
            <input
              value={overview.q}
              onChange={(e) => overview.setQ(e.target.value)}
              placeholder="Zoek nodes…"
              aria-label="Zoek nodes"
            />
          </label>
        }
        bodyClassName="lv-v2-brain-network-panel__body"
      >
        <BrainDnaNetwork
          nodes={nodes}
          edges={edges}
          selectedId={selectedId}
          onSelect={setSelectedId}
          categoryFilter={categoryFilter}
          onCategoryFilterChange={setCategoryFilter}
          preferredFocalId={null}
          loading={graphLoading}
          error={graphError}
          onRetry={() => void refresh()}
          activation={activation}
          onFollowRequest={followRequest}
          graphTruncated={truncated}
          graphMaxNodes={maxNodes}
          searchQuery={overview.q}
        />
      </Panel>

      <Panel
        className="lv-v2-brain-selected-panel"
        title="Geselecteerde Node"
        action={
          <Link className="lv-v2-brain-link" to={deepLinkResearch(overview)}>
            Open in Research
          </Link>
        }
      >
        {selected ? (
          <div className="lv-v2-brain-selected">
            <div className="lv-v2-brain-selected__head">
              <div
                className="lv-v2-brain-selected__emblem"
                style={{ ["--lv2-node-color" as string]: `var(--lv2-viz-${categoryForNode(selected)})` }}
                aria-hidden="true"
              >
                {selected.label.slice(0, 1).toUpperCase()}
              </div>
              <div className="lv-v2-brain-selected__identity">
                <h4>{selected.label}</h4>
                <p>{description}</p>
                <Badge tone="info">{categoryLabel(categoryForNode(selected))}</Badge>
              </div>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => void overview.expandNode(selected.id)}
                title="Vouw projectie uit vanaf deze node"
              >
                Editeer
              </Button>
            </div>

            <div className="lv-v2-brain-selected__metric">
              <div className="lv-v2-brain-selected__metric-row">
                <span>{confidenceLabel}</span>
                <strong>{confidenceValue != null ? `${confidenceValue}%` : "—"}</strong>
              </div>
              <ProgressBar value={confidenceValue} label={confidenceLabel} />
            </div>

            <ul className="lv-v2-brain-selected__stats">
              <li>
                <span>Gerelateerde nodes ({relatedCount})</span>
                <button type="button" className="lv-v2-brain-link" onClick={() => overview.setCategoryFilter("all")}>
                  Bekijk links
                </button>
              </li>
              <li>
                <span>
                  Gelinkte geheugens (
                  {linkedMemoriesAvailable ? linkedMemories ?? 0 : "—"})
                </span>
                <Link className="lv-v2-brain-link" to="/memory">
                  Bekijk geheugen
                </Link>
              </li>
              <li>
                <span>
                  Bewijs items ({evidenceForNodeAvailable ? evidenceForNode ?? 0 : "—"})
                </span>
                <Link className="lv-v2-brain-link" to={evidenceLink(overview)}>
                  Bekijk bewijs
                </Link>
              </li>
            </ul>

            <p className="lv-v2-brain-selected__updated">Laatst bijgewerkt {updatedAt}</p>
            <p className="lv-v2-brain-selected__summary">{description}</p>

            <div className="lv-v2-brain-selected__actions">
              <Link className="lv-v2-button lv-v2-button--secondary lv-v2-button--sm" to={`/chat?brain_node=${encodeURIComponent(selected.id)}`}>
                Open in Chat
              </Link>
              <span className="lv-v2-brain-selected__type">{prettyTypeLabel(selected.type)}</span>
            </div>
          </div>
        ) : (
          <p className="lv-v2-muted">{graphLoading ? "Laden…" : "Selecteer een node in het netwerk."}</p>
        )}
      </Panel>
    </section>
  );
}
