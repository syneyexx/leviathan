"use client";

import { AlertTriangle, ExternalLink, FileText, Loader2, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { BrainNodeDetail } from "@/lib/brain-node-detail-api";
import type { GraphNode } from "./brain-graph-adapter";
import "./brain-node-detail-dialog.css";

type BrainNodeDetailDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  detail: BrainNodeDetail | null;
  fallbackNode?: GraphNode;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  onOpenTarget: () => void;
};

const formatDate = (value?: string | null) => {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("nl-NL");
};

const formatMetadataValue = (value: unknown) => {
  if (value == null || value === "") return "—";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value, null, 2);
};

export function BrainNodeDetailDialog({
  open,
  onOpenChange,
  detail,
  fallbackNode,
  loading,
  error,
  onRetry,
  onOpenTarget,
}: BrainNodeDetailDialogProps) {
  const title = detail?.title || fallbackNode?.label || "Brain-node";
  const description = detail?.description || fallbackNode?.description || "Volledige opgeslagen informatie van deze node.";
  const kind = detail?.kind || fallbackNode?.kind || "node";
  const hasTarget = Boolean(detail?.open_href || fallbackNode?.openHref);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="brain-detail-dialog" aria-describedby="brain-node-detail-description">
        <DialogHeader className="brain-detail-header">
          <div className="brain-detail-eyebrow">
            <span>{kind}</span>
            {detail?.status ? <span>{detail.status}</span> : null}
            {detail?.source ? <span>{detail.source}</span> : null}
          </div>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription id="brain-node-detail-description">{description}</DialogDescription>
        </DialogHeader>

        {loading ? (
          <div className="brain-detail-state" role="status">
            <Loader2 className="animate-spin" />
            <div><strong>Inhoud laden…</strong><span>HADES leest de opgeslagen informatie achter deze node.</span></div>
          </div>
        ) : error ? (
          <div className="brain-detail-state brain-detail-state--error" role="alert">
            <AlertTriangle />
            <div><strong>Detail kon niet worden geladen</strong><span>{error}</span></div>
            <Button variant="outline" size="sm" onClick={onRetry}><RefreshCw />Opnieuw proberen</Button>
          </div>
        ) : detail ? (
          <div className="brain-detail-body">
            <div className="brain-detail-facts">
              <div><span>Bron</span><strong>{detail.source || "—"}</strong></div>
              <div><span>Aangemaakt</span><strong>{formatDate(detail.created_at)}</strong></div>
              <div><span>Bijgewerkt</span><strong>{formatDate(detail.updated_at)}</strong></div>
              <div><span>Inhoud</span><strong>{detail.returned_chars.toLocaleString("nl-NL")} tekens</strong></div>
            </div>

            {detail.source_uri ? (
              <div className="brain-detail-source">
                <span>Bronlocatie</span>
                {/^https?:\/\//i.test(detail.source_uri) ? (
                  <a href={detail.source_uri} target="_blank" rel="noreferrer noopener">{detail.source_uri}<ExternalLink /></a>
                ) : <code>{detail.source_uri}</code>}
              </div>
            ) : null}

            {detail.truncated ? (
              <div className="brain-detail-warning">
                <AlertTriangle />
                <span>Deze bron is uitzonderlijk groot. De detailweergave is begrensd om de interface responsief te houden.</span>
              </div>
            ) : null}

            <div className="brain-detail-sections">
              {detail.sections.length ? detail.sections.map((section, index) => (
                <section key={`${section.title}-${index}`} className="brain-detail-section">
                  <header>
                    <FileText />
                    <div><strong>{section.title}</strong>{Object.keys(section.metadata || {}).length ? <small>{Object.entries(section.metadata).map(([key, value]) => `${key}: ${formatMetadataValue(value)}`).join(" · ")}</small> : null}</div>
                  </header>
                  <pre>{section.content || "Geen tekstinhoud opgeslagen."}</pre>
                </section>
              )) : (
                <div className="brain-detail-empty">Geen aanvullende tekstinhoud opgeslagen voor deze node.</div>
              )}
            </div>

            {Object.keys(detail.metadata || {}).length ? (
              <details className="brain-detail-metadata">
                <summary>Metadata bekijken</summary>
                <dl>
                  {Object.entries(detail.metadata).map(([key, value]) => (
                    <div key={key}><dt>{key}</dt><dd><pre>{formatMetadataValue(value)}</pre></dd></div>
                  ))}
                </dl>
              </details>
            ) : null}
          </div>
        ) : null}

        <DialogFooter className="brain-detail-footer">
          {hasTarget ? <Button variant="outline" onClick={onOpenTarget}><ExternalLink />Open gekoppelde pagina</Button> : null}
          <Button onClick={() => onOpenChange(false)}>Sluiten</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
