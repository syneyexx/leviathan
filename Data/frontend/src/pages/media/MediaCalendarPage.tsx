import { PixelMockPage } from "../PixelMockPage";

export function MediaCalendarPage() {
  return (
    <PixelMockPage
      pageKey="calendar"
      title="Calendar"
      modeLabel="Calendar Mode"
      searchPlaceholder="Search media, content, campaigns, platforms, or ask Leviathan..."
      systemItems={["MEMORY ONLINE", "SYSTEMS OPERATIONAL"]}
    />
  );
}
