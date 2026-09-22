import { PixelMockPage } from "./PixelMockPage";

/** Pixel-exact Research content from design reference. */
export function ResearchPixelPage() {
  return (
    <PixelMockPage
      pageKey="research"
      title="Research"
      modeLabel="Research Mode"
      searchPlaceholder="Search knowledge, papers, datasets, web..."
      systemItems={["SYSTEMS ONLINE", "AI", "TOOLS", "AGENTS", "SYNC"]}
    />
  );
}
