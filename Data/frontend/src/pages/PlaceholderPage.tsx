import { useLocation, useSearchParams } from "react-router-dom";
import { AppShell } from "../layouts/AppShell";
import { SubMenu } from "../components/SubMenu";
import { findMainMenuByPath, findSubMenuItem } from "../navigation/menu";

type PlaceholderPageProps = {
  title?: string;
  modeLabel?: string;
  searchPlaceholder?: string;
  layout?: "standard" | "wide";
  pageClass?: string;
};

/** Lightweight shell for submenu destinations that do not have a full page yet. */
export function PlaceholderPage({
  title,
  modeLabel = "Explore Mode",
  searchPlaceholder = "Search Leviathan...",
  layout = "wide",
  pageClass,
}: PlaceholderPageProps) {
  const location = useLocation();
  const [params] = useSearchParams();
  const section = findMainMenuByPath(location.pathname);
  const item = findSubMenuItem(section, location.pathname, params.get("tab"));
  const heading = title ?? item?.label ?? section.label;

  return (
    <AppShell
      activeMode="explore"
      modeLabel={modeLabel}
      searchPlaceholder={searchPlaceholder}
      layout={layout}
      pageClass={pageClass}
    >
      <main className="lv-main">
        <SubMenu />
        <section className="lv-panel lv-card" style={{ padding: 20 }}>
          <div className="lv-section-label">{section.label}</div>
          <h1 style={{ margin: "8px 0 6px", fontFamily: "var(--lv-font-display)", letterSpacing: "0.18em" }}>
            {heading}
          </h1>
          <p className="lv-muted" style={{ margin: 0 }}>
            Deze pagina is gereserveerd in het menu. De shell staat klaar voor de volgende Leviathan-stap.
          </p>
        </section>
      </main>
    </AppShell>
  );
}
