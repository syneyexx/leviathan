import { media } from "../assets/media";
import { BrandMark } from "./BrandMark";
import { useClock } from "../hooks/useClock";

type AppHeaderProps = {
  searchPlaceholder?: string;
  modeLabel?: string;
  onMenuClick: () => void;
};

export function AppHeader({
  searchPlaceholder = "Search anything...",
  modeLabel = "Serenity Mode",
  onMenuClick,
}: AppHeaderProps) {
  const clock = useClock();

  return (
    <header className="lv-header">
      <div className="lv-brand-block">
        <div className="lv-brand-mark" aria-hidden="true">
          <BrandMark />
        </div>
        <div className="lv-brand-copy">
          <div className="lv-brand">LEVIATHAN</div>
          <div className="lv-brand-tag">Intelligence Beyond Limits</div>
        </div>
      </div>

      <label className="lv-search">
        <svg className="lv-icon" viewBox="0 0 24 24">
          <circle cx="11" cy="11" r="7" />
          <path d="M20 20l-3.5-3.5" />
        </svg>
        <input type="search" placeholder={searchPlaceholder} aria-label="Search" />
        <span className="lv-kbd">CTRL K</span>
      </label>

      <div className="lv-clock" aria-live="polite">
        <div className="lv-clock-date">{clock.date}</div>
        <div className="lv-clock-time">{clock.time}</div>
        <div className="lv-clock-mode">{modeLabel}</div>
      </div>

      <div className="lv-systems">
        <div className="lv-earth-mini">
          <img src={media.earthMini} alt="" width={64} height={64} />
        </div>
        <div className="lv-systems-capsule">
          <div className="lv-systems-title">
            <span className="lv-status-online" />
            Systems Online
            <svg className="lv-icon lv-chev" viewBox="0 0 24 24">
              <path d="M9 6l6 6-6 6" />
            </svg>
          </div>
          <div className="lv-systems-row">
            <span className="lv-sys-item">
              <span className="lv-status-online" />
              AI
            </span>
            <span className="lv-sys-item">
              <span className="lv-status-online" />
              Tools
            </span>
            <span className="lv-sys-item">
              <span className="lv-status-online" />
              Agents
            </span>
            <span className="lv-sys-item">
              <span className="lv-status-online" />
              Sync
            </span>
          </div>
        </div>
      </div>

      <div className="lv-header-end">
        <div className="lv-header-quote">
          A deeper intelligence
          <br />
          A brighter tomorrow
        </div>
        <button className="lv-menu-btn" type="button" aria-label="Menu" onClick={onMenuClick}>
          <span />
          <span />
        </button>
      </div>
    </header>
  );
}
