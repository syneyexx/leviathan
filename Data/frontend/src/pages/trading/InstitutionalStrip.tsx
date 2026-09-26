/** W30 — Institutional Trading Center status strip (no new route tree). */
export function InstitutionalStrip({
  liveBlocked = true,
  qualityLabel = "QUALITY PASS|WARN|FAIL|UNMEASURED",
  families = "equity · crypto · forex · futures",
}: {
  liveBlocked?: boolean;
  qualityLabel?: string;
  families?: string;
}) {
  return (
    <section className="lv-tp-ticker" aria-label="Institutional trading status">
      <article className="lv-tp-tick">
        <div className="lv-tp-tick-label">Live trading</div>
        <div className="lv-tp-tick-value">{liveBlocked ? "BLOCKED" : "UNLOCKED"}</div>
        <div className="lv-tp-tick-foot">
          <span className={liveBlocked ? "is-good" : "is-bad"}>LiveTradingGuard</span>
        </div>
      </article>
      <article className="lv-tp-tick">
        <div className="lv-tp-tick-label">Data quality</div>
        <div className="lv-tp-tick-value" style={{ fontSize: "0.75rem" }}>
          {qualityLabel}
        </div>
        <div className="lv-tp-tick-foot">
          <span className="is-good">parse ≠ PASS</span>
        </div>
      </article>
      <article className="lv-tp-tick">
        <div className="lv-tp-tick-label">Families</div>
        <div className="lv-tp-tick-value" style={{ fontSize: "0.75rem" }}>
          {families}
        </div>
        <div className="lv-tp-tick-foot">
          <span className="is-good">options/FI stubs</span>
        </div>
      </article>
    </section>
  );
}
