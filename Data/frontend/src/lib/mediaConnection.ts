/**
 * Media Control / platform pages have no live social-provider integration.
 * Frontend must not present fixture KPIs as operational truth.
 */
export const MEDIA_CONNECTED = false as const;

export const MEDIA_STATUS_LABEL = "NOT CONNECTED" as const;

export const MEDIA_UNAVAILABLE = "UNAVAILABLE" as const;

export const MEDIA_SYSTEM_ITEMS = ["MEDIA NOT CONNECTED", "METRICS UNAVAILABLE"] as const;

export const MEDIA_TRUTH_REASON =
  "No external media platform provider is connected. Metrics, queues, schedules, and engagement are unavailable — not live production data.";

export function mediaMetricDisplay(_fabricated?: string): string {
  return MEDIA_CONNECTED ? (_fabricated ?? MEDIA_UNAVAILABLE) : MEDIA_UNAVAILABLE;
}
