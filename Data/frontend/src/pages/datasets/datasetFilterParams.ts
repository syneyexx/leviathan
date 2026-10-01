/**
 * Map Datasets V2 filter labels → canonical listDatasets query params.
 * Server-side filtering only — inventory must not re-filter type/updated client-side.
 */

import type { DhFilterId } from "./constants";

export type DatasetListFilterParams = {
  offset?: number;
  q?: string;
  sourceScope?: "local" | "external";
  indexed?: boolean;
  type?: string;
  detectedFormat?: string;
  tags?: string;
  updatedAfter?: string;
  updatedBefore?: string;
  cursor?: string;
  sort?: string;
};

/** Display label → detectedFormat / type query value(s). Prefer detectedFormat. */
export function typeLabelToQueryParam(
  typeFilter: string,
): { detectedFormat?: string; type?: string } {
  const t = typeFilter.trim().toLowerCase();
  if (!t || t === "alle types" || t === "all types") return {};
  // Canonical detected_format values used by backend + mapType in datasetsMapping.
  if (t === "tekst" || t === "text") return { detectedFormat: "text" };
  if (t === "tabel" || t === "structured" || t === "table") return { detectedFormat: "csv" };
  if (t === "documenten" || t === "document" || t === "documents") return { detectedFormat: "md" };
  if (t === "code") return { detectedFormat: "code" };
  if (t === "json") return { detectedFormat: "json" };
  if (t === "afbeeldingen" || t === "images" || t === "image") return { detectedFormat: "image" };
  if (t === "multimodal") return { detectedFormat: "multimodal" };
  return { detectedFormat: t };
}

/** Map updated filter label → ISO updatedAfter (+ optional sort override). */
export function updatedFilterToQueryParams(
  updatedFilter: string,
  nowMs = Date.now(),
): Pick<DatasetListFilterParams, "updatedAfter" | "sort"> {
  const u = updatedFilter.trim().toLowerCase();
  if (!u || u === "laatst gewijzigd" || u === "last updated") {
    return { sort: "updated_at_desc" };
  }
  if (u === "oudste eerst" || u === "oldest first") {
    return { sort: "updated_at_asc" };
  }
  const windowMs =
    u === "laatste 24 uur" || u === "last 24 hours"
      ? 24 * 60 * 60 * 1000
      : u === "laatste 7 dagen" || u === "last 7 days"
        ? 7 * 24 * 60 * 60 * 1000
        : u === "laatste 30 dagen" || u === "last 30 days"
          ? 30 * 24 * 60 * 60 * 1000
          : null;
  if (windowMs == null) return { sort: "updated_at_desc" };
  return {
    updatedAfter: new Date(nowMs - windowMs).toISOString(),
    sort: "updated_at_desc",
  };
}

export function activityPeriodToQueryParams(
  period: string,
  nowMs = Date.now(),
): { createdAfter?: string; createdBefore?: string } {
  const p = period.trim().toLowerCase();
  if (!p || p === "alles" || p === "all") return {};
  const windowMs =
    p === "laatste 24 uur" || p === "last 24 hours"
      ? 24 * 60 * 60 * 1000
      : p === "laatste 7 dagen" || p === "last 7 days"
        ? 7 * 24 * 60 * 60 * 1000
        : p === "laatste 30 dagen" || p === "last 30 days"
          ? 30 * 24 * 60 * 60 * 1000
          : null;
  if (windowMs == null) return {};
  return { createdAfter: new Date(nowMs - windowMs).toISOString() };
}

export function buildListDatasetsParams(opts: {
  filter: DhFilterId;
  query?: string;
  typeFilter?: string;
  updatedFilter?: string;
  tags?: string;
  offset?: number;
  cursor?: string;
  nowMs?: number;
}): DatasetListFilterParams {
  const params: DatasetListFilterParams = {
    sort: "updated_at_desc",
  };
  if (opts.offset != null) params.offset = opts.offset;
  if (opts.cursor) params.cursor = opts.cursor;
  if (opts.query) params.q = opts.query;
  if (opts.tags) params.tags = opts.tags;
  if (opts.filter === "local") params.sourceScope = "local";
  if (opts.filter === "external") params.sourceScope = "external";
  if (opts.filter === "indexed") params.indexed = true;
  if (opts.filter === "not_indexed") params.indexed = false;

  const typeQ = typeLabelToQueryParam(opts.typeFilter ?? "Alle types");
  if (typeQ.detectedFormat) params.detectedFormat = typeQ.detectedFormat;
  if (typeQ.type) params.type = typeQ.type;

  const updatedQ = updatedFilterToQueryParams(opts.updatedFilter ?? "Laatst gewijzigd", opts.nowMs);
  if (updatedQ.updatedAfter) params.updatedAfter = updatedQ.updatedAfter;
  if (updatedQ.sort) params.sort = updatedQ.sort;

  return params;
}
