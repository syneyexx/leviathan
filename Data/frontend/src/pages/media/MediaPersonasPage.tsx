import { PixelMockPage } from "../PixelMockPage";

export function MediaPersonasPage() {
  return (
    <PixelMockPage
      pageKey="personas"
      title="Personas"
      modeLabel="Personas Mode"
      searchPlaceholder="Search media, content, campaigns, platforms, or ask Leviathan..."
      systemItems={["MEMORY ONLINE", "SYSTEMS OPERATIONAL"]}
    />
  );
}
