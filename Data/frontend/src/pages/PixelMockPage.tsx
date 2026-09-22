import { AppShell } from "../layouts/AppShell";
import { mediaPageContent, type MediaPageKey } from "../assets/mediaPagesAssets";

type PixelMockPageProps = {
  pageKey: MediaPageKey;
  title: string;
  modeLabel: string;
  searchPlaceholder: string;
  systemItems?: readonly string[];
};

/**
 * Pixel-exact content panel — shows the design-reference content crop
 * (sidebar/chrome already provided by AppShell + footer submenu).
 */
export function PixelMockPage({
  pageKey,
  title,
  modeLabel,
  searchPlaceholder,
  systemItems,
}: PixelMockPageProps) {
  const src = mediaPageContent[pageKey];

  return (
    <AppShell
      activeMode="explore"
      modeLabel={modeLabel}
      searchPlaceholder={searchPlaceholder}
      systemItems={systemItems}
      layout="wide"
      pageClass="lv-app--pixel-mock"
    >
      <main className="lv-main lv-pixel-main">
        <section className="lv-pixel-frame" aria-label={title}>
          <img className="lv-pixel-shot" src={src} alt={title} width={1450} height={893} />
        </section>
      </main>
    </AppShell>
  );
}
