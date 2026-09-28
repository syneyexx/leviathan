import { request } from "../http";
import type { ResearchCommandSnapshot } from "../../types/researchCommand";

export type ResearchCommandQuery = {
  orchestraId?: string;
  portfolioId?: string;
  labId?: string;
  sessionId?: string;
  asOf?: string;
};

function queryString(params: ResearchCommandQuery): string {
  const q = new URLSearchParams();
  if (params.orchestraId) q.set("orchestraId", params.orchestraId);
  if (params.portfolioId) q.set("portfolioId", params.portfolioId);
  if (params.labId) q.set("labId", params.labId);
  if (params.sessionId) q.set("sessionId", params.sessionId);
  if (params.asOf) q.set("asOf", params.asOf);
  const text = q.toString();
  return text ? `?${text}` : "";
}

export const researchCommandApi = {
  researchCommandSnapshot(
    params: ResearchCommandQuery = {},
    init?: { signal?: AbortSignal },
  ): Promise<ResearchCommandSnapshot> {
    return request(`/api/market-sim/research-command${queryString(params)}`, { signal: init?.signal });
  },

  researchCommandStart(body: {
    orchestraId: string;
    portfolioId: string;
    labId?: string;
  }): Promise<Record<string, unknown>> {
    return request("/api/market-sim/research-command/start", {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  researchCommandPause(body: {
    sessionId?: string | null;
    orchestraId?: string | null;
  }): Promise<Record<string, unknown>> {
    return request("/api/market-sim/research-command/pause", {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  researchCommandFlatten(body: { sessionId: string; confirm: "FLATTEN_PAPER" }): Promise<Record<string, unknown>> {
    return request("/api/market-sim/research-command/flatten", {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  researchCommandKill(body: {
    sessionId: string;
    armed: boolean;
    confirm?: string;
  }): Promise<Record<string, unknown>> {
    return request("/api/market-sim/research-command/kill-switch", {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  researchCommandEvolve(body: { labId: string }): Promise<Record<string, unknown>> {
    return request("/api/market-sim/research-command/evolution/start", {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  researchCommandWatch(body: {
    sessionId: string;
    symbol: string;
    reason: string;
  }): Promise<Record<string, unknown>> {
    return request("/api/market-sim/research-command/watch", {
      method: "POST",
      body: JSON.stringify(body),
    });
  },
};
