import { PixelMockPage } from "../PixelMockPage";

export function MediaViralPage() {
  return (
    <PixelMockPage
      pageKey="viral"
      title="Viral Radar"
      modeLabel="Viral Mode"
      searchPlaceholder="Search trends, creators, topics, competitors, or ask Leviathan..."
      systemItems={["MEMORY ONLINE", "SYSTEMS OPERATIONAL"]}
    />
  );
}
