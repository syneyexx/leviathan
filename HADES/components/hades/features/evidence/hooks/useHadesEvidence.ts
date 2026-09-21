"use client";

import { useCallback, useMemo } from "react";
import { useHadesQuery, invalidateHadesQuery } from "@/hooks/use-hades-query";
import { hadesApi, type ClaimRecord } from "@/lib/hades-api";

const KEY = "hades:evidence";

export type EvidenceClaimView = {
  id: string;
  title: string;
  topic: string;
  reliability: number | null;
  updated: string;
  status: "verified" | "review" | "conflict";
  statusLabel: string;
  firstSeen: string;
  lastUpdate: string;
  tags: string[];
  summary: string;
  lastValidation: string;
  relatedCount: number;
  provenance: string;
  verificationStatus: string;
  evidenceLinks: Array<Record<string, unknown>>;
  raw: ClaimRecord;
};

function mapStatus(verification: string): {
  status: EvidenceClaimView["status"];
  statusLabel: string;
} {
  const v = String(verification || "").toUpperCase();
  if (v === "SUPPORTED") return { status: "verified", statusLabel: "Geverifieerd" };
  if (v === "CONTRADICTED") return { status: "conflict", statusLabel: "Conflict" };
  if (v === "PARTIALLY_SUPPORTED") return { status: "review", statusLabel: "Gedeeltelijk" };
  if (v === "STALE" || v === "SUPERSEDED") return { status: "review", statusLabel: v === "STALE" ? "Verouderd" : "Vervangen" };
  return { status: "review", statusLabel: "Niet geverifieerd" };
}

function toView(claim: ClaimRecord): EvidenceClaimView {
  const mapped = mapStatus(claim.verification_status);
  const links = Array.isArray(claim.evidence_links) ? claim.evidence_links : [];
  const confidence =
    typeof claim.confidence === "number" && Number.isFinite(claim.confidence)
      ? Math.round(claim.confidence * (claim.confidence <= 1 ? 100 : 1))
      : null;
  const text = String(claim.text || "").trim();
  return {
    id: claim.id,
    title: text.slice(0, 120) || claim.id,
    topic: String(claim.source_kind || claim.provenance || "claim"),
    reliability: confidence,
    updated: String(claim.observed_at || "—"),
    status: mapped.status,
    statusLabel: mapped.statusLabel,
    firstSeen: String(claim.valid_from || claim.observed_at || "—"),
    lastUpdate: String(claim.observed_at || "—"),
    tags: [
      claim.verification_status,
      claim.provenance,
      claim.source_kind,
    ].filter(Boolean) as string[],
    summary: text,
    lastValidation: mapped.statusLabel,
    relatedCount: links.length + (claim.supports?.length || 0) + (claim.contradicts?.length || 0),
    provenance: String(claim.provenance || "—"),
    verificationStatus: String(claim.verification_status || "UNVERIFIED"),
    evidenceLinks: links,
    raw: claim,
  };
}

export function useHadesEvidence(taskId = "") {
  const query = useHadesQuery(
    `${KEY}:${taskId || "all"}`,
    async () => {
      const [claimsRes, pack] = await Promise.all([
        hadesApi.claims(taskId),
        hadesApi.exportKnowledgePack(200).catch(() => null),
      ]);
      return { claims: claimsRes.claims || [], pack };
    },
    { staleTime: 5_000, refetchInterval: 15_000 },
  );

  const claims = query.data?.claims ?? [];
  const pack = query.data?.pack ?? null;
  const cards = useMemo(() => claims.map(toView), [claims]);

  const stats = useMemo(() => {
    const verified = cards.filter((c) => c.status === "verified").length;
    const conflicts = cards.filter((c) => c.status === "conflict").length;
    const review = cards.filter((c) => c.status === "review").length;
    const withConfidence = cards.filter((c) => typeof c.reliability === "number");
    const avgReliability =
      withConfidence.length > 0
        ? Math.round(
            withConfidence.reduce((sum, c) => sum + (c.reliability || 0), 0) / withConfidence.length,
          )
        : null;
    return {
      claims: cards.length,
      verified,
      conflicts,
      review,
      sources: pack?.evidence_count ?? pack?.knowledge_count ?? 0,
      avgReliability,
      evidenceInventory: pack?.evidence ?? [],
    };
  }, [cards, pack]);

  const refresh = useCallback(async () => {
    invalidateHadesQuery(`${KEY}:${taskId || "all"}`);
    return query.refetch();
  }, [query, taskId]);

  return {
    claims,
    cards,
    stats,
    pack,
    loading: query.status === "loading" && !query.data,
    error: query.error,
    refresh,
    reassess: async (id: string) => {
      await hadesApi.reassessClaim(id);
      await refresh();
    },
  };
}
