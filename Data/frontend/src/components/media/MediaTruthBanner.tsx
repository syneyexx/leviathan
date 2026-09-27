import { MEDIA_STATUS_LABEL, MEDIA_TRUTH_REASON } from "../../lib/mediaConnection";

/** Honest connection posture for Media Control / platform routes. */
export function MediaTruthBanner({ children }: { children?: string }) {
  return (
    <p className="lv-demo-banner" role="status" data-truth="not-connected">
      <strong>{MEDIA_STATUS_LABEL}</strong>
      {" — "}
      {children ?? MEDIA_TRUTH_REASON}
    </p>
  );
}
