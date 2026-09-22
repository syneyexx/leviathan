import { useLocation } from "react-router-dom";
import { AppShell } from "../layouts/AppShell";
import { findMainMenuByPath, findSubMenuItem } from "../navigation/menu";

type SectionPageProps = {
  title?: string;
  modeLabel?: string;
  searchPlaceholder?: string;
  description?: string;
};

/**
 * Full page shell for submenu destinations that do not yet have a specialized UI.
 * Every submenu route resolves to a real page — never a dead toast.
 */
export function SectionPage({
  title,
  modeLabel,
  searchPlaceholder = "Search Leviathan...",
  description,
}: SectionPageProps) {
  const location = useLocation();
  const section = findMainMenuByPath(location.pathname);
  const item = findSubMenuItem(section, location.pathname);
  const heading = title ?? item?.label ?? section.label;

  return (
    <AppShell
      activeMode="explore"
      modeLabel={modeLabel ?? `${section.label} Mode`}
      searchPlaceholder={searchPlaceholder}
      layout="wide"
    >
      <main className="lv-main">
        <section className="lv-panel lv-card" style={{ padding: 20 }}>
          <div className="lv-section-label">{section.label}</div>
          <h1
            style={{
              margin: "10px 0 8px",
              fontFamily: "var(--lv-font-display)",
              letterSpacing: "0.18em",
              textTransform: "uppercase",
              fontSize: "clamp(22px, 2.4vw, 34px)",
            }}
          >
            {heading}
          </h1>
          <p className="lv-muted" style={{ margin: 0, maxWidth: 640 }}>
            {description ??
              `${heading} is beschikbaar via het submenu. De workspace voor deze sectie wordt hier verder uitgewerkt.`}
          </p>
        </section>
      </main>
    </AppShell>
  );
}

/** @deprecated use SectionPage */
export const PlaceholderPage = SectionPage;
