import type { FinalBetaIconName } from "../icons";

export type CalendarView = "maand" | "week" | "dag" | "lijst";
export type CalPlatform =
  | "youtube"
  | "tiktok"
  | "instagram"
  | "facebook"
  | "linkedin"
  | "x"
  | "website"
  | "podcast";
export type CalEntryType = "post" | "campagne" | "deadline" | "review" | "event";

export const CAL_VIEWS: Array<{ id: CalendarView; label: string }> = [
  { id: "maand", label: "Maand" },
  { id: "week", label: "Week" },
  { id: "dag", label: "Dag" },
  { id: "lijst", label: "Lijst" },
];

export const CAL_WEEKDAYS = ["Ma", "Di", "Wo", "Do", "Vr", "Za", "Zo"];

export const CAL_PLATFORM_LEGEND: Array<{ id: CalPlatform; label: string; color: string }> = [
  { id: "youtube", label: "YouTube", color: "#ff3b3b" },
  { id: "tiktok", label: "TikTok", color: "#25f4ee" },
  { id: "instagram", label: "Instagram", color: "#e4405f" },
  { id: "facebook", label: "Facebook", color: "#1877f2" },
  { id: "linkedin", label: "LinkedIn", color: "#0a66c2" },
  { id: "x", label: "X", color: "#e8eef2" },
  { id: "website", label: "Website", color: "#22c55e" },
  { id: "podcast", label: "Podcast", color: "#a78bfa" },
];

export const CAL_TYPE_LEGEND: Array<{ id: CalEntryType; label: string; icon: FinalBetaIconName }> = [
  { id: "post", label: "Post", icon: "file" },
  { id: "campagne", label: "Campagne", icon: "bolt" },
  { id: "deadline", label: "Deadline", icon: "clock" },
  { id: "review", label: "Review", icon: "shield" },
  { id: "event", label: "Event", icon: "calendar" },
];

export type CalGridEntry = {
  time: string;
  title: string;
  platform: CalPlatform;
  type: CalEntryType;
};

/** September 2026 — Mon-first grid. Sep 1 = Tue, today = 17, selected default = 15. */
export const CAL_YEAR = 2026;
export const CAL_MONTH = 8; // 0-indexed September
export const CAL_TODAY = 17;
export const CAL_DEFAULT_SELECTED = 15;

export const CAL_ENTRIES: Record<number, CalGridEntry[]> = {
  1: [{ time: "10:00", title: "Kickoff Q3", platform: "linkedin", type: "event" }],
  2: [{ time: "14:00", title: "Reel batch", platform: "instagram", type: "post" }],
  3: [
    { time: "09:00", title: "YT Short", platform: "youtube", type: "post" },
    { time: "16:00", title: "Review cut", platform: "website", type: "review" },
  ],
  4: [{ time: "11:00", title: "TikTok Reel", platform: "tiktok", type: "post" }],
  5: [{ time: "13:00", title: "Podcast ep.12", platform: "podcast", type: "post" }],
  8: [
    { time: "09:30", title: "Social Sprint", platform: "instagram", type: "campagne" },
    { time: "15:00", title: "FB carousel", platform: "facebook", type: "post" },
  ],
  9: [{ time: "10:00", title: "Product Demo", platform: "youtube", type: "post" }],
  10: [
    { time: "08:00", title: "Morning hook", platform: "tiktok", type: "post" },
    { time: "17:00", title: "Deadline assets", platform: "website", type: "deadline" },
  ],
  11: [{ time: "12:00", title: "LinkedIn essay", platform: "linkedin", type: "post" }],
  12: [
    { time: "09:00", title: "AI verandert alles", platform: "youtube", type: "post" },
    { time: "14:30", title: "Thread X", platform: "x", type: "post" },
  ],
  13: [{ time: "11:00", title: "Weekend drop", platform: "instagram", type: "post" }],
  14: [{ time: "16:00", title: "Campagne sync", platform: "website", type: "campagne" }],
  15: [
    { time: "09:00", title: "Social Sprint", platform: "instagram", type: "campagne" },
    { time: "11:00", title: "TikTok Reel", platform: "tiktok", type: "post" },
    { time: "15:00", title: "Product Demo", platform: "youtube", type: "post" },
  ],
  16: [
    { time: "10:00", title: "IG Stories", platform: "instagram", type: "post" },
    { time: "14:00", title: "Review pack", platform: "website", type: "review" },
  ],
  17: [
    { time: "09:00", title: "Content Review", platform: "website", type: "review" },
    { time: "14:00", title: "YouTube Short", platform: "youtube", type: "post" },
    { time: "16:00", title: "Team Sync", platform: "linkedin", type: "event" },
  ],
  18: [
    { time: "09:30", title: "Campagne evaluatie", platform: "website", type: "campagne" },
    { time: "13:00", title: "TikTok batch", platform: "tiktok", type: "post" },
  ],
  19: [{ time: "11:00", title: "FB live teaser", platform: "facebook", type: "post" }],
  20: [
    { time: "15:00", title: "HADES Live Q&A", platform: "youtube", type: "event" },
    { time: "18:00", title: "Podcast clip", platform: "podcast", type: "post" },
  ],
  22: [{ time: "10:00", title: "Creator tips", platform: "instagram", type: "post" }],
  23: [
    { time: "09:00", title: "YT longform", platform: "youtube", type: "post" },
    { time: "16:00", title: "Deadline copy", platform: "website", type: "deadline" },
  ],
  24: [{ time: "12:00", title: "X thread", platform: "x", type: "post" }],
  25: [
    { time: "10:00", title: "Maandelijkse rapportage", platform: "linkedin", type: "event" },
    { time: "14:00", title: "IG carousel", platform: "instagram", type: "post" },
  ],
  26: [{ time: "11:00", title: "TikTok trend", platform: "tiktok", type: "post" }],
  29: [{ time: "09:00", title: "Week wrap", platform: "youtube", type: "post" }],
  30: [{ time: "15:00", title: "Q4 preview", platform: "linkedin", type: "campagne" }],
};

export type CalDayScheduleItem = {
  start: string;
  end: string;
  title: string;
  type: CalEntryType;
  platform?: CalPlatform;
  avatars: string[];
};

export const CAL_DAY_SCHEDULE: Record<number, CalDayScheduleItem[]> = {
  15: [
    { start: "09:00", end: "10:30", title: "Social Sprint", type: "campagne", platform: "instagram", avatars: ["AC", "MK", "JL"] },
    { start: "11:00", end: "11:45", title: "TikTok Reel", type: "post", platform: "tiktok", avatars: ["MK"] },
    { start: "15:00", end: "16:00", title: "Product Demo", type: "post", platform: "youtube", avatars: ["AC", "JL"] },
  ],
  17: [
    { start: "09:00", end: "10:00", title: "Content Review", type: "review", avatars: ["AC", "MK", "JL"] },
    { start: "14:00", end: "14:30", title: "YouTube Short", type: "post", platform: "youtube", avatars: ["AC"] },
    { start: "16:00", end: "17:00", title: "Team Sync", type: "event", avatars: ["AC", "MK", "JL"] },
  ],
};

export const CAL_DAY_STATS: Record<number, { items: number; duration: string; capacity: number }> = {
  15: { items: 3, duration: "3h 15m", capacity: 72 },
  17: { items: 3, duration: "2h 30m", capacity: 60 },
};

export const CAL_CAMPAIGNS = [
  { id: "c1", name: "HADES Launch Q3", done: 12, total: 20, pct: 60 },
  { id: "c2", name: "Creator Growth Push", done: 16, total: 20, pct: 80 },
  { id: "c3", name: "Podcast Autumn Arc", done: 5, total: 12, pct: 42 },
  { id: "c4", name: "Short-form Lab", done: 9, total: 15, pct: 60 },
];

export const CAL_CONTENT_STATS = [
  { id: "planned", label: "Geplande posts", value: "28", trend: "+27%", tone: "up" as const, icon: "calendar" as FinalBetaIconName },
  { id: "published", label: "Gepubliceerd", value: "24", trend: "+33%", tone: "up" as const, icon: "checkcircle" as FinalBetaIconName },
  { id: "review", label: "In review", value: "3", trend: "+0%", tone: "flat" as const, icon: "shield" as FinalBetaIconName },
  { id: "expired", label: "Verlopen", value: "1", trend: "-50%", tone: "down" as const, icon: "clock" as FinalBetaIconName },
];

export type TeamLoad = "free" | "busy" | "full";

export const CAL_TEAM = {
  days: ["Ma", "Di", "Wo", "Do", "Vr"],
  rows: [
    { role: "HADES Creator", loads: ["free", "busy", "busy", "free", "full"] as TeamLoad[] },
    { role: "Content Team", loads: ["busy", "busy", "free", "busy", "busy"] as TeamLoad[] },
    { role: "Design", loads: ["free", "free", "busy", "busy", "free"] as TeamLoad[] },
    { role: "Growth", loads: ["busy", "free", "full", "busy", "free"] as TeamLoad[] },
    { role: "Management", loads: ["free", "busy", "free", "free", "busy"] as TeamLoad[] },
  ],
};

export const CAL_PUBLISH_WINDOWS = [
  { platform: "youtube" as CalPlatform, label: "YouTube", window: "10:00 – 12:00", level: "hoog" as const, pct: 92 },
  { platform: "tiktok" as CalPlatform, label: "TikTok", window: "18:00 – 21:00", level: "hoog" as const, pct: 88 },
  { platform: "instagram" as CalPlatform, label: "Instagram", window: "12:00 – 14:00", level: "mid" as const, pct: 64 },
  { platform: "linkedin" as CalPlatform, label: "LinkedIn", window: "08:00 – 09:30", level: "mid" as const, pct: 58 },
  { platform: "x" as CalPlatform, label: "X", window: "07:00 – 08:00", level: "laag" as const, pct: 34 },
];

export const CAL_ACTIONS: Array<{ label: string; icon: FinalBetaIconName }> = [
  { label: "Nieuwe post", icon: "plus" },
  { label: "Campagne", icon: "bolt" },
  { label: "Deadline", icon: "clock" },
  { label: "Review", icon: "shield" },
  { label: "Importeren", icon: "upload" },
  { label: "Exporteren", icon: "download" },
];

export const CAL_UPCOMING = [
  { day: "18", month: "SEP", title: "Campagne evaluatie", hint: "09:30 · Website" },
  { day: "20", month: "SEP", title: "HADES Live Q&A", hint: "15:00 · YouTube" },
  { day: "25", month: "SEP", title: "Maandelijkse rapportage", hint: "10:00 · LinkedIn" },
];

export const CAL_FILTERS = {
  channels: "Alle kanalen",
  types: "Alle types",
  campaigns: "Alle campagnes",
};
