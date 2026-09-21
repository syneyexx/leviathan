import type { FinalBetaIconName } from "../icons";

export const VIRAL_KPIS: Array<{
  id: string;
  label: string;
  value: string;
  hint: string;
  hintTone?: "up" | "flat";
  icon: FinalBetaIconName;
  iconTone: string;
}> = [
  { id: "scanned", label: "Trends gescand", value: "1.842", hint: "+23% vs gisteren", hintTone: "up", icon: "target", iconTone: "green" },
  { id: "rising", label: "Opkomende trends", value: "47", hint: "+12 nieuw", hintTone: "up", icon: "bolt", iconTone: "orange" },
  { id: "strong", label: "Sterke signalen", value: "15", hint: "> 80% confidence", hintTone: "flat", icon: "chart", iconTone: "cyan" },
  { id: "velocity", label: "Gemiddelde trend velocity", value: "+612%", hint: "7d groei", hintTone: "up", icon: "line", iconTone: "cyan" },
  { id: "chance", label: "Virale kansen", value: "9", hint: "Score > 80", hintTone: "flat", icon: "bolt", iconTone: "gold" },
  { id: "platforms", label: "Platforms actief", value: "6 / 6", hint: "Alle platformen", hintTone: "flat", icon: "link", iconTone: "cyan" },
];

export const VIRAL_MOMENTUM = {
  labels: ["10 sep", "11 sep", "12 sep", "13 sep", "14 sep", "15 sep", "16 sep", "17 sep"],
  series: [
    { id: "tt", label: "TikTok", color: "#00f2ea", values: [22, 28, 35, 42, 55, 68, 74, 88] },
    { id: "yt", label: "YouTube", color: "#ff0000", values: [30, 32, 38, 40, 48, 52, 58, 62] },
    { id: "ig", label: "Instagram", color: "#e4405f", values: [18, 24, 30, 36, 44, 50, 56, 60] },
    { id: "x", label: "X", color: "#e8eef2", values: [12, 16, 20, 22, 28, 30, 34, 38] },
    { id: "fb", label: "Facebook", color: "#1877f2", values: [10, 12, 14, 18, 20, 22, 24, 26] },
    { id: "rd", label: "Reddit", color: "#ff4500", values: [8, 14, 18, 26, 32, 40, 46, 52] },
  ],
};

export const VIRAL_RISING = [
  { rank: 1, title: "AI pet influencers", growth: "+820%", score: 94, platform: "tt", tone: "a" },
  { rank: 2, title: "Cozy productivity", growth: "+640%", score: 91, platform: "ig", tone: "b" },
  { rank: 3, title: "Retro tech unbox", growth: "+510%", score: 87, platform: "yt", tone: "c" },
  { rank: 4, title: "Local AI demos", growth: "+430%", score: 84, platform: "x", tone: "d" },
  { rank: 5, title: "Travel nature reels", growth: "+380%", score: 81, platform: "ig", tone: "e" },
];

export const VIRAL_SIGNALS = [
  { id: "tt", label: "TikTok", count: 28, delta: "+12", pct: 100, color: "#00f2ea" },
  { id: "yt", label: "YouTube", count: 24, delta: "+8", pct: 86, color: "#ff0000" },
  { id: "ig", label: "Instagram", count: 19, delta: "+6", pct: 68, color: "#e4405f" },
  { id: "x", label: "X", count: 14, delta: "+4", pct: 50, color: "#e8eef2" },
  { id: "fb", label: "Facebook", count: 11, delta: "+2", pct: 39, color: "#1877f2" },
  { id: "rd", label: "Reddit", count: 9, delta: "+5", pct: 32, color: "#ff4500" },
];

export const VIRAL_NICHES = [
  { label: "AI Creators", count: 28, x: 38, y: 42, r: 38, color: "#22d3ee" },
  { label: "Travel & Nature", count: 26, x: 72, y: 28, r: 34, color: "#34d399" },
  { label: "Productivity", count: 24, x: 58, y: 68, r: 30, color: "#a78bfa" },
  { label: "Retro Tech", count: 22, x: 22, y: 70, r: 26, color: "#f59e0b" },
  { label: "Pets", count: 18, x: 80, y: 62, r: 22, color: "#f472b6" },
  { label: "Finance", count: 14, x: 28, y: 28, r: 18, color: "#38bdf8" },
];

export const VIRAL_SOUNDS = [
  { rank: 1, title: "Neon Pulse Drop", growth: "+920%", platform: "tt", wave: [4, 10, 6, 14, 8, 16, 5, 12, 7, 15] },
  { rank: 2, title: "Lo-fi Desk Loop", growth: "+710%", platform: "ig", wave: [6, 8, 12, 7, 14, 9, 11, 5, 13, 8] },
  { rank: 3, title: "Retro Click Kit", growth: "+580%", platform: "tt", wave: [5, 12, 8, 10, 15, 6, 13, 9, 7, 14] },
  { rank: 4, title: "Ocean Soft Pad", growth: "+460%", platform: "ig", wave: [3, 7, 11, 6, 12, 8, 10, 14, 5, 9] },
  { rank: 5, title: "Founders Hook", growth: "+390%", platform: "tt", wave: [8, 5, 13, 9, 6, 15, 10, 7, 12, 11] },
];

export const VIRAL_HASHTAGS = [
  { tag: "#aipet", growth: "+820%", posts: "128K", spark: [20, 28, 35, 48, 62, 78, 90] },
  { tag: "#cozyproductivity", growth: "+640%", posts: "96K", spark: [18, 22, 30, 40, 55, 70, 82] },
  { tag: "#localai", growth: "+510%", posts: "74K", spark: [12, 18, 26, 34, 48, 60, 72] },
  { tag: "#retrotech", growth: "+430%", posts: "61K", spark: [10, 16, 22, 30, 42, 50, 58] },
  { tag: "#naturereels", growth: "+380%", posts: "54K", spark: [14, 18, 24, 28, 36, 44, 52] },
];

export const VIRAL_CHANCES = [
  { score: 92, title: "AI pet duo challenge", platform: "tt", tags: ["AI", "Pets", "Viral"], tone: "a" },
  { score: 88, title: "Cozy desk 60s", platform: "ig", tags: ["Productiviteit", "Aesthetic"], tone: "b" },
  { score: 86, title: "Local model flex", platform: "yt", tags: ["AI", "Demo"], tone: "c" },
  { score: 84, title: "Retro unbox ASMR", platform: "tt", tags: ["Tech", "ASMR"], tone: "d" },
  { score: 81, title: "EU nature POV", platform: "ig", tags: ["Travel", "Nature"], tone: "e" },
];

export const VIRAL_COMPETITORS = [
  { account: "NovaLabs", initials: "NL", topic: "AI pets", mentions: "1.2K", growth: "+420%", tone: "cyan" },
  { account: "DeskCraft", initials: "DC", topic: "Cozy desks", mentions: "980", growth: "+310%", tone: "purple" },
  { account: "PixelForge", initials: "PF", topic: "Local AI", mentions: "860", growth: "+280%", tone: "green" },
  { account: "TrailCut", initials: "TC", topic: "Nature POV", mentions: "720", growth: "+210%", tone: "gold" },
  { account: "RetroByte", initials: "RB", topic: "Unboxing", mentions: "640", growth: "+190%", tone: "blue" },
];

export const VIRAL_DETECTORS = [
  "Trend patroon analyse",
  "Sentiment analyse",
  "Sound matching",
  "Hashtag clustering",
  "Concurrent tracking",
  "Geo hotspot detectie",
];

export const VIRAL_CONFIDENCE = [
  { label: "Zeer hoog", count: 14, tone: "green" },
  { label: "Hoog", count: 21, tone: "cyan" },
  { label: "Gemiddeld", count: 10, tone: "gold" },
  { label: "Laag", count: 2, tone: "red" },
];

export const VIRAL_ALERTS = [
  { label: "Trending topic", value: "50%", tone: "green" },
  { label: "Virale kans", value: "80%", tone: "gold" },
  { label: "Ongebruikelijke piek", value: "200%", tone: "orange" },
  { label: "Negatief sentiment", value: "-60%", tone: "red" },
];

export const VIRAL_ACTIONS: Array<{ label: string; icon: FinalBetaIconName }> = [
  { label: "Trends vernieuwen", icon: "refresh" },
  { label: "Alert instellen", icon: "bolt" },
  { label: "Rapport genereren", icon: "file" },
  { label: "Exporteren", icon: "download" },
  { label: "Kans analyseren", icon: "target" },
  { label: "Trend monitoren", icon: "line" },
];

export const VIRAL_PLATFORM_SHORT: Record<string, { short: string; color: string }> = {
  tt: { short: "TT", color: "#00f2ea" },
  yt: { short: "YT", color: "#ff0000" },
  ig: { short: "IG", color: "#e4405f" },
  x: { short: "X", color: "#e8eef2" },
  fb: { short: "FB", color: "#1877f2" },
  rd: { short: "RD", color: "#ff4500" },
};
