/** FINALBETA Media Control overview mock data (pixel reference). */

export type MediaPlatform = "youtube" | "tiktok" | "instagram" | "facebook" | "x";

export const MEDIA_KPIS = [
  {
    id: "channels",
    label: "Kanalen actief",
    value: "5 / 6",
    hint: "83% verbonden",
    hintTone: "muted" as const,
    icon: "chart",
    tone: "cyan",
    live: true,
  },
  {
    id: "posts",
    label: "Posts vandaag",
    value: "12",
    hint: "↑ +33% vs gisteren",
    hintTone: "up" as const,
    icon: "file",
    tone: "cyan",
  },
  {
    id: "planned",
    label: "Publicaties gepland",
    value: "28",
    hint: "Volgende: over 42m",
    hintTone: "muted" as const,
    icon: "calendar",
    tone: "cyan",
  },
  {
    id: "reach",
    label: "Bereik (30 dagen)",
    value: "482.7K",
    hint: "↑ +28%",
    hintTone: "up" as const,
    icon: "users",
    tone: "cyan",
  },
  {
    id: "engagement",
    label: "Engagement rate",
    value: "6.4%",
    hint: "↑ +1.2%",
    hintTone: "up" as const,
    icon: "bolt",
    tone: "cyan",
  },
  {
    id: "viral",
    label: "Virale signalen",
    value: "3",
    hint: "↑ 2 kansen",
    hintTone: "up" as const,
    icon: "target",
    tone: "orange",
  },
] as const;

export const MEDIA_PLATFORM_STATS: Array<{
  id: MediaPlatform;
  label: string;
  value: string;
  trend: string;
  color: string;
}> = [
  { id: "youtube", label: "YouTube", value: "182.4K", trend: "↑ +28%", color: "#ff3b3b" },
  { id: "tiktok", label: "TikTok", value: "96.1K", trend: "↑ +42%", color: "#25f4ee" },
  { id: "instagram", label: "Instagram", value: "134.7K", trend: "↑ +21%", color: "#e1306c" },
  { id: "facebook", label: "Facebook", value: "52.3K", trend: "↑ +18%", color: "#1877f2" },
  { id: "x", label: "X", value: "17.2K", trend: "↑ +12%", color: "#e8eef2" },
];

/** 30-day reach series (0–100 scale for sparkPath). */
export const MEDIA_CHART_SERIES: Record<MediaPlatform, number[]> = {
  youtube: [42, 48, 45, 52, 58, 55, 62, 68, 64, 72, 78, 74, 82, 88, 84],
  tiktok: [18, 22, 28, 26, 34, 40, 38, 48, 54, 52, 62, 70, 68, 78, 86],
  instagram: [36, 40, 44, 42, 50, 56, 54, 60, 66, 70, 68, 74, 80, 78, 84],
  facebook: [22, 24, 26, 28, 30, 32, 34, 36, 38, 40, 42, 44, 46, 48, 50],
  x: [10, 12, 11, 14, 13, 16, 15, 18, 17, 20, 19, 22, 21, 24, 23],
};

export const MEDIA_CHART_LABELS = ["18 aug", "25 aug", "1 sep", "8 sep", "15 sep"];

export const MEDIA_QUEUE = [
  {
    id: "q1",
    title: "Van idee naar impact",
    tags: "#AI #Productiviteit",
    when: "Vandaag",
    time: "14:00",
    platform: "youtube" as MediaPlatform,
    thumb: "a",
  },
  {
    id: "q2",
    title: "3 AI tools die je leven makkelijker maken",
    tags: "#AITools #Tips",
    when: "Vandaag",
    time: "15:30",
    platform: "tiktok" as MediaPlatform,
    thumb: "b",
  },
  {
    id: "q3",
    title: "Behind the scenes",
    tags: "#HADES #BTS",
    when: "Vandaag",
    time: "17:00",
    platform: "instagram" as MediaPlatform,
    thumb: "c",
  },
  {
    id: "q4",
    title: "HADES Update v0.9",
    tags: "#Update #Roadmap",
    when: "Vandaag",
    time: "19:00",
    platform: "youtube" as MediaPlatform,
    thumb: "d",
  },
  {
    id: "q5",
    title: "Community Q&A",
    tags: "#Community #Live",
    when: "Morgen",
    time: "20:00",
    platform: "facebook" as MediaPlatform,
    thumb: "e",
  },
];

export const MEDIA_TRENDS = [
  {
    id: "t1",
    rank: 1,
    title: "AI agents",
    hint: "Hoge relevantie voor jouw niche",
    growth: "+320%",
    badge: "TRENDING" as const,
  },
  {
    id: "t2",
    rank: 2,
    title: "Prompt engineering",
    hint: "Groeiend in tech & business",
    growth: "+210%",
    badge: "TRENDING" as const,
  },
  {
    id: "t3",
    rank: 3,
    title: "AI video",
    hint: "Sterke engagement voorspeld",
    growth: "+180%",
    badge: "TRENDING" as const,
  },
  {
    id: "t4",
    rank: 4,
    title: "Automatisering",
    hint: "Toenemende zoekvolumes",
    growth: "+95%",
    badge: "OPKOMEND" as const,
  },
  {
    id: "t5",
    rank: 5,
    title: "AI in onderwijs",
    hint: "Kans voor thought leadership",
    growth: "+72%",
    badge: "OPKOMEND" as const,
  },
];

export const MEDIA_TOP_CONTENT = [
  {
    id: "c1",
    rank: 1,
    title: "AI verandert alles (en dit is waarom)",
    platform: "youtube" as MediaPlatform,
    views: "324.7K",
    likes: "12.4K",
    eng: "8.1%",
    date: "3 sep",
    thumb: "a",
  },
  {
    id: "c2",
    rank: 2,
    title: "5 AI tools in 60 seconden",
    platform: "tiktok" as MediaPlatform,
    views: "287.1K",
    likes: "22.5K",
    eng: "7.8%",
    date: "7 sep",
    thumb: "b",
  },
  {
    id: "c3",
    rank: 3,
    title: "Productieve ochtendroutine",
    platform: "instagram" as MediaPlatform,
    views: "156.3K",
    likes: "9.7K",
    eng: "6.9%",
    date: "1 sep",
    thumb: "c",
  },
  {
    id: "c4",
    rank: 4,
    title: "HADES v0.9 Preview",
    platform: "youtube" as MediaPlatform,
    views: "142.6K",
    likes: "8.1K",
    eng: "5.7%",
    date: "10 sep",
    thumb: "d",
  },
  {
    id: "c5",
    rank: 5,
    title: "Waarom AI geen hype is",
    platform: "facebook" as MediaPlatform,
    views: "98.4K",
    likes: "4.3K",
    eng: "4.8%",
    date: "5 sep",
    thumb: "e",
  },
];

export const MEDIA_CALENDAR = [
  {
    day: "17",
    month: "SEP",
    items: [
      { platform: "youtube" as MediaPlatform, title: "Van idee naar impact", time: "14:00" },
      { platform: "tiktok" as MediaPlatform, title: "3 AI tools die je leven makkelijker maken", time: "15:30" },
      { platform: "instagram" as MediaPlatform, title: "Behind the scenes", time: "17:00" },
    ],
  },
  {
    day: "18",
    month: "SEP",
    items: [
      { platform: "facebook" as MediaPlatform, title: "Community highlight", time: "10:00" },
      { platform: "instagram" as MediaPlatform, title: "Tips & tricks carousel", time: "16:00" },
    ],
  },
  {
    day: "19",
    month: "SEP",
    items: [{ platform: "youtube" as MediaPlatform, title: "HADES LIVE — Q&A", time: "20:00" }],
  },
  {
    day: "20",
    month: "SEP",
    items: [{ platform: "tiktok" as MediaPlatform, title: "Zaterdag | AI nieuws roundup", time: "11:00" }],
  },
];

export const MEDIA_AUTOMATIONS = [
  {
    id: "a1",
    title: "Content recycling",
    desc: "Herpubliceer top content",
    tone: "green",
    icon: "refresh",
    on: true,
  },
  {
    id: "a2",
    title: "Cross-platform publicatie",
    desc: "Publiceer naar alle kanalen",
    tone: "blue",
    icon: "globe",
    on: true,
  },
  {
    id: "a3",
    title: "AI ondertiteling",
    desc: "Genereer en vertaal ondertitels",
    tone: "cyan",
    icon: "mic",
    on: true,
  },
  {
    id: "a4",
    title: "Trend monitoring",
    desc: "Detecteer virale kansen",
    tone: "green",
    icon: "target",
    on: true,
  },
  {
    id: "a5",
    title: "Performance alerts",
    desc: "Meld bij afwijkingen",
    tone: "orange",
    icon: "bolt",
    on: true,
  },
] as const;

export const MEDIA_PIPELINE = [
  { id: "ideas", label: "Ideeën", count: 24, tone: "blue" },
  { id: "concepts", label: "Concepten", count: 14, tone: "purple" },
  { id: "review", label: "In review", count: 6, tone: "gold" },
  { id: "approved", label: "Goedgekeurd", count: 28, tone: "green" },
  { id: "published", label: "Gepubliceerd", count: 168, tone: "teal" },
] as const;

export const MEDIA_PERSONAS = [
  { id: "p1", name: "HADES Expert", role: "Tech insights & tutorials", online: true, tone: "a" },
  { id: "p2", name: "HADES Creator", role: "Behind the scenes", online: true, tone: "b" },
  { id: "p3", name: "HADES Visionary", role: "Thought leadership", online: true, tone: "c" },
  { id: "p4", name: "HADES Community", role: "Community & support", online: false, tone: "d" },
];

export const MEDIA_QUEUE_HEALTH = [
  { id: "ready", label: "Gereed voor publicatie", count: 28, tone: "green" },
  { id: "review", label: "Wachten op review", count: 6, tone: "gold" },
  { id: "drafts", label: "Concepten", count: 14, tone: "blue" },
  { id: "blocked", label: "Geblokkeerd", count: 1, tone: "red" },
] as const;

export const MEDIA_ALERTS = [
  { id: "n1", text: "Video gaat viraal op TikTok", ago: "12m", tone: "green" },
  { id: "n2", text: "Hoge engagement op YouTube", ago: "34m", tone: "gold" },
  { id: "n3", text: "Nieuw trend signaal: AI agents", ago: "1h", tone: "blue" },
  { id: "n4", text: "Instagram connectie hersteld", ago: "2h", tone: "gold" },
  { id: "n5", text: "Publicatie mislukt (Facebook)", ago: "2h", tone: "red" },
] as const;

export const MEDIA_QUICK_ACTIONS = [
  { id: "qa1", label: "Nieuwe post", icon: "external" },
  { id: "qa2", label: "Content plannen", icon: "calendar" },
  { id: "qa3", label: "AI idee genereren", icon: "bolt" },
  { id: "qa4", label: "Bulk upload", icon: "upload" },
] as const;

export const MEDIA_INFO: Array<{ k: string; v: string; tone?: "green" }> = [
  { k: "Status", v: "Online", tone: "green" },
  { k: "Kanalen actief", v: "5/6" },
  { k: "Totaal volgers", v: "482.7K" },
  { k: "Publicaties (30d)", v: "168" },
  { k: "Gem. engagement", v: "6.4%" },
  { k: "Laatste sync", v: "17 sep 2026, 13:22" },
];
