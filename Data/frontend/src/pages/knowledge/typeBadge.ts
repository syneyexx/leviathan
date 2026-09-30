/**
 * Short table badge labels derived from canonical mime/parser/library_type.
 * Does not invent source types — unknown stays Overige/typed label.
 */

export function knowledgeTypeBadge(row: {
  mime_type?: string | null;
  parser?: string | null;
  library_type?: string | null;
  library_type_label?: string | null;
}): { short: string; tone: string } {
  const mime = (row.mime_type || "").toLowerCase();
  const parser = (row.parser || "").toLowerCase();
  const lt = (row.library_type || "").toLowerCase();

  if (mime.includes("pdf") || parser === "pdf") return { short: "PDF", tone: "pdf" };
  if (
    mime.includes("parquet") ||
    mime.includes("csv") ||
    mime.includes("spreadsheet") ||
    lt === "table" ||
    lt === "market_data" ||
    lt === "financial_data"
  ) {
    return { short: "DATA", tone: "data" };
  }
  if (
    mime.startsWith("text/") ||
    mime.includes("markdown") ||
    lt === "note" ||
    lt === "web" ||
    lt === "conversation"
  ) {
    return { short: "TEXT", tone: "text" };
  }
  if (
    mime.includes("javascript") ||
    mime.includes("typescript") ||
    mime.includes("python") ||
    mime.includes("json") ||
    lt === "code" ||
    parser === "code"
  ) {
    return { short: "CODE", tone: "code" };
  }
  if (mime.startsWith("image/") || lt === "image") return { short: "IMG", tone: "image" };
  if (lt === "book" || lt === "document" || lt === "research_paper") {
    return { short: "PDF", tone: "pdf" };
  }
  const label = (row.library_type_label || row.library_type || "OVERIG").toString();
  return { short: label.slice(0, 8).toUpperCase(), tone: lt || "other" };
}
