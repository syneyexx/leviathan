import type { FinalBetaIconName } from "../icons";

export type QueueStatus = "klaar" | "review" | "geblokkeerd" | "wachtrij" | "goedgekeurd" | "gepubliceerd";
export type PlatformId = "yt" | "tt" | "ig" | "fb" | "x" | "li";

export const QUEUE_KPIS: Array<{
  id: string;
  label: string;
  value: string;
  trend: string;
  tone: "up" | "down";
  icon: FinalBetaIconName;
  iconTone: string;
}> = [
  { id: "total", label: "Totaal in wachtrij", value: "28", trend: "↑ +12%", tone: "up", icon: "list", iconTone: "cyan" },
  { id: "ready", label: "Klaar voor publicatie", value: "17", trend: "↑ +31%", tone: "up", icon: "checkcircle", iconTone: "green" },
  { id: "review", label: "In review", value: "6", trend: "↓ -14%", tone: "down", icon: "clock", iconTone: "orange" },
  { id: "blocked", label: "Geblokkeerd", value: "3", trend: "↑ +200%", tone: "down", icon: "shield", iconTone: "red" },
  { id: "today", label: "Vandaag publiceren", value: "12", trend: "↑ +33%", tone: "up", icon: "calendar", iconTone: "blue" },
  { id: "week", label: "Deze week", value: "28", trend: "↑ +18%", tone: "up", icon: "chart", iconTone: "cyan" },
];

export const QUEUE_TABS = [
  { id: "totaal", label: "Totaal", count: 28 },
  { id: "wachtrij", label: "In wachtrij", count: 17 },
  { id: "review", label: "In review", count: 6 },
  { id: "goedgekeurd", label: "Goedgekeurd", count: 17 },
  { id: "geblokkeerd", label: "Geblokkeerd", count: 3 },
  { id: "gepubliceerd", label: "Gepubliceerd", count: 142 },
] as const;

export type QueueItem = {
  id: number;
  title: string;
  description: string;
  platforms: PlatformId[];
  publishAt: string;
  status: QueueStatus;
  statusLabel: string;
  review: string;
  reviewTone: "green" | "gold" | "red" | "blue";
  assignee: { initials: string; name: string; tone: string };
  thumbTone: string;
};

export const QUEUE_ITEMS: QueueItem[] = [
  {
    id: 1,
    title: "AI pet influencers — teaser",
    description: "30s short · hooks + CTA · NL/EN",
    platforms: ["yt", "tt", "ig"],
    publishAt: "17 sep 2026 14:00",
    status: "klaar",
    statusLabel: "Klaar",
    review: "2/2",
    reviewTone: "green",
    assignee: { initials: "JD", name: "J. Dekker", tone: "cyan" },
    thumbTone: "a",
  },
  {
    id: 2,
    title: "Cozy productivity desk setup",
    description: "Reel · ambient B-roll · captions",
    platforms: ["ig", "tt", "x"],
    publishAt: "17 sep 2026 16:30",
    status: "review",
    statusLabel: "In review",
    review: "1/2",
    reviewTone: "gold",
    assignee: { initials: "ES", name: "E. Smit", tone: "purple" },
    thumbTone: "b",
  },
  {
    id: 3,
    title: "HADES local AI walkthrough",
    description: "Long-form · chapters · end screen",
    platforms: ["yt", "li"],
    publishAt: "18 sep 2026 09:00",
    status: "goedgekeurd",
    statusLabel: "Goedgekeurd",
    review: "2/2",
    reviewTone: "green",
    assignee: { initials: "ML", name: "M. Leeuw", tone: "green" },
    thumbTone: "c",
  },
  {
    id: 4,
    title: "Retro tech unboxing clip",
    description: "Shorts · sound pack · hashtags",
    platforms: ["tt", "yt", "ig"],
    publishAt: "18 sep 2026 12:15",
    status: "wachtrij",
    statusLabel: "In wachtrij",
    review: "0/2",
    reviewTone: "red",
    assignee: { initials: "KV", name: "K. Visser", tone: "gold" },
    thumbTone: "d",
  },
  {
    id: 5,
    title: "Travel & nature montage",
    description: "Carousel + Reel · geotags EU",
    platforms: ["ig", "fb", "x"],
    publishAt: "18 sep 2026 18:00",
    status: "klaar",
    statusLabel: "Klaar",
    review: "2/2",
    reviewTone: "green",
    assignee: { initials: "RT", name: "R. Teun", tone: "blue" },
    thumbTone: "e",
  },
  {
    id: 6,
    title: "Platform rights checklist",
    description: "Meta · licentie · asset audit",
    platforms: ["fb", "ig", "li"],
    publishAt: "19 sep 2026 10:00",
    status: "geblokkeerd",
    statusLabel: "Geblokkeerd",
    review: "Metadata fout",
    reviewTone: "red",
    assignee: { initials: "JD", name: "J. Dekker", tone: "cyan" },
    thumbTone: "f",
  },
  {
    id: 7,
    title: "Friday founder's note",
    description: "Thread + LinkedIn article",
    platforms: ["x", "li"],
    publishAt: "19 sep 2026 15:45",
    status: "review",
    statusLabel: "In review",
    review: "1/2",
    reviewTone: "gold",
    assignee: { initials: "ES", name: "E. Smit", tone: "purple" },
    thumbTone: "a",
  },
  {
    id: 8,
    title: "Sound trend remix pack",
    description: "5 clips · TT/IG sync",
    platforms: ["tt", "ig"],
    publishAt: "20 sep 2026 11:00",
    status: "klaar",
    statusLabel: "Klaar",
    review: "2/2",
    reviewTone: "green",
    assignee: { initials: "ML", name: "M. Leeuw", tone: "green" },
    thumbTone: "b",
  },
  {
    id: 9,
    title: "Weekly digest — Viral radar",
    description: "Carousel · stats snapshot",
    platforms: ["ig", "fb", "x", "li"],
    publishAt: "21 sep 2026 08:30",
    status: "wachtrij",
    statusLabel: "In wachtrij",
    review: "0/2",
    reviewTone: "red",
    assignee: { initials: "KV", name: "K. Visser", tone: "gold" },
    thumbTone: "c",
  },
  {
    id: 10,
    title: "Behind the scenes studio",
    description: "Stories · poll sticker",
    platforms: ["ig", "fb"],
    publishAt: "21 sep 2026 17:00",
    status: "goedgekeurd",
    statusLabel: "Goedgekeurd",
    review: "2/2",
    reviewTone: "green",
    assignee: { initials: "RT", name: "R. Teun", tone: "blue" },
    thumbTone: "d",
  },
];

export const QUEUE_VOLUME = {
  days: ["17 sep", "18 sep", "19 sep", "20 sep", "21 sep", "22 sep", "23 sep"],
  series: [
    { id: "yt", label: "YouTube", color: "#ff0000", values: [4, 6, 3, 5, 7, 4, 5] },
    { id: "tt", label: "TikTok", color: "#00f2ea", values: [7, 5, 8, 6, 9, 7, 8] },
    { id: "ig", label: "Instagram", color: "#e4405f", values: [5, 4, 6, 5, 4, 6, 5] },
    { id: "fb", label: "Facebook", color: "#1877f2", values: [2, 3, 2, 4, 3, 2, 3] },
    { id: "x", label: "X", color: "#e8eef2", values: [3, 2, 4, 3, 2, 3, 4] },
  ],
};

export const QUEUE_STATUS_SLICES = [
  { label: "Klaar", count: 17, color: "#22c55e", pct: "61%" },
  { label: "In review", count: 6, color: "#f59e0b", pct: "21%" },
  { label: "Geblokkeerd", count: 3, color: "#ef4444", pct: "11%" },
  { label: "In wachtrij", count: 2, color: "#38bdf8", pct: "7%" },
];

export const QUEUE_TIMELINE = {
  days: ["17", "18", "19", "20", "21", "22", "23"],
  planned: [8, 10, 7, 12, 9, 6, 11],
  published: [5, 7, 4, 8, 6, 3, 2],
};

export const QUEUE_OVERVIEW = [
  { label: "Totaal in wachtrij", value: "28", tone: "cyan" },
  { label: "Klaar voor publicatie", value: "17", tone: "green" },
  { label: "In review", value: "6", tone: "gold" },
  { label: "Geblokkeerd", value: "3", tone: "red" },
  { label: "Achterstallige review", value: "4", tone: "orange" },
  { label: "Gepubliceerd (7d)", value: "41", tone: "blue" },
];

export const QUEUE_BLOCKED = [
  { id: 6, reason: "Metadata fout" },
  { id: 14, reason: "Rechten/licentie" },
  { id: 22, reason: "Platform error" },
];

export const QUEUE_BACKLOG = [
  { id: 4, reason: "Wacht op review" },
  { id: 2, reason: "Feedback verwacht" },
];

export const QUEUE_ACTIONS: Array<{ label: string; icon: FinalBetaIconName }> = [
  { label: "Nieuwe content", icon: "plus" },
  { label: "Planning bekijken", icon: "calendar" },
  { label: "Bulk bewerken", icon: "sliders" },
  { label: "Exporteren", icon: "download" },
  { label: "AI suggesties", icon: "brain" },
  { label: "Notificaties", icon: "bolt" },
];

export const PLATFORM_META: Record<PlatformId, { label: string; color: string; short: string }> = {
  yt: { label: "YouTube", color: "#ff0000", short: "YT" },
  tt: { label: "TikTok", color: "#00f2ea", short: "TT" },
  ig: { label: "Instagram", color: "#e4405f", short: "IG" },
  fb: { label: "Facebook", color: "#1877f2", short: "FB" },
  x: { label: "X", color: "#e8eef2", short: "X" },
  li: { label: "LinkedIn", color: "#0a66c2", short: "in" },
};
