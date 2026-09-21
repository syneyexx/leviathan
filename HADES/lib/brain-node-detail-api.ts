import { API_BASE, HadesApiError } from "./hades-api";

export type BrainNodeDetailSection = {
  title: string;
  content: string;
  metadata: Record<string, unknown>;
};

export type BrainNodeDetail = {
  id: string;
  kind: string;
  title: string;
  description: string;
  source: string;
  source_uri?: string | null;
  open_href?: string | null;
  status?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  metadata: Record<string, unknown>;
  sections: BrainNodeDetailSection[];
  truncated: boolean;
  content_chars: number;
  returned_chars: number;
};

export async function fetchBrainNodeDetail(nodeId: string): Promise<BrainNodeDetail> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/brain/nodes/${encodeURIComponent(nodeId)}/detail`, {
      headers: { "Content-Type": "application/json" },
    });
  } catch {
    throw new HadesApiError("De lokale FastAPI-backend is niet bereikbaar. Start eerst START_HADES.bat.");
  }

  if (!response.ok) {
    let message = `API-fout ${response.status}`;
    let detail: unknown = null;
    try {
      const body = (await response.json()) as { detail?: unknown };
      detail = body.detail;
      if (typeof detail === "string") message = detail;
      else if (detail && typeof detail === "object" && "message" in detail) {
        message = String((detail as { message: unknown }).message);
      }
    } catch {
      // Keep the HTTP status fallback for non-JSON failures.
    }
    throw new HadesApiError(message, response.status, detail);
  }

  return response.json() as Promise<BrainNodeDetail>;
}
