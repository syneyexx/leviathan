/** Compact qualification / measurement truth strip — backend is sole authority. */
export function QualificationTruthStrip({
  qualificationState,
  qualified,
  blockers = [],
  pitState,
  sealedState,
  liveBlocked = true,
}: {
  qualificationState?: string | null;
  qualified?: boolean | null;
  blockers?: string[];
  pitState?: string | null;
  sealedState?: string | null;
  liveBlocked?: boolean;
}) {
  const qState = String(qualificationState || "UNMEASURED").toUpperCase();
  const nonGreen = new Set([
    "UNMEASURED",
    "ASSUMED",
    "ESTIMATED",
    "FEATURE_GATED",
    "INSUFFICIENT_HISTORY",
    "UNAVAILABLE",
    "NOT_IMPLEMENTED",
    "BLOCKED",
    "REJECTED",
    "FAILED",
  ]);
  const qClass =
    qualified === true && qState === "QUALIFIED"
      ? "is-good"
      : nonGreen.has(qState) || qualified === false
        ? "is-bad"
        : "is-warn";

  return (
    <section className="lv-tp-ticker" aria-label="Qualification truth">
      <article className="lv-tp-tick">
        <div className="lv-tp-tick-label">Qualification</div>
        <div className="lv-tp-tick-value" style={{ fontSize: "0.75rem" }}>
          {qState}
        </div>
        <div className="lv-tp-tick-foot">
          <span className={qClass}>
            {qualified === true ? "qualified" : "not institutional PASS"}
          </span>
        </div>
      </article>
      <article className="lv-tp-tick">
        <div className="lv-tp-tick-label">PIT cert</div>
        <div className="lv-tp-tick-value" style={{ fontSize: "0.75rem" }}>
          {String(pitState || "UNMEASURED").toUpperCase()}
        </div>
        <div className="lv-tp-tick-foot">
          <span className={nonGreen.has(String(pitState || "UNMEASURED").toUpperCase()) ? "is-bad" : "is-good"}>
            parse ≠ PASS
          </span>
        </div>
      </article>
      <article className="lv-tp-tick">
        <div className="lv-tp-tick-label">Sealed</div>
        <div className="lv-tp-tick-value" style={{ fontSize: "0.75rem" }}>
          {String(sealedState || "UNMEASURED").toUpperCase()}
        </div>
        <div className="lv-tp-tick-foot">
          <span className="is-warn">{blockers[0] || "receipt required"}</span>
        </div>
      </article>
      <article className="lv-tp-tick">
        <div className="lv-tp-tick-label">Live trading</div>
        <div className="lv-tp-tick-value">{liveBlocked ? "BLOCKED" : "UNLOCKED"}</div>
        <div className="lv-tp-tick-foot">
          <span className={liveBlocked ? "is-good" : "is-bad"}>LiveTradingGuard</span>
        </div>
      </article>
    </section>
  );
}
