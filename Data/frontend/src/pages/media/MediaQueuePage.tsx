import { PixelMockPage } from "../PixelMockPage";

export function MediaQueuePage() {
  return (
    <PixelMockPage
      pageKey="queue"
      title="Algemene publicatiewachtrij"
      modeLabel="Publish Mode"
      searchPlaceholder="Search media, content, campaigns, or ask Leviathan..."
      systemItems={["MEMORY ONLINE", "SYSTEMS OPERATIONAL"]}
    />
  );
}
