"use client";

import { useCallback, useRef, useState } from "react";
import { fetchBrainNodeDetail } from "@/lib/brain-node-detail-api";
import type { BrainNodeDetail } from "@/lib/brain-node-detail-api";
import type { GraphNode } from "./brain-graph-adapter";
import { BrainNodeDetailDialog } from "./brain-node-detail-dialog";

export function useBrainNodeDetail() {
  const [open, setOpen] = useState(false);
  const [node, setNode] = useState<GraphNode | undefined>();
  const [detail, setDetail] = useState<BrainNodeDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestSeq = useRef(0);

  const load = useCallback(async (target: GraphNode) => {
    const seq = ++requestSeq.current;
    setNode(target);
    setOpen(true);
    setLoading(true);
    setError(null);
    setDetail(null);
    try {
      const payload = await fetchBrainNodeDetail(target.id);
      if (seq !== requestSeq.current) return;
      setDetail(payload);
    } catch (reason) {
      if (seq !== requestSeq.current) return;
      setError(reason instanceof Error ? reason.message : "Node-detail kon niet worden geladen.");
    } finally {
      if (seq === requestSeq.current) setLoading(false);
    }
  }, []);

  const onOpenChange = useCallback((nextOpen: boolean) => {
    setOpen(nextOpen);
    if (!nextOpen) requestSeq.current += 1;
  }, []);

  const openTarget = useCallback(() => {
    const href = detail?.open_href || node?.openHref;
    if (!href) return;
    setOpen(false);
    window.location.hash = href.replace(/^#/, "");
  }, [detail?.open_href, node?.openHref]);

  const dialog = (
    <BrainNodeDetailDialog
      open={open}
      onOpenChange={onOpenChange}
      detail={detail}
      fallbackNode={node}
      loading={loading}
      error={error}
      onRetry={() => { if (node) void load(node); }}
      onOpenTarget={openTarget}
    />
  );

  return { openNodeDetail: load, detailDialog: dialog };
}
