import { Button } from "../ui";
import { StatusDot } from "../ui";
import { useDutchClock } from "../../hooks/useDutchClock";

export type AppTopbarV2Props = {
  title?: string;
  subtitle?: string;
  online?: boolean | null;
  refreshing?: boolean;
  onRefresh?: () => void;
  onMenuClick?: () => void;
  /** Injected clock (visual tests). */
  now?: () => Date;
  onThemeToggle?: () => void;
  themeToggleTitle?: string;
};

export function AppTopbarV2({
  title = "Dashboard / Command Center",
  subtitle = "Overzicht van je hele AI infrastructuur, agents en activiteiten.",
  online = null,
  refreshing = false,
  onRefresh,
  onMenuClick,
  now,
  onThemeToggle,
  themeToggleTitle = "Appearance (display only — no theme contract connected)",
}: AppTopbarV2Props) {
  const clock = useDutchClock({ now, intervalMs: now ? 60_000 : 1_000 });
  const statusTone = online === true ? "success" : online === false ? "danger" : "muted";

  return (
    <header className="lv-v2-topbar">
      <div className="lv-v2-topbar__left">
        <button
          className="lv-v2-menu-btn"
          type="button"
          aria-label="Menu"
          onClick={onMenuClick}
        >
          <span />
          <span />
          <span />
        </button>
        <div className="lv-v2-topbar__grid-icon" aria-hidden="true">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
            <rect x="4" y="4" width="6" height="6" rx="1" />
            <rect x="14" y="4" width="6" height="6" rx="1" />
            <rect x="4" y="14" width="6" height="6" rx="1" />
            <rect x="14" y="14" width="6" height="6" rx="1" />
          </svg>
        </div>
        <div className="lv-v2-topbar__titles">
          <h1 className="lv-v2-topbar__title">{title}</h1>
          <p className="lv-v2-topbar__subtitle">{subtitle}</p>
        </div>
      </div>

      <div className="lv-v2-topbar__right">
        <button
          type="button"
          className="lv-v2-topbar__icon-btn"
          aria-label={themeToggleTitle}
          title={themeToggleTitle}
          onClick={onThemeToggle}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
            <circle cx="12" cy="12" r="4" />
            <path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M17 7l1.4-1.4M5.6 18.4l1.4-1.4" />
          </svg>
        </button>

        <Button
          variant="secondary"
          size="sm"
          loading={refreshing}
          disabled={!onRefresh || refreshing}
          onClick={() => onRefresh?.()}
          aria-label="Refresh dashboard"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
            <path d="M20 12a8 8 0 1 1-2.2-5.5" />
            <path d="M20 4v5h-5" />
          </svg>
          Refresh
        </Button>

        <div className="lv-v2-topbar__clock" aria-live="polite">
          <StatusDot tone={statusTone} pulse={online === true} />
          <span>
            {clock.dateLine} | {clock.timeLine}
          </span>
        </div>
      </div>
    </header>
  );
}
