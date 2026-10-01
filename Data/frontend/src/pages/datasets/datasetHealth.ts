/**
 * Catalog-wide health items + UNMEASURED bar rendering helpers.
 * Never use page-local inventory as catalog health truth.
 */

import type { DatasetOverview } from "../../types/api";

export type HealthItem = {
  id: string;
  label: string;
  pct: number | null;
  hint: string;
  tone: "green" | "teal" | "blue" | "orange";
};

export function buildCatalogHealthItems(overview: DatasetOverview | null): HealthItem[] {
  if (!overview) {
    return [
      {
        id: "ready",
        label: "Ready Coverage",
        pct: null,
        hint: "UNMEASURED (overview unavailable)",
        tone: "green",
      },
      {
        id: "schema",
        label: "Schema Validation",
        pct: null,
        hint: "UNMEASURED (overview unavailable)",
        tone: "teal",
      },
      {
        id: "embedding",
        label: "Embedding Coverage",
        pct: null,
        hint: "UNMEASURED (overview unavailable)",
        tone: "blue",
      },
      {
        id: "offline",
        label: "Offline Availability",
        pct: null,
        hint: "UNMEASURED (overview unavailable)",
        tone: "orange",
      },
    ];
  }

  const total = overview.totalDatasets ?? 0;
  const ready = overview.readyDatasets ?? overview.byStatus?.ready ?? null;
  const withVal = overview.datasetsWithValidation ?? overview.versionsWithValidation ?? null;
  const withoutVal =
    overview.datasetsWithoutValidation ??
    (withVal != null && total > 0 ? Math.max(0, total - withVal) : null);
  const indexed = overview.indexedDatasets ?? null;
  const local = overview.localDatasets ?? null;
  const unknown =
    (overview.byStatus?.unknown ?? 0) +
    (overview.byStatus?.UNKNOWN ?? 0) +
    Object.entries(overview.byStatus ?? {}).reduce((sum, [k, v]) => {
      const key = k.toLowerCase();
      if (key === "unknown" || key === "unmeasured") return sum;
      if (
        ["ready", "offline", "failed", "processing", "validating", "created", "raw", "archived"].includes(
          key,
        )
      ) {
        return sum;
      }
      return sum + v;
    }, 0);

  const readyPct = total > 0 && ready != null ? Math.round((ready / total) * 100) : null;
  const schemaPct =
    total > 0 && withVal != null ? Math.round((withVal / total) * 100) : null;
  const indexedPct = total > 0 && indexed != null ? Math.round((indexed / total) * 100) : null;
  const localPct = total > 0 && local != null ? Math.round((local / total) * 100) : null;

  return [
    {
      id: "ready",
      label: "Ready Coverage",
      pct: readyPct,
      hint:
        ready != null
          ? `${ready}/${total} ready (status counts, not integrity proof)`
          : "UNMEASURED (readyDatasets absent)",
      tone: "green",
    },
    {
      id: "schema",
      label: "Schema Validation",
      pct: schemaPct,
      hint:
        withVal != null
          ? `${withVal} measured · ${withoutVal ?? "?"} without validation evidence`
          : "UNMEASURED (no global validation aggregate)",
      tone: "teal",
    },
    {
      id: "embedding",
      label: "Embedding Coverage",
      pct: indexedPct,
      hint:
        indexed != null
          ? `${Math.max(0, total - indexed)} datasets not indexed`
          : "UNMEASURED (indexedDatasets absent)",
      tone: "blue",
    },
    {
      id: "offline",
      label: "Local / Offline Availability",
      pct: localPct,
      hint:
        local != null
          ? unknown > 0
            ? `${local} local · ${unknown} unknown statuses`
            : `${local} local datasets`
          : "UNMEASURED (localDatasets absent)",
      tone: "orange",
    },
  ];
}

/** Bar fill style — never coerce null pct to 0%. */
export function healthBarStyle(pct: number | null): { className: string; style?: { width: string } } {
  if (pct == null) {
    return { className: "is-indeterminate" };
  }
  return { className: "", style: { width: `${Math.max(0, Math.min(100, pct))}%` } };
}

export function healthPctLabel(pct: number | null): string {
  return pct == null ? "UNMEASURED" : `${pct}%`;
}
