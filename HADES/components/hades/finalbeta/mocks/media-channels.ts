/** Mock data for FINALBETA media channel pages (YouTube / TikTok / Instagram / Facebook). */

export const YT_KPIS = [
  { id: "subs", label: "Totaal abonnees", value: "125K", trend: "+12%", hint: "+13.4K deze maand", icon: "users" },
  { id: "views", label: "Totaal weergaven", value: "12.8M", trend: "+28%", hint: "+2.8M deze maand", icon: "play" },
  { id: "watch", label: "Kijktijd (uren)", value: "171.2K", trend: "+35%", hint: "+44.2K deze maand", icon: "clock" },
  { id: "eng", label: "Engagement rate", value: "8.4%", trend: "+21%", hint: "Likes, reacties, shares", icon: "chart" },
  { id: "vids", label: "Video's", value: "248", trend: "+16%", hint: "+34 deze maand", icon: "image" },
] as const;

export const YT_PERF_STATS = [
  { label: "Weergaven", value: "1.2M", trend: "+26%", color: "#eab94f" },
  { label: "Unieke kijkers", value: "316K", trend: "+18%", color: "#22d3ee" },
  { label: "Kijktijd", value: "48.6K", trend: "+32%", color: "#f472b6" },
  { label: "Nieuwe abonnees", value: "13.4K", trend: "+12%", color: "#22c55e" },
] as const;

export const YT_PIPELINE = {
  ideeën: [
    { title: "AI Agents Explained", meta: "Concept · 2 dagen" },
    { title: "Future of AI Workflows", meta: "Concept · 4 dagen" },
    { title: "Local LLM Setup Guide", meta: "Concept · 1 week" },
    { title: "HADES Plugin Deep Dive", meta: "Concept · 3 dagen" },
    { title: "Offline AI Myths", meta: "Concept · 5 dagen" },
  ],
  productie: [
    { title: "HADES Use Cases (Script)", meta: "Script · 60%" },
    { title: "Automate Your Life", meta: "Edit · 40%" },
    { title: "Sovereign Pitch Short", meta: "Voice · 25%" },
  ],
  review: [
    { title: "HADES v0.9 Update Thumbnail", meta: "Review · Thumbnail" },
    { title: "AI Agents Cutdown", meta: "Review · Final cut" },
  ],
  klaar: [
    { title: "Build Smarter Tomorrow", meta: "Gereed" },
    { title: "Train. Own. Control.", meta: "Gereed" },
    { title: "Local Power Trailer", meta: "Gereed" },
  ],
} as const;

export const YT_UPLOADS = [
  {
    title: "HADES v0.9 Complete Overview",
    duration: "14:32",
    views: "128K",
    likes: "9.4K",
    comments: "612",
    ago: "2 dagen geleden",
  },
  {
    title: "AI Agents Explained in 10 Minutes",
    duration: "10:04",
    views: "96K",
    likes: "7.1K",
    comments: "448",
    ago: "5 dagen geleden",
  },
  {
    title: "Local LLM Setup for Creators",
    duration: "18:21",
    views: "84K",
    likes: "6.2K",
    comments: "391",
    ago: "1 week geleden",
  },
  {
    title: "From Idea to Impact — Workflow",
    duration: "12:48",
    views: "71K",
    likes: "5.4K",
    comments: "286",
    ago: "2 weken geleden",
  },
] as const;

export const YT_COMMUNITY = [
  { label: "Reacties", value: "1.4K", icon: "chat" },
  { label: "Likes", value: "9.8K", icon: "checkcircle" },
  { label: "Shares", value: "1.2K", icon: "external" },
  { label: "Sentimentscore", value: "92%", icon: "bolt" },
] as const;

export const YT_TRAFFIC = [
  { label: "YouTube zoeken", pct: 48 },
  { label: "Aanbevolen video's", pct: 28 },
  { label: "Externe bronnen", pct: 12 },
  { label: "Direct / Overig", pct: 12 },
] as const;

export const YT_TOP = [
  { rank: 1, title: "HADES v0.9 Complete Overview", views: "128K" },
  { rank: 2, title: "AI Agents Explained in 10 Minutes", views: "96K" },
  { rank: 3, title: "Local LLM Setup for Creators", views: "84K" },
  { rank: 4, title: "From Idea to Impact — Workflow", views: "71K" },
  { rank: 5, title: "Train. Own. Control. Trailer", views: "62K" },
] as const;

export const YT_UPLOAD_STATUS = [
  { name: "HADES_Trailer.mp4", status: "Uploaden", pct: 78, hint: "2m resterend" },
  { name: "AI_Agents_Guide.mp4", status: "Verwerken", pct: 42, hint: "Rendering" },
  { name: "Thumbnail_v09.png", status: "Gereed", pct: 100, hint: "Klaar" },
] as const;

export const TT_KPIS = [
  { id: "views", label: "Totaal views", value: "1.2M", trend: "+26%", hint: "Laatste 30 dagen", icon: "play" },
  { id: "reach", label: "Bereik", value: "316K", trend: "+18%", hint: "Unieke kijkers", icon: "users" },
  { id: "eng", label: "Gemiddelde engagement", value: "8.4%", trend: "+32%", hint: "Likes, reacties, shares", icon: "chart" },
  { id: "followers", label: "Volgers", value: "89K", trend: "+28%", hint: "Totaal volgers", icon: "globe" },
] as const;

export const TT_TRENDS = [
  { title: "Cinematic AI edits", tags: "#ai #cinematic #edit", growth: "+245%", status: "Trending", tone: "green" },
  { title: "Motivatie shorts", tags: "#mindset #discipline", growth: "+178%", status: "Trending", tone: "green" },
  { title: "Before/After transformaties", tags: "#ai #transformation", growth: "+132%", status: "Opkomst", tone: "gold" },
  { title: "AI tools in 30 sec", tags: "#aitools #productivity", growth: "+96%", status: "Opkomst", tone: "gold" },
  { title: "Dark aesthetic", tags: "#dark #aesthetic #cinematic", growth: "+88%", status: "Stabiel", tone: "blue" },
] as const;

export const TT_BEST = [
  { title: "AI verandert alles… ⚡", views: "452K", likes: "62K", comments: "1.4K", eng: "14.8%", ago: "3 dagen geleden" },
  { title: "Van idee naar realiteit", views: "318K", likes: "41K", comments: "987", eng: "13.2%", ago: "6 dagen geleden" },
  { title: "Deze AI tool moet je proberen", views: "276K", likes: "38K", comments: "1.2K", eng: "14.5%", ago: "9 dagen geleden" },
  { title: "Discipline > Motivatie", views: "198K", likes: "24K", comments: "624", eng: "12.4%", ago: "12 dagen geleden" },
  { title: "AI workflow in 30 seconden", views: "164K", likes: "22K", comments: "518", eng: "11.8%", ago: "2 weken geleden" },
] as const;

export const TT_CAL_EVENTS = [
  { day: 0, time: "10:00", label: "Behind the scenes", tone: "pub" },
  { day: 1, time: "12:00", label: "AI tip: Tool in 30s", tone: "plan" },
  { day: 2, time: "14:00", label: "Trend react Duet", tone: "concept" },
  { day: 3, time: "16:00", label: "Q&A Reacties", tone: "review" },
  { day: 4, time: "11:00", label: "Product teaser", tone: "plan" },
  { day: 5, time: "18:00", label: "Weekend hook", tone: "pub" },
  { day: 6, time: "09:00", label: "Motivatie short", tone: "concept" },
] as const;

export const TT_PUB_STATUS = [
  { label: "Gepubliceerd", value: 24, trend: "+33%", tone: "up" as const },
  { label: "Gepland", value: 6, trend: "+20%", tone: "up" as const },
  { label: "In concept", value: 4, trend: "0%", tone: "flat" as const },
  { label: "In review", value: 2, trend: "−33%", tone: "down" as const },
  { label: "Gefaald", value: 1, trend: "−50%", tone: "down" as const },
];

export const TT_WEEK_STATS = [
  { label: "Views", value: "428K", trend: "+22%" },
  { label: "Likes", value: "38K", trend: "+27%" },
  { label: "Reacties", value: "4.2K", trend: "+31%" },
  { label: "Shares", value: "6.8K", trend: "+18%" },
] as const;

export const FB_KPIS = [
  { id: "reach", label: "Pagina bereik", value: "38K", trend: "+24%", hint: "Afgelopen 7 dagen", icon: "chart" },
  { id: "eng", label: "Betrokkenheid", value: "4.2K", trend: "+36%", hint: "Likes, reacties, shares", icon: "users" },
  { id: "new", label: "Nieuwe volgers", value: "+612", trend: "+28%", hint: "Afgelopen 7 dagen", icon: "plus" },
  { id: "video", label: "Videoweergaven", value: "125K", trend: "+51%", hint: "Alle video's", icon: "play" },
] as const;

export const FB_SCHEDULE = [
  { day: 0, time: "09:00", label: "Pagina post (Aankondiging)", tone: "page" },
  { day: 1, time: "12:00", label: "Video post (Product demo)", tone: "video" },
  { day: 2, time: "14:00", label: "Afbeelding (Quote post)", tone: "image" },
  { day: 3, time: "16:00", label: "Live Video (Q&A sessie)", tone: "live" },
  { day: 4, time: "11:00", label: "Link post (Blog artikel)", tone: "link" },
  { day: 5, time: "18:00", label: "Community spotlight", tone: "page" },
  { day: 6, time: "10:00", label: "Weekend tip", tone: "image" },
] as const;

export const FB_CAMPAIGNS = [
  { title: "Product Lancering 2026", status: "Actief", tone: "green", done: 12, total: 20 },
  { title: "Community Groei", status: "Actief", tone: "green", done: 8, total: 15 },
  { title: "Video Awareness", status: "Planning", tone: "gold", done: 3, total: 10 },
  { title: "Webinar Registratie", status: "Actief", tone: "green", done: 14, total: 18 },
  { title: "Retargeting Engaged", status: "Pauze", tone: "gray", done: 5, total: 12 },
] as const;

export const FB_COMMUNITY = [
  { name: "Sophie de Vries", ago: "2 min geleden", text: "Geweldige update! Wanneer komt de volgende demo?", type: "Reactie" },
  { name: "Mark Jansen", ago: "18 min geleden", text: "HADES voelt eindelijk als een echt commandocentrum.", type: "Reactie" },
  { name: "Tech Reviews NL", ago: "1 uur geleden", text: "Interessant perspectief op lokale AI.", type: "Vermelding" },
  { name: "Lisa Vermeer", ago: "3 uur geleden", text: "Kunnen jullie een deep dive doen over plugins?", type: "Bericht" },
  { name: "Jonas Bakker", ago: "5 uur geleden", text: "De trailer ziet er strak uit 🔥", type: "Reactie" },
] as const;

export const FB_QUEUE = [
  { title: "Behind the Build: HADES AI", kind: "Video · 02:14", status: "Gereed", when: "Di 12 · 14:00" },
  { title: "Community Spotlight", kind: "Afbeelding", status: "Concept", when: "Wo 13 · 10:00" },
  { title: "Product Demo Cutdown", kind: "Video · 00:45", status: "Gereed", when: "Do 14 · 16:00" },
  { title: "Quote: Build smarter", kind: "Afbeelding", status: "Concept", when: "Vr 15 · 09:00" },
] as const;

export const IG_KPIS = [
  { id: "followers", label: "Volgers", value: "64K", trend: "+16%", hint: "Totaal volgers", icon: "users" },
  { id: "reach", label: "Bereik", value: "316K", trend: "+28%", hint: "Afgelopen 30 dagen", icon: "chart" },
  { id: "eng", label: "Engagement", value: "8.4%", trend: "+22%", hint: "Gemiddelde per post", icon: "bolt" },
  { id: "stories", label: "Stories views", value: "48K", trend: "+35%", hint: "Gemiddelde per story", icon: "image" },
  { id: "reels", label: "Reels weergaven", value: "1.2M", trend: "+46%", hint: "Afgelopen 30 dagen", icon: "play" },
] as const;

export const IG_CAL_EVENTS = [
  { day: 0, time: "10:00", label: "Behind the scenes", tone: "story" },
  { day: 1, time: "12:00", label: "Product demo", tone: "reel" },
  { day: 2, time: "14:00", label: "Quote design", tone: "post" },
  { day: 3, time: "16:00", label: "Daily update", tone: "story" },
  { day: 4, time: "11:00", label: "Tips & tricks", tone: "reel" },
  { day: 5, time: "17:00", label: "Community", tone: "post" },
  { day: 6, time: "09:00", label: "Weekend reel", tone: "reel" },
] as const;

export const IG_RECENT = [
  { title: "Build Smarter Tomorrow", views: "128K", likes: "9.2K", kind: "Reel" },
  { title: "AI Changes Everything", views: "96K", likes: "7.4K", kind: "Post" },
  { title: "Progress is a Choice", views: "84K", likes: "6.1K", kind: "Reel" },
  { title: "HADES Final Beta", views: "71K", likes: "5.8K", kind: "Post" },
  { title: "Local Power Trailer", views: "64K", likes: "4.9K", kind: "Reel" },
  { title: "Workflow in 30s", views: "58K", likes: "4.2K", kind: "Story" },
  { title: "Plugin Deep Dive", views: "52K", likes: "3.8K", kind: "Post" },
  { title: "Train. Own. Control.", views: "47K", likes: "3.5K", kind: "Reel" },
] as const;

export const IG_ASSETS = [
  { name: "Launch_Teaser_Reel.mp4", res: "1080×1920", pct: 85, status: "Rendering", tone: "blue" },
  { name: "Quote_Design.png", res: "1080×1350", pct: 100, status: "Gereed", tone: "green" },
  { name: "BehindScenes_Story.mp4", res: "1080×1920", pct: 42, status: "Uploading", tone: "blue" },
  { name: "Product_Shot.png", res: "1080×1080", pct: 73, status: "Processing", tone: "gold" },
] as const;

export const IG_TOP = [
  { title: "AI Changes Everything", views: "128K" },
  { title: "Build Smarter Tomorrow", views: "74K" },
  { title: "Progress is a Choice", views: "61K" },
] as const;

export const WEEK_DAYS = [
  { key: "ma", label: "Ma", date: 11 },
  { key: "di", label: "Di", date: 12 },
  { key: "wo", label: "Wo", date: 13 },
  { key: "do", label: "Do", date: 14 },
  { key: "vr", label: "Vr", date: 15 },
  { key: "za", label: "Za", date: 16 },
  { key: "zo", label: "Zo", date: 17 },
] as const;

export const CAL_HOURS = ["08:00", "10:00", "12:00", "14:00", "16:00", "18:00", "20:00"] as const;
