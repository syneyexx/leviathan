import { PixelMockPage } from "../PixelMockPage";

export function MediaLibraryPage() {
  return (
    <PixelMockPage
      pageKey="library"
      title="Bibliotheek"
      modeLabel="Library Mode"
      searchPlaceholder="Zoek bestanden, tags, campagnes, auteurs of content..."
      systemItems={["MEMORY ONLINE", "SYSTEMS OPERATIONAL"]}
    />
  );
}
