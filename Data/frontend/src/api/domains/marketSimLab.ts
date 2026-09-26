/** Research Lab market-sim API domain — no page-local ad-hoc fetch (W18B). */

import { request } from "../http";

export const marketSimLabApi = {
  marketSimLabOverview(): Promise<Record<string, unknown>> {
    return request("/api/market-sim/lab/overview");
  },

  marketSimLabCostPack(params?: {
    feeBps?: number;
    slippageBps?: number;
    seed?: number;
  }): Promise<{ cost_pack: Record<string, unknown> }> {
    const q = new URLSearchParams();
    if (params?.feeBps != null) q.set("feeBps", String(params.feeBps));
    if (params?.slippageBps != null) q.set("slippageBps", String(params.slippageBps));
    if (params?.seed != null) q.set("seed", String(params.seed));
    const qs = q.toString();
    return request(`/api/market-sim/lab/cost-pack${qs ? `?${qs}` : ""}`);
  },

  marketSimLabFeedHealth(payload: Record<string, unknown>): Promise<{ feed_health: Record<string, unknown> }> {
    return request("/api/market-sim/lab/feed-health", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  marketSimLabTrials(params?: {
    strategyId?: string;
    limit?: number;
  }): Promise<{ trials: Record<string, unknown>[]; count: number; truth: Record<string, unknown> }> {
    const q = new URLSearchParams();
    if (params?.strategyId) q.set("strategyId", params.strategyId);
    if (params?.limit != null) q.set("limit", String(params.limit));
    const qs = q.toString();
    return request(`/api/market-sim/lab/trials${qs ? `?${qs}` : ""}`);
  },

} as const;
