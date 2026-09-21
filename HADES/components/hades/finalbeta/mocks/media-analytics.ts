import type { FinalBetaIconName } from "../icons";

export type AnalyticsRange = "7d" | "30d" | "90d" | "1j";
export type AudienceTab = "leeftijd" | "geslacht" | "locatie" | "interesses";

export const ANALYTICS_KPIS: Array<{
  id: string;
  label: string;
  value: string;
  trend: string;
  icon: FinalBetaIconName;
  iconTone: string;
}> = [
  { id: "reach", label: "Totaal bereik", value: "482.7K", trend: "+28%", icon: "chart", iconTone: "cyan" },
  { id: "views", label: "Videoweergaven", value: "134.7K", trend: "+21%", icon: "image", iconTone: "cyan" },
  { id: "eng", label: "Betrokkenheid", value: "6.4%", trend: "+1.2%", icon: "bolt", iconTone: "pink" },
  { id: "followers", label: "Nieuwe volgers", value: "12.3K", trend: "+42%", icon: "users", iconTone: "cyan" },
  { id: "ctr", label: "CTR (links)", value: "3.8%", trend: "+0.9%", icon: "target", iconTone: "green" },
  { id: "conv", label: "Conversies", value: "1.247", trend: "+35%", icon: "database", iconTone: "gold" },
];

export const ANALYTICS_RANGES: Array<{ id: AnalyticsRange; label: string }> = [
  { id: "7d", label: "7d" },
  { id: "30d", label: "30d" },
  { id: "90d", label: "90d" },
  { id: "1j", label: "1j" },
];

export const ANALYTICS_PERF = {
  labels: ["18 aug", "25 aug", "1 sep", "8 sep", "15 sep"],
  yLabels: ["200K", "100K", "0"],
  series: [
    { id: "reach", label: "Bereik", color: "#38bdf8", values: [42, 55, 68, 88, 96, 110, 125, 140, 155, 168, 175, 188] },
    { id: "views", label: "Weergaven", color: "#f472b6", values: [28, 34, 40, 48, 55, 62, 70, 78, 85, 92, 98, 105] },
    { id: "eng", label: "Engagement rate", color: "#2dd4bf", values: [18, 22, 26, 30, 34, 38, 42, 46, 50, 54, 58, 62] },
    { id: "conv", label: "Conversies", color: "#4ade80", values: [8, 10, 12, 16, 20, 24, 28, 32, 36, 40, 44, 48] },
  ],
};

export const ANALYTICS_ATTRIBUTION: Array<{
  label: string;
  count: number;
  pct: string;
  color: string;
}> = [
  { label: "YouTube", count: 38, pct: "38%", color: "#ff3b3b" },
  { label: "TikTok", count: 24, pct: "24%", color: "#25f4ee" },
  { label: "Instagram", count: 18, pct: "18%", color: "#e4405f" },
  { label: "Facebook", count: 10, pct: "10%", color: "#1877f2" },
  { label: "LinkedIn", count: 6, pct: "6%", color: "#0a66c2" },
  { label: "Web / Overig", count: 4, pct: "4%", color: "#758392" },
];

export const ANALYTICS_AUDIENCE_TABS: Array<{ id: AudienceTab; label: string }> = [
  { id: "leeftijd", label: "Leeftijd" },
  { id: "geslacht", label: "Geslacht" },
  { id: "locatie", label: "Locatie" },
  { id: "interesses", label: "Interesses" },
];

export const ANALYTICS_AUDIENCE: Record<
  AudienceTab,
  Array<{ label: string; pct: number }>
> = {
  leeftijd: [
    { label: "13-17", pct: 8 },
    { label: "18-24", pct: 28 },
    { label: "25-34", pct: 34 },
    { label: "35-44", pct: 20 },
    { label: "45-54", pct: 7 },
    { label: "55+", pct: 3 },
  ],
  geslacht: [
    { label: "Man", pct: 54 },
    { label: "Vrouw", pct: 42 },
    { label: "Overig", pct: 4 },
  ],
  locatie: [
    { label: "Nederland", pct: 48 },
    { label: "België", pct: 18 },
    { label: "Duitsland", pct: 12 },
    { label: "VS", pct: 10 },
    { label: "UK", pct: 7 },
    { label: "Overig", pct: 5 },
  ],
  interesses: [
    { label: "AI & Tech", pct: 36 },
    { label: "Creatief", pct: 22 },
    { label: "Business", pct: 18 },
    { label: "Educatie", pct: 14 },
    { label: "Lifestyle", pct: 10 },
  ],
};

export const ANALYTICS_COHORT = {
  labels: ["Week 32", "Week 33", "Week 34", "Week 35", "Week 36", "Week 37"],
  series: [
    { id: "reach", label: "Bereik", color: "#38bdf8", values: [48, 55, 62, 70, 78, 88] },
    { id: "eng", label: "Engagement", color: "#f472b6", values: [22, 28, 32, 38, 44, 52] },
    { id: "conv", label: "Conversies", color: "#4ade80", values: [10, 14, 18, 22, 28, 34] },
  ],
};

export const ANALYTICS_FUNNEL = [
  { id: "views", label: "Weergaven", value: "134.7K", pct: "100%", width: 100, color: "#38bdf8" },
  { id: "clicks", label: "Klikken", value: "5.1K", pct: "3.8%", width: 62, color: "#22d3ee" },
  { id: "leads", label: "Leads", value: "1.9K", pct: "1.4%", width: 38, color: "#a78bfa" },
  { id: "conv", label: "Conversies", value: "1.247", pct: "0.9%", width: 24, color: "#eab94f" },
];

export type AnalyticsPlatformId = "youtube" | "tiktok" | "instagram" | "facebook" | "linkedin" | "x";

export const ANALYTICS_PLATFORMS: Array<{
  id: AnalyticsPlatformId;
  label: string;
  reach: string;
  engagement: string;
  growth: string;
}> = [
  { id: "youtube", label: "YouTube", reach: "182.4K", engagement: "6.1%", growth: "+28%" },
  { id: "tiktok", label: "TikTok", reach: "116.2K", engagement: "8.4%", growth: "+42%" },
  { id: "instagram", label: "Instagram", reach: "86.8K", engagement: "5.2%", growth: "+18%" },
  { id: "facebook", label: "Facebook", reach: "48.3K", engagement: "3.1%", growth: "+9%" },
  { id: "linkedin", label: "LinkedIn", reach: "28.9K", engagement: "4.6%", growth: "+15%" },
  { id: "x", label: "X", reach: "20.1K", engagement: "2.8%", growth: "+6%" },
];

export const ANALYTICS_BEST = [
  {
    rank: 1,
    title: "AI verandert alles",
    platform: "youtube" as AnalyticsPlatformId,
    date: "12 sep",
    reach: "182.4K",
    eng: "8.4%",
    conversions: "324",
    thumb: "a",
  },
  {
    rank: 2,
    title: "30 dagen local AI",
    platform: "tiktok" as AnalyticsPlatformId,
    date: "10 sep",
    reach: "96.2K",
    eng: "9.1%",
    conversions: "218",
    thumb: "b",
  },
  {
    rank: 3,
    title: "Creator stack 2026",
    platform: "instagram" as AnalyticsPlatformId,
    date: "8 sep",
    reach: "74.5K",
    eng: "7.6%",
    conversions: "186",
    thumb: "c",
  },
  {
    rank: 4,
    title: "HADES live demo",
    platform: "youtube" as AnalyticsPlatformId,
    date: "5 sep",
    reach: "68.1K",
    eng: "7.2%",
    conversions: "154",
    thumb: "d",
  },
  {
    rank: 5,
    title: "Short-form playbook",
    platform: "tiktok" as AnalyticsPlatformId,
    date: "2 sep",
    reach: "54.8K",
    eng: "6.9%",
    conversions: "132",
    thumb: "e",
  },
];

export const ANALYTICS_WORST = [
  {
    rank: 1,
    title: "Oude workflow",
    platform: "youtube" as AnalyticsPlatformId,
    date: "3 sep",
    reach: "4.2K",
    eng: "0.8%",
    conversions: "12",
    thumb: "f",
  },
  {
    rank: 2,
    title: "Recap week 28",
    platform: "facebook" as AnalyticsPlatformId,
    date: "28 aug",
    reach: "5.1K",
    eng: "1.1%",
    conversions: "9",
    thumb: "g",
  },
  {
    rank: 3,
    title: "Behind the scenes B-roll",
    platform: "instagram" as AnalyticsPlatformId,
    date: "22 aug",
    reach: "6.4K",
    eng: "1.4%",
    conversions: "14",
    thumb: "h",
  },
  {
    rank: 4,
    title: "Q2 metrics dump",
    platform: "linkedin" as AnalyticsPlatformId,
    date: "18 aug",
    reach: "7.8K",
    eng: "1.6%",
    conversions: "11",
    thumb: "i",
  },
  {
    rank: 5,
    title: "Thread: oude tips",
    platform: "x" as AnalyticsPlatformId,
    date: "14 aug",
    reach: "3.9K",
    eng: "0.9%",
    conversions: "6",
    thumb: "j",
  },
];

export const ANALYTICS_BENCHMARKS = [
  { label: "Totaal bereik", value: "+28%", tone: "green" as const },
  { label: "Engagement", value: "+12%", tone: "green" as const },
  { label: "Conversies", value: "+35%", tone: "green" as const },
  { label: "T.o.v. sector", value: "+62%", tone: "green" as const },
];

export const ANALYTICS_ANOMALIES = [
  { id: "a1", title: "Piek in bereik", delta: "+320%", when: "12 sep 14:00", tone: "green" as const },
  { id: "a2", title: "Daling engagement", delta: "-48%", when: "8 sep 03:00", tone: "red" as const },
  { id: "a3", title: "Ongebruikelijk verkeer", delta: "+210%", when: "5 sep 11:00", tone: "gold" as const },
  { id: "a4", title: "Nieuwe doelgroep", delta: "+65%", when: "14 sep 19:00", tone: "blue" as const },
];

export const ANALYTICS_ACTIONS: Array<{ label: string; icon: FinalBetaIconName }> = [
  { label: "Nieuw rapport", icon: "file" },
  { label: "Rapport plannen", icon: "calendar" },
  { label: "Exporteren", icon: "download" },
  { label: "Insights genereren", icon: "bolt" },
  { label: "Doelgroepanalyse", icon: "users" },
  { label: "Concurrenten", icon: "target" },
];

export const ANALYTICS_PERIOD = {
  period: "Afgelopen 30 dagen",
  compare: "Vorige periode",
  range: "18 aug 2026 → 17 sep 2026",
};
