import { useState } from "react";
import { mediaPageArt, mediaPageHeroes } from "../../assets/mediaPagesAssets";
import { AppShell } from "../../layouts/AppShell";
import { useAppToast } from "../../state/useAppToast";
import { BarRow, Donut, PageHero, Panel, Pill } from "./mr-shared";

type PersonaKind = "audience" | "creator" | "brand";

type Persona = {
  id: string;
  name: string;
  archetype: string;
  kind: PersonaKind;
  age: string;
  reach: string;
  thumb: string;
  summary: string;
  demographics: { label: string; value: string }[];
  psych: string[];
  tone: string;
  themes: string[];
  matches: { name: string; score: string }[];
};

const TABS = [
  { id: "audience", label: "Audience Personas" },
  { id: "creator", label: "Creator & Brand" },
] as const;

const PERSONAS: Persona[] = [
  {
    id: "p1",
    name: "The Aspirer",
    archetype: "AMBITION ARCHETYPE",
    kind: "audience",
    age: "22–28",
    reach: "2.4M",
    thumb: mediaPageArt.personas[0],
    summary:
      "Gedreven door groei en status. Consumeert discipline-content in korte bursts, deelt wat bewijsbaar werkt, en mijdt fluff.",
    demographics: [
      { label: "Leeftijd", value: "22–28" },
      { label: "Locatie", value: "NL / BE / DE" },
      { label: "Inkomen", value: "€32k–€55k" },
      { label: "Platforms", value: "TikTok · IG · YT" },
    ],
    psych: ["Status-driven", "High agency", "FOMO-aware", "Proof-seeking", "Night owl"],
    tone: "Direct, ritmisch, zero excuses. Korte zinnen. Call-to-action als bevel.",
    themes: ["Discipline", "Compounding", "Identity shift", "Morning systems"],
    matches: [
      { name: "Discipline Changes Everything", score: "94%" },
      { name: "Build in Silence", score: "88%" },
      { name: "A Brighter Tomorrow", score: "81%" },
    ],
  },
  {
    id: "p2",
    name: "Strategist",
    archetype: "SYSTEMS ARCHETYPE",
    kind: "audience",
    age: "28–40",
    reach: "1.1M",
    thumb: mediaPageArt.personas[1],
    summary: "Denkt in frameworks. Wil frameworks, dashboards en herhaalbare playbooks — geen motivatiepraat.",
    demographics: [
      { label: "Leeftijd", value: "28–40" },
      { label: "Locatie", value: "EU hubs" },
      { label: "Inkomen", value: "€55k–€110k" },
      { label: "Platforms", value: "LinkedIn · YT" },
    ],
    psych: ["Analytical", "ROI-first", "Long-form ok", "Skeptical"],
    tone: "Kalm, precies, data-first. Minder hype, meer structuur.",
    themes: ["Systems", "Ops", "Attribution", "Playbooks"],
    matches: [
      { name: "Signal Over Noise", score: "91%" },
      { name: "Neural Edge Briefing", score: "86%" },
    ],
  },
  {
    id: "p3",
    name: "Explorer",
    archetype: "CURIOSITY ARCHETYPE",
    kind: "audience",
    age: "18–24",
    reach: "3.8M",
    thumb: mediaPageArt.personas[2],
    summary: "Scrolt breed, ontdekt niches snel, blijft bij merken die verrassen zonder te verkopen.",
    demographics: [
      { label: "Leeftijd", value: "18–24" },
      { label: "Locatie", value: "Global EN" },
      { label: "Inkomen", value: "Student / early" },
      { label: "Platforms", value: "TikTok · Reels" },
    ],
    psych: ["Novelty seeker", "Visual-first", "Trend fluent"],
    tone: "Speels, snelle cuts, cliffhangers, memes als brug.",
    themes: ["Trends", "Behind the scenes", "Challenges"],
    matches: [
      { name: "Audience Gravity", score: "90%" },
      { name: "The Compounding Mind", score: "77%" },
    ],
  },
  {
    id: "p4",
    name: "Realist",
    archetype: "GROUNDING ARCHETYPE",
    kind: "audience",
    age: "30–45",
    reach: "890K",
    thumb: mediaPageArt.personas[3],
    summary: "Want bewijs, risico’s en eerlijke trade-offs. Reageert op case studies en cijfers.",
    demographics: [
      { label: "Leeftijd", value: "30–45" },
      { label: "Locatie", value: "NL / UK" },
      { label: "Inkomen", value: "€45k–€85k" },
      { label: "Platforms", value: "YT · FB" },
    ],
    psych: ["Risk-aware", "Evidence-led", "Low hype"],
    tone: "Eerlijk, sober, ‘hier is wat faalde’. Geen overclaims.",
    themes: ["Case studies", "Risk", "Budget realism"],
    matches: [
      { name: "Markets After Midnight", score: "85%" },
      { name: "Signal Over Noise", score: "80%" },
    ],
  },
  {
    id: "p5",
    name: "Creator",
    archetype: "MAKER ARCHETYPE",
    kind: "creator",
    age: "24–34",
    reach: "640K",
    thumb: mediaPageArt.personas[4],
    summary: "Produceert zelf content. Zoekt templates, hooks en collab-formats die herbruikbaar zijn.",
    demographics: [
      { label: "Leeftijd", value: "24–34" },
      { label: "Locatie", value: "EU creators" },
      { label: "Inkomen", value: "Creator income" },
      { label: "Platforms", value: "All" },
    ],
    psych: ["Tool-obsessed", "Collab-ready", "Format hopper"],
    tone: "Collegiaal, ‘steal this’, process-transparant.",
    themes: ["Hooks", "Templates", "Collabs", "Workflow"],
    matches: [
      { name: "Weekly Recap Reel", score: "92%" },
      { name: "Caption Batch · Q2", score: "84%" },
    ],
  },
  {
    id: "p6",
    name: "Executive",
    archetype: "BRAND ARCHETYPE",
    kind: "brand",
    age: "35–55",
    reach: "120K",
    thumb: mediaPageArt.personas[5],
    summary: "Beslist over budget en merkconsistentie. Wil risk controls, brand kits en meetbare lift.",
    demographics: [
      { label: "Leeftijd", value: "35–55" },
      { label: "Locatie", value: "HQ markets" },
      { label: "Inkomen", value: "Exec / CMO" },
      { label: "Platforms", value: "LI · YT" },
    ],
    psych: ["Brand-safe", "KPI-driven", "Delegates"],
    tone: "Boardroom-klaar. Korte briefs, heldere outcomes.",
    themes: ["Brand kit", "Governance", "ROAS", "Reputation"],
    matches: [
      { name: "Brand Kit Refresh", score: "96%" },
      { name: "A Brighter Tomorrow", score: "89%" },
    ],
  },
];

const SEGMENTS = [
  { label: "Gen Z", value: 38, color: "#22c9d6" },
  { label: "Millennials", value: 34, color: "#d4af37" },
  { label: "Gen X", value: 18, color: "#818cf8" },
  { label: "Other", value: 10, color: "#4ade80" },
] as const;

const JOURNEY = [
  { step: "01", title: "Awareness", desc: "Short-form hooks" },
  { step: "02", title: "Interest", desc: "Proof clips" },
  { step: "03", title: "Consider", desc: "Deep dives" },
  { step: "04", title: "Convert", desc: "Offer CTA" },
  { step: "05", title: "Advocate", desc: "UGC loops" },
] as const;

const INTERESTS = [
  { label: "Discipline / mindset", value: 86, color: "#22c9d6" },
  { label: "Markets & macro", value: 72, color: "#d4af37" },
  { label: "Creator tools", value: 64, color: "#818cf8" },
  { label: "Brand systems", value: 58, color: "#4ade80" },
] as const;

const FORMATS = [
  { label: "Short video", value: 91, color: "#22c9d6" },
  { label: "Carousel", value: 68, color: "#d4af37" },
  { label: "Long-form", value: 54, color: "#818cf8" },
  { label: "Threads", value: 41, color: "#4ade80" },
] as const;

export function MediaPersonasPage() {
  const toast = useAppToast();
  const [tab, setTab] = useState<(typeof TABS)[number]["id"]>("audience");
  const [selectedId, setSelectedId] = useState("p1");
  const [query, setQuery] = useState("");

  const selected = PERSONAS.find((p) => p.id === selectedId) ?? PERSONAS[0];
  const cards = PERSONAS.filter((p) => {
    if (!query.trim()) return true;
    const hay = `${p.name} ${p.archetype} ${p.themes.join(" ")}`.toLowerCase();
    return hay.includes(query.trim().toLowerCase());
  });

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Personas Mode"
      searchPlaceholder="Search media, content, campaigns, platforms, or ask Leviathan..."
      systemItems={["MEMORY ONLINE", "SYSTEMS OPERATIONAL"]}
      layout="wide"
      pageClass="lv-app--media-research"
    >
      <main className="lv-main lv-mr-main">
        <PageHero image={mediaPageHeroes.personas} title="PERSONAS" imageOnly />

        <Panel>
          <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 12, justifyContent: "space-between" }}>
            <div className="lv-mr-tabs" role="tablist" style={{ border: 0 }}>
              {TABS.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  role="tab"
                  className={`lv-mr-tab${tab === t.id ? " is-active" : ""}`}
                  onClick={() => setTab(t.id)}
                >
                  {t.label}
                </button>
              ))}
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, fontSize: 12 }}>
              <Pill tone="cyan">12 Total</Pill>
              <Pill tone="gold">8 Audience</Pill>
              <Pill tone="green">3 Creator</Pill>
              <Pill tone="blue">1 Brand</Pill>
            </div>
          </div>

          <div className="lv-mr-toolbar">
            <input
              className="lv-mr-input"
              style={{ minWidth: 220, flex: 1 }}
              placeholder="Zoek personas, archetypes, themes..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <select className="lv-mr-select" defaultValue="all" aria-label="Segment">
              <option value="all">Alle segmenten</option>
              <option value="genz">Gen Z</option>
              <option value="mill">Millennials</option>
              <option value="genx">Gen X</option>
            </select>
            <select className="lv-mr-select" defaultValue="reach" aria-label="Sorteren">
              <option value="reach">Sorteer: Reach</option>
              <option value="name">Naam</option>
              <option value="match">Match score</option>
            </select>
            <button type="button" className="lv-mr-btn lv-mr-btn--gold" onClick={() => toast("Create Persona")}>
              + Create Persona
            </button>
          </div>
        </Panel>

        <section className="lv-mp-cards">
          {(cards.length ? cards : PERSONAS).map((p) => {
            const dimmed =
              (tab === "audience" && p.kind !== "audience") || (tab === "creator" && p.kind === "audience");
            return (
              <button
                key={p.id}
                type="button"
                className={`lv-mp-card${p.id === selected.id ? " is-active" : ""}`}
                style={dimmed ? { opacity: 0.45 } : undefined}
                onClick={() => setSelectedId(p.id)}
              >
                <div className="lv-mp-card-media">
                  <img src={p.thumb} alt="" />
                </div>
                <div className="lv-mp-card-body">
                  <strong>{p.name}</strong>
                  <div className="arch">{p.archetype}</div>
                  <div className="lv-mr-muted" style={{ fontSize: 11 }}>
                    {p.age} · {p.reach}
                  </div>
                </div>
              </button>
            );
          })}
        </section>

        <section className="lv-mr-split" style={{ gridTemplateColumns: "minmax(0, 1.4fr) minmax(280px, 0.75fr)" }}>
          <div style={{ display: "grid", gap: 10 }}>
            <section className="lv-mp-grid">
              <Panel title="Audience Segmentation">
                <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                  <Donut slices={SEGMENTS.map((s) => ({ value: s.value, color: s.color }))} center="100%" />
                  <div style={{ display: "grid", gap: 6, fontSize: 12, flex: 1 }}>
                    {SEGMENTS.map((s) => (
                      <div key={s.label} style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                        <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
                          <span style={{ width: 8, height: 8, borderRadius: 99, background: s.color }} />
                          {s.label}
                        </span>
                        <strong>{s.value}%</strong>
                      </div>
                    ))}
                  </div>
                </div>
              </Panel>

              <Panel title="Persona Relationships">
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center", justifyContent: "center", padding: "8px 0" }}>
                  {PERSONAS.map((p, i) => (
                    <button
                      key={p.id}
                      type="button"
                      onClick={() => setSelectedId(p.id)}
                      style={{
                        width: i === 0 ? 72 : 56,
                        height: i === 0 ? 72 : 56,
                        borderRadius: "50%",
                        border: p.id === selected.id ? "2px solid #d4af37" : "1px solid rgba(70,120,160,0.35)",
                        overflow: "hidden",
                        padding: 0,
                        cursor: "pointer",
                        background: "#080a0c",
                      }}
                      title={p.name}
                    >
                      <img src={p.thumb} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                    </button>
                  ))}
                </div>
                <p className="lv-mr-muted" style={{ fontSize: 11, margin: "4px 0 0", textAlign: "center" }}>
                  Aspirer ↔ Creator · Strategist ↔ Executive · Explorer ↔ Realist
                </p>
              </Panel>

              <Panel title="Audience Journey">
                <div style={{ display: "grid", gap: 8 }}>
                  {JOURNEY.map((j) => (
                    <div key={j.step} style={{ display: "grid", gridTemplateColumns: "28px 1fr", gap: 8, alignItems: "start" }}>
                      <span style={{ color: "#c5a059", fontSize: 11, fontWeight: 700 }}>{j.step}</span>
                      <div>
                        <strong style={{ color: "#f0ebe3", fontSize: 12 }}>{j.title}</strong>
                        <div className="lv-mr-muted" style={{ fontSize: 11 }}>
                          {j.desc}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </Panel>

              <Panel title="Interests / Formats">
                <div style={{ display: "grid", gap: 10 }}>
                  <div>
                    <div className="lv-mr-muted" style={{ fontSize: 10, marginBottom: 6, letterSpacing: "0.08em" }}>
                      INTERESTS
                    </div>
                    {INTERESTS.map((row) => (
                      <BarRow key={row.label} label={row.label} value={row.value} color={row.color} />
                    ))}
                  </div>
                  <div>
                    <div className="lv-mr-muted" style={{ fontSize: 10, marginBottom: 6, letterSpacing: "0.08em" }}>
                      FORMATS
                    </div>
                    {FORMATS.map((row) => (
                      <BarRow key={row.label} label={row.label} value={row.value} color={row.color} />
                    ))}
                  </div>
                </div>
              </Panel>
            </section>
          </div>

          <Panel title="PERSONA DETAIL" action={<Pill tone="gold">{selected.archetype}</Pill>}>
            <div className="lv-mp-detail-media">
              <img src={mediaPageArt.personaDetail} alt="" />
            </div>
            <div style={{ marginTop: 10 }}>
              <strong style={{ color: "#f0ebe3", fontFamily: "var(--lv-font-display)", fontSize: 18 }}>{selected.name}</strong>
              <p className="lv-mr-muted" style={{ margin: "6px 0 0", fontSize: 12, lineHeight: 1.45 }}>
                {selected.summary}
              </p>
            </div>

            <div style={{ marginTop: 12 }}>
              <div className="lv-mr-panel-title" style={{ marginBottom: 8 }}>
                Demographics
              </div>
              <div className="lv-ml-meta">
                {selected.demographics.map((d) => (
                  <div key={d.label}>
                    <span className="lv-mr-muted">{d.label}</span>
                    <strong>{d.value}</strong>
                  </div>
                ))}
              </div>
            </div>

            <div style={{ marginTop: 12 }}>
              <div className="lv-mr-panel-title" style={{ marginBottom: 8 }}>
                Psychographic tags
              </div>
              <div className="lv-mp-tags">
                {selected.psych.map((tag) => (
                  <span key={tag} className="lv-mp-tag">
                    {tag}
                  </span>
                ))}
              </div>
            </div>

            <div style={{ marginTop: 12 }}>
              <div className="lv-mr-panel-title" style={{ marginBottom: 6 }}>
                Tone of voice
              </div>
              <p style={{ margin: 0, fontSize: 12, lineHeight: 1.45, color: "#c5d0d8" }}>{selected.tone}</p>
            </div>

            <div style={{ marginTop: 12 }}>
              <div className="lv-mr-panel-title" style={{ marginBottom: 8 }}>
                Content themes
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {selected.themes.map((t) => (
                  <Pill key={t} tone="cyan">
                    {t}
                  </Pill>
                ))}
              </div>
            </div>

            <div style={{ marginTop: 14 }}>
              <div className="lv-mr-panel-title" style={{ marginBottom: 8 }}>
                Top Campaign Matches
              </div>
              {selected.matches.map((m) => (
                <div key={m.name} className="lv-mp-match">
                  <span>
                    {m.name}{" "}
                    <span className="lv-mr-good" style={{ marginLeft: 6 }}>
                      {m.score}
                    </span>
                  </span>
                  <button type="button" className="lv-mr-btn lv-mr-btn--gold" onClick={() => toast(`Use: ${m.name}`)}>
                    Use
                  </button>
                </div>
              ))}
            </div>
          </Panel>
        </section>
      </main>
    </AppShell>
  );
}
